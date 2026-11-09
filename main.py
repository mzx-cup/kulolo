"""手机遥控台入口：python main.py

启动后自动打开浏览器（零配置），页面上点「一键运行」即可自动操控手机。
只绑定 127.0.0.1 —— 绑 0.0.0.0 会让同局域网任何人控制插着的手机，绝不能那么做。

可选参数：
    python main.py              默认 127.0.0.1:8765 并自动开浏览器
    python main.py --port 9000  换端口
    python main.py --no-open    不自动开浏览器
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import adbutils
import card_gallery
import card_probe
import locale_kit
import locale_switch
import runtime_paths
import scenario_alarm
import scenario_alarm_close
import scenario_alarm_prompt
import scenario_app_suggest
import scenario_birthday
import scenario_boomplay_music
import scenario_cross_region
import scenario_festival
import scenario_greeting
import scenario_power_outage
import scenario_power_restore
import scenario_power_saving
import scenario_satellite
import scenario_smart_traffic
import scenario_summary_report
import scenario_personal_knowledge
from phone_ctl import Device, UiError

HOST = "127.0.0.1"
PORT = 8765
# 前端产物是只读资源：源码直跑时在工作目录，打包后在 exe 的解包目录里。
WEB = runtime_paths.resource_path("web")

# 场景注册表：前端左侧列表按此渲染，POST /api/scenario/<id> 按此分发。
# params 用声明式描述，前端据此动态生成参数行（time 类型会拆出 hour/minute 两个输入）。
# 新增场景时还可以按需加几个可选字段（都不写也能正常工作）：
#   group      左侧目录分组名；不写则按 id 前缀推断（festival_* → 节日祝福卡片，其余 → 重要日卡片）
#   retryable  卡片未触发时是否提供「下月同日重跑」；不写则节日场景 False、其余 True
#   icon       卡片图标键：cake / heart / exam / ticket / pin / lantern / spark / calendar / gift / star / clock ...
#   accent     保留字段，前端目前按 group 自动配色
#   card_keywords  卡片认领文案（见下）
#
# card_keywords 怎么用
# --------------------
# 场景跑完不再弹「卡片出来了吗」让人点，而是拿这串关键词去设备上自动认卡
# （card_probe：先看锁屏原子卡片，再回桌面翻智慧建议轮播）。命中就截图存进
# 卡片库、算这一轮成功。
#
# 写法约定：
#   * **具体的放前面**：先写卡片标题里的固定片段（如 "幸运四叶草"），
#     再退到更泛的词；顺序就是匹配优先级。
#   * 能跨语言就都写上：卡片文案跟着系统语言走，只写中文在英语/阿拉伯语
#     环境下必然认不出。
#   * 也可以写成 `lambda r: (...)`：卡片标题里带随机名字时（如 Bday110792）
#     要等场景跑到一半才知道，交给回调按 `r.card_hint` 现算。
#   * 不写这个字段 = 这个场景不做自动识别（回调直接放行，行为同以前）。

# 重要日类卡片的认领文案，按「卡片类型」分三组。
#
# 这些卡大多是**锁屏卡片**：标题里带这一轮随机生成的名字（Bday110792 之类），
# 副标题随卡片不同而不同。所以主判据一律用 `r.card_hint`（场景跑到一半把
# 名字写进来），拿不到再退到各类型的固定文案。
#
# 为什么按类型分：策划案卡是「xx·生日 · 3 天后」、考前提醒是「考试还有 3 天」
# 这类，跟祝福卡的「今天是xx / 抽取你的幸运四叶草」完全不重叠；用一套通用
# 词会把「没出卡」误判成「出了别的卡」。
GREETING_CARD_KEYWORDS = (
    "今天是", "幸运四叶草", "抽取你的", "四叶草", "祝你顺利", "clover",
)
# 策划案卡（生日/纪念日/考试前 3 天）：文案形如「xx·生日 · 3 天后」
PLAN_CARD_KEYWORDS = (
    "天后", "策划案", "还有 3 天", "3 天后", "days later", "in 3 days",
    "birthday plan", "upcoming",
)
# 追星 / 重要日提醒类：文案更泛，靠名字 + 通用词兜底
REMINDER_CARD_KEYWORDS = (
    "今天是", "提醒", "重要日", "观演", "追星", "演出", "reminder", "today",
)


def important_day_keywords(kind: str):
    """按卡片类型造一个 callable：优先本轮随机名字，再退到该类型的固定文案。"""
    fallbacks = {
        "greeting": GREETING_CARD_KEYWORDS,
        "plan": PLAN_CARD_KEYWORDS,
        "reminder": REMINDER_CARD_KEYWORDS,
    }[kind]

    def _kw(r) -> tuple[str, ...]:
        name = (getattr(r, "card_hint", "") or "").strip()
        own = (name,) if name else ()
        return own + fallbacks

    return _kw


# 兼容旧名字（exam_greeting 等场景已用）
greeting_keywords = important_day_keywords("greeting")

# 时间管理三张卡片的触发方式：真实触发要改系统时间 + 建/关闹钟 + 息屏等待；
# Mock 触发靠 TransAtomicBrain 调试页一键注入事件，几秒钟出卡。
METHOD_OPTIONS = [
    {"v": "real", "t": "真实触发（改时间 + 建闹钟）"},
    {"v": "mock", "t": "Mock 触发（TransAtomicBrain 一键出卡）"},
]

# 触发前要求手机使用哪种系统语言。选中的值会在跑场景之前写进
# `settings put system system_locales` 并重启一次（约 1~2 分钟），
# 让整轮触发都在同一种界面语言下进行。和当前语言一致时自动跳过重启。
LOCALE_OPTIONS = [{"v": code, "t": name} for code, name in locale_kit.TRIGGER_LOCALES]
METHOD_PARAM = {"key": "method", "type": "select", "label": "触发方式",
                "value": "real", "options": METHOD_OPTIONS}
LOCALE_PARAM = {"key": "locale", "type": "select", "label": "触发语言",
                "value": locale_kit.DEFAULT_LOCALE, "options": LOCALE_OPTIONS}

SCENARIOS = [
    {
        "id": "birthday",
        "title": "生日策划案卡片",
        "tag": "birthday · card",
        "desc": "建生日事件，把系统时间调到生日前 3 天，息屏 60 秒后亮屏上滑解锁，"
                "验证锁屏上的策划案卡片。",
        "module": scenario_birthday,
        "params": [
            {"key": "offset_days", "type": "number", "label": "生日 = 今天 +",
             "value": 4, "min": 1, "max": 27, "unit": "天"},
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "card_keywords": important_day_keywords("plan"),
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "from": "offset_days", "prefix": "今天 + ", "suffix": " 天"},
        ],
    },
    {
        "id": "greeting",
        "title": "生日祝福卡片",
        "tag": "greeting · card",
        "desc": "把手机时间调到日历里设置的生日当天，息屏静候约 1 分钟，"
                "再亮屏上滑解锁，查看锁屏上的祝福卡片。"
                "日历里没有生日时会自动在「今天+1」新建一个。",
        "module": scenario_greeting,
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "card_keywords": important_day_keywords("greeting"),
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "v": "生日当天"},
        ],
    },
    {
        "id": "anniversary",
        "title": "纪念日策划案卡片",
        "tag": "anniversary · card",
        "desc": "建纪念日事件（重要日里选「纪念日」），把系统时间调到纪念日前 3 天，"
                "息屏 60 秒后第一次解锁，回桌面再等 1 分钟，二次息屏亮屏后"
                "验证锁屏上的纪念日提醒卡片。",
        "module": scenario_birthday,
        # 注意：这里**不写** unsupported_note。纪念日策划案卡在 NOTE 系列上
        # 确实不出卡，但同一份代码换到非 NOTE 机型应该能正常跑，所以改由
        # 前端按 /api/status 的 modelInfo.is_note 实时置灰（见 actions/oobe.ts）。
        # 写死 unsupported_note 会把所有机型都拦掉。
        "params": [
            {"key": "offset_days", "type": "number", "label": "纪念日 = 今天 +",
             "value": 4, "min": 1, "max": 27, "unit": "天"},
            {"key": "hour", "type": "time", "label": "系统时间", "h": 10, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "anniversary", "ev_display": "纪念日",
                  "desktop_wait_sec": 90},
        "card_keywords": important_day_keywords("plan"),
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "from": "offset_days", "prefix": "今天 + ", "suffix": " 天"},
        ],
    },
    {
        "id": "anniversary_greeting",
        "title": "纪念日动效卡片",
        "tag": "anniversary · effect",
        "desc": "把手机时间调到日历里设置的纪念日当天，息屏 60 秒后第一次解锁，"
                "回桌面再等 1 分钟，二次息屏亮屏后查看锁屏上的纪念日动效卡片。"
                "日历里没有纪念日时会自动在「今天+1」新建一个。",
        "module": scenario_greeting,
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 10, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "anniversary", "ev_display": "纪念日",
                   "desktop_wait_sec": 90},
        "card_keywords": important_day_keywords("greeting"),
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "v": "纪念日当天"},
        ],
    },
    {
        "id": "exam",
        "title": "考试考前提醒卡片",
        "tag": "exam · card",
        "desc": "建考试事件（重要日里选「Exam Day」），把系统时间调到考试前 3 天，"
                "息屏 60 秒后亮屏上滑解锁，验证锁屏上的考前提醒卡片。",
        "module": scenario_birthday,
        "params": [
            {"key": "offset_days", "type": "number", "label": "考试 = 今天 +",
             "value": 4, "min": 1, "max": 27, "unit": "天"},
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "exam", "ev_display": "考试"},
        "card_keywords": important_day_keywords("plan"),
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "from": "offset_days", "prefix": "今天 + ", "suffix": " 天"},
        ],
    },
    {
        "id": "exam_greeting",
        "title": "考试祝福卡片",
        "tag": "exam · blessing",
        "desc": "把手机时间调到日历里设置的考试当天，息屏静候约 1 分钟，再亮屏"
                "上滑解锁，查看锁屏上的考试祝福卡片。日历里没有考试事件时会自动"
                "在「今天+1」新建一个。",
        "module": scenario_greeting,
        "icon": "exam",
        "card_keywords": important_day_keywords("greeting"),
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "exam", "ev_display": "考试"},
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "v": "考试当天"},
        ],
    },
    {
        "id": "show_day",
        "title": "追星提醒卡片",
        "tag": "show day · concert",
        "desc": "把手机时间调到日历里设置的观演日（Show Day）当天，息屏静候约 1 分钟"
                "再亮屏上滑解锁，然后补一次「马上息屏、马上亮屏、上滑解锁」，"
                "查看锁屏上的追星提醒卡片。日历里没有该事件时会自动在「今天+1」新建。",
        "module": scenario_greeting,
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 10, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "performance", "ev_display": "观演日",
                   "second_off_sec": 2},
        "card_keywords": important_day_keywords("reminder"),
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "v": "观演日当天"},
        ],
    },
    {
        "id": "important_day",
        "title": "重要日提醒卡片",
        "tag": "important day · reminder",
        "desc": "不用勾选任何类型，直接在日历重要日里输入名字新建事件，把手机时间"
                "调到该事件当天，息屏静候约 1 分钟再亮屏上滑解锁，查看锁屏上的"
                "重要日提醒卡片。",
        "module": scenario_greeting,
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "none", "ev_display": "重要日", "no_lookup": True},
        "card_keywords": important_day_keywords("reminder"),
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "v": "重要日当天"},
        ],
    },
    {
        "id": "wake_alarm_delay",
        "title": "起床闹钟延迟卡片",
        "tag": "wake alarm · delay",
        "desc": "刷机后先在 22:00 保持 10 分钟亮屏使用数据（日常已有数据可设 0）；"
                "设每天 04:01 的闹钟，把系统时间调到周三 23:39，息屏 60 秒到 23:40 "
                "再亮屏，看锁屏/通知栏是否出现「起床闹钟延迟」卡片。",
        "module": scenario_alarm,
        "group": "时间管理",
        "icon": "clock",
        "retryable": False,
        "card_keywords": ("延后", "睡得有点晚", "闹钟", "alarm", "delay", "snooze"),
        "params": [
            {"key": "method", "type": "select", "label": "触发方式",
             "value": "real", "options": METHOD_OPTIONS},
            {"key": "warmup_min", "type": "number", "label": "刷机预热",
             "value": 10, "min": 0, "max": 30, "unit": "分钟"},
            {"key": "wait_sec", "type": "number", "label": "息屏等待",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "specs": [
            {"k": "闹钟", "v": "每天 04:01"},
            {"k": "测试", "v": "周三 23:39 → 23:40"},
            {"k": "预热", "from": "warmup_min", "suffix": "min"},
        ],
    },
    {
        "id": "alarm_early_prompt",
        "title": "提前打开提示卡片",
        "tag": "alarm · early prompt",
        "desc": "先设每天 04:05 的闹钟再关掉（闹钟仍在列表里、处于关闭状态）；"
                "系统时间调到周日 19:09，息屏等 60 秒、再亮屏等 60 秒，"
                "桌面「智慧建议」应出现「要开启明天的闹钟吗？」卡片。",
        "module": scenario_alarm_prompt,
        "group": "时间管理",
        "icon": "clock",
        "retryable": False,
        "card_keywords": ("要开启明天的闹钟吗", "明天是工作日", "开启明天的闹钟",
                          "turn on tomorrow", "tomorrow's alarm", "workday"),
        "params": [
            {"key": "method", "type": "select", "label": "触发方式",
             "value": "real", "options": METHOD_OPTIONS},
            {"key": "wait_sec", "type": "number", "label": "息屏/亮屏各等待",
             "value": 60, "min": 30, "max": 300, "unit": "秒"},
        ],
        "specs": [
            {"k": "闹钟", "v": "每天 04:05（关闭）"},
            {"k": "测试", "v": "周日 19:09 → 19:11"},
        ],
    },
    {
        "id": "alarm_early_close",
        "title": "提前关闭提示卡片",
        "tag": "alarm · early close",
        "desc": "设置每天 04:05 闹钟并保持每日闹钟开启；"
                "系统时间调到周五 19:09，先息屏等待 60 秒，再亮屏等待 60 秒；"
                "之后桌面「智慧建议」应出现「明天是休息日 / 要关闭明天的闹钟吗？」。",
        "module": scenario_alarm_close,
        "group": "时间管理",
        "icon": "clock",
        "retryable": False,
        "card_keywords": ("要关闭明天的闹钟吗", "明天是休息日", "关闭明天的闹钟",
                          "turn off tomorrow", "tomorrow's alarm", "day off"),
        "params": [
            {"key": "method", "type": "select", "label": "触发方式",
             "value": "real", "options": METHOD_OPTIONS},
            {"key": "wait_sec", "type": "number", "label": "息屏/亮屏各等待",
             "value": 60, "min": 30, "max": 300, "unit": "秒"},
        ],
        "specs": [
            {"k": "闹钟", "v": "每天 04:05（开启）"},
            {"k": "测试", "v": "周五 19:09 → 19:11"},
        ],
    },
    {
        "id": "one_tap_taxi",
        "title": "一键打车卡片",
        "tag": "life · taxi",
        "desc": "Yango 一键打车卡片，任何时间都可以触发。发送 AppSuggestEvent"
                "（app_list=com.yandex.yango），系统桌面出现一键打车卡片。",
        "module": scenario_app_suggest,
        "group": "生活服务卡片",
        "icon": "car",
        "retryable": False,
        "card_keywords": ("打车", "Yango", "yango", "ride", "taxi"),
        "params": [
            {"key": "wait_sec", "type": "number", "label": "等待卡片",
             "value": 5, "min": 2, "max": 60, "unit": "秒"},
        ],
        "hidden": {"app_package": "com.yandex.yango"},
        "specs": [
            {"k": "应用", "v": "Yango"},
            {"k": "时机", "v": "任何时间"},
        ],
    },
    {
        "id": "one_tap_food",
        "title": "一键点餐卡片",
        "tag": "life · food",
        "desc": "foodpanda 一键点餐卡片，仅午餐 10:45~13:00、晚餐 17:00~19:00 出卡。"
                "把系统时间设到窗口内，再发 AppSuggestEvent"
                "（app_list=com.global.foodpanda.android）。",
        "module": scenario_app_suggest,
        "group": "生活服务卡片",
        "icon": "food",
        "retryable": False,
        "card_keywords": ("点餐", "foodpanda", "Foodpanda", "外卖", "food", "delivery"),
        "params": [
            {"key": "hour", "type": "time", "label": "点餐时间", "h": 11, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "等待卡片",
             "value": 5, "min": 2, "max": 60, "unit": "秒"},
        ],
        "hidden": {"app_package": "com.global.foodpanda.android"},
        "specs": [
            {"k": "应用", "v": "foodpanda"},
            {"k": "午餐", "v": "10:45~13:00"},
            {"k": "晚餐", "v": "17:00~19:00"},
        ],
    },
    {
        "id": "boomplay_recent_music",
        "title": "最近音乐卡片",
        "tag": "boomplay · music",
        "desc": "Boomplay 随机播放一首海外音乐约 10 秒，mock 发 AppSuggestEvent"
                "（app_list=com.afmobi.boomplayer）；再打开系统蓝牙、"
                "mock 发 HEADSET_PLUG（state=1,type=1）连上耳机，卡片即出现。"
                "重触发前先把时间拨到 2 小时后或隔天（每天上限 2 次、冷却 2 小时）。",
        "module": scenario_boomplay_music,
        "group": "BoomPlay",
        "icon": "music",
        "retryable": False,
        "card_keywords": ("最近播放", "Boomplay", "boomplay", "音乐", "music", "recently played"),
        "params": [
            {"key": "gap", "type": "select", "label": "间隔（频率控制）",
             "value": "2h",
             "options": [
                 {"v": "2h", "t": "2 小时后（过冷却）"},
                 {"v": "next_day", "t": "隔天（重置每日额度）"},
                 {"v": "skip", "t": "不改时间（首次触发）"},
             ]},
            {"key": "wait_sec", "type": "number", "label": "等待卡片",
             "value": 30, "min": 5, "max": 300, "unit": "秒"},
            {"key": "play_sec", "type": "number", "label": "播放时长",
             "value": 10, "min": 3, "max": 120, "unit": "秒"},
        ],
        "hidden": {"app_package": "com.afmobi.boomplayer"},
        "specs": [
            {"k": "应用", "v": "Boomplay"},
            {"k": "mock 事件", "v": "AppSuggestEvent + HEADSET_PLUG"},
            {"k": "每天上限", "v": "2 次"},
            {"k": "触发冷却", "v": "2 小时"},
        ],
    },
    {
        "id": "satellite_call",
        "title": "卫星通话卡片",
        "tag": "tips · satellite",
        "desc": "先确认 ro.tr_telephony.satellite.support=1；清掉原子化模拟器 "
                "com.transsion.atomicbrain，断网再重连；日期推到 3 天后（>72h）、"
                "时间设 09:59 并等到 10:00，桌面/锁屏出现卫星通话玩机技巧卡片。",
        "module": scenario_satellite,
        "group": "玩机技巧卡片",
        "icon": "satellite",
        "retryable": False,
        "card_keywords": ("卫星通话", "卫星", "satellite", "Satellite"),
        "params": [
            {"key": "wait_sec", "type": "number", "label": "10点后等待",
             "value": 75, "min": 65, "max": 300, "unit": "秒"},
        ],
        "specs": [
            {"k": "支持", "v": "satellite.support=1"},
            {"k": "联网", "v": "3 天（>72h）"},
            {"k": "时间", "v": "10:00（09:59 起等）"},
        ],
    },
    {
        "id": "monthly_summary",
        "title": "月度总结卡片",
        "tag": "summary · monthly",
        "desc": "把系统时间调到下个月的第二个周一上午 08:59，息屏等待 60 秒，"
                "上滑解锁后等待 1-2 分钟，桌面出现月度总结体验报告卡片。",
        "module": scenario_summary_report,
        "group": "体验报告卡片",
        "icon": "calendar",
        "retryable": False,
        "card_keywords": ("月度总结", "本月总结", "体验报告", "monthly summary", "monthly report"),
        "params": [
            {"key": "wait_sec", "type": "number", "label": "解锁后等待",
              "value": 90, "min": 30, "max": 180, "unit": "秒"},
        ],
        "hidden": {"report_type": "monthly"},
        "specs": [
            {"k": "日期", "v": "下个月第二个周一"},
            {"k": "时间", "v": "08:59"},
            {"k": "息屏", "v": "60s"},
        ],
    },
    {
        "id": "yearly_summary",
        "title": "年度总结卡片",
        "tag": "summary · yearly",
        "desc": "把系统时间调到当年 12月25日上午 08:59，息屏等待 60 秒，"
                "上滑解锁后等待 1-2 分钟，桌面出现年度总结体验报告卡片。",
        "module": scenario_summary_report,
        "group": "体验报告卡片",
        "icon": "star",
        "retryable": False,
        "card_keywords": ("年度总结", "年度报告", "体验报告", "yearly summary", "annual report"),
        "params": [
            {"key": "wait_sec", "type": "number", "label": "解锁后等待",
              "value": 90, "min": 30, "max": 180, "unit": "秒"},
        ],
        "hidden": {"report_type": "yearly"},
        "specs": [
            {"k": "日期", "v": "12月25日"},
            {"k": "时间", "v": "08:59"},
            {"k": "息屏", "v": "60s"},
        ],
    },
    {
        "id": "cross_region",
        "title": "跨国 / 跨城卡片",
        "tag": "location · cross region",
        "desc": "两种方式自选。①定位切换：定位改到上海亮屏 20 分钟，再切到新德里"
                "亮屏 20 分钟，上滑回桌面出卡；②Mock：直接发 LocationEvent"
                "（country_code=IN，city_code 留空=跨国，1148=德里，1057=新德里）。",
        "module": scenario_cross_region,
        "group": "位置感知卡片",
        "icon": "globe",
        "retryable": False,
        "card_keywords": ("跨国", "跨城", "印度", "India", "in India", "abroad"),
        "params": [
            {"key": "method", "type": "select", "label": "触发方式",
             "value": "mock_country",
             "options": [
                 {"v": "mock_country", "t": "Mock · 跨国卡片（IN）"},
                 {"v": "mock_city_1148", "t": "Mock · 跨城卡片 德里 1148"},
                 {"v": "mock_city_1057", "t": "Mock · 跨城卡片 新德里 1057"},
                 {"v": "location", "t": "定位切换 · 上海 → 新德里（各 20 分钟）"},
             ]},
            {"key": "wait_min", "type": "number", "label": "定位法每地停留",
             "value": 20, "min": 1, "max": 60, "unit": "分钟"},
            {"key": "wait_sec", "type": "number", "label": "Mock 下发后等待",
             "value": 10, "min": 5, "max": 120, "unit": "秒"},
        ],
        "specs": [
            {"k": "事件", "v": "LocationEvent"},
            {"k": "国家", "v": "IN"},
            {"k": "城市码", "v": "空 / 1148 / 1057"},
        ],
    },
    {
        "id": "power_outage_warning",
        "title": "停电预警卡片",
        "tag": "kplc · outage · warning",
        "desc": "需要 root 版设备（要向受 START_TCE_SERVICE 保护的 TceService 注入数据）。"
                "联网，时区改内罗毕、国家改 KE，注入 5 条内罗毕夜间证据把常住区变成 "
                "KE-30/Nairobi；清 atomiccore + atomicbrain，时间调到目标日 11:49，"
                "息屏 60 秒后亮屏解锁，约 25 秒后桌面出现停电预警卡片。",
        "module": scenario_power_outage,
        "group": "停电建议",
        "icon": "bolt",
        "retryable": False,
        "card_keywords": (
            "停电预警", "请提前做好电力储备", "停电", "电力储备",
            "power outage", "outage", "kplc",
            "انقطاع التيار", "انقطاع الكهرباء", "الكهرباء",
        ),
        "params": [
            {"key": "year", "type": "number", "label": "触发年份",
             "value": 2026, "min": 2024, "max": 2100},
            {"key": "month", "type": "number", "label": "触发月份",
             "value": 10, "min": 1, "max": 12},
            {"key": "day", "type": "number", "label": "触发日",
             "value": 15, "min": 1, "max": 31},
            {"key": "hour", "type": "number", "label": "触发小时",
             "value": 11, "min": 8, "max": 23},
            {"key": "minute", "type": "number", "label": "触发分钟",
             "value": 49, "min": 0, "max": 59},
            {"key": "off_sec", "type": "number", "label": "息屏等待",
             "value": 60, "min": 10, "max": 300, "unit": "秒"},
            {"key": "wait_sec", "type": "number", "label": "解锁后等卡片",
             "value": 90, "min": 20, "max": 240, "unit": "秒"},
        ],
        "specs": [
            {"k": "规则", "v": "64379 · KPLC"},
            {"k": "常住区", "v": "KE-30 / Nairobi"},
            {"k": "时间", "v": "11:49 · 息屏 60s"},
        ],
    },
    {
        "id": "power_outage_saving",
        "title": "停电省电提醒卡片",
        "tag": "kplc · outage · saving",
        "desc": "需要 root 版设备。联网，时区改内罗毕、国家改 KE，装 TransAtomicBrain；"
                "时间先调到 09-18 12:29（KPLC 日期框取当天），清 atomiccore + atomicbrain，"
                "在调试页 KPLC 区把电量 mock 成 30% 放电中，点「Mock 电量=30」"
                "再点「查询 KPLC API」确认有公告，最后拨到 12:30、息屏 10 秒解锁出卡。",
        "module": scenario_power_saving,
        "group": "停电建议",
        "icon": "bolt",
        "retryable": False,
        "card_keywords": (
            "省电建议", "开启省电模式", "省电模式", "建议您及时开启省电",
            "power saving", "battery saver", "save power",
            "توفير الطاقة", "توفير البطارية", "توفير",
        ),
        "params": [
            {"key": "year", "type": "number", "label": "触发年份",
             "value": 2026, "min": 2024, "max": 2100},
            {"key": "month", "type": "number", "label": "触发月份",
             "value": 9, "min": 1, "max": 12},
            {"key": "day", "type": "number", "label": "触发日",
             "value": 18, "min": 1, "max": 31},
            {"key": "hour", "type": "number", "label": "触发小时",
             "value": 12, "min": 0, "max": 23},
            {"key": "minute", "type": "number", "label": "触发分钟",
             "value": 30, "min": 0, "max": 59},
            {"key": "battery", "type": "number", "label": "mock 电量",
             "value": 30, "min": 1, "max": 100, "unit": "%"},
            {"key": "off_sec", "type": "number", "label": "息屏等待",
             "value": 10, "min": 10, "max": 300, "unit": "秒"},
            {"key": "wait_sec", "type": "number", "label": "解锁后等卡片",
             "value": 90, "min": 20, "max": 240, "unit": "秒"},
        ],
        "specs": [
            {"k": "规则", "v": "64380 · KPLC"},
            {"k": "区域", "v": "MATASIA · 12:30"},
            {"k": "电量", "v": "30% · 放电中"},
        ],
    },
    {
        "id": "power_outage_restore",
        "title": "停电恢复卡片",
        "tag": "kplc · outage · restoration",
        "desc": "需要 root 版设备。流程同省电卡，但不 mock 电量 —— 反而要先 "
                "「dumpsys battery reset」清掉上一轮残留的电池 mock，否则省电卡会抢走同一个 "
                "conflict_group 把恢复卡挤掉。查 KPLC API 确认当天有停电公告后，"
                "把时间拨到结束前 2 小时的 16:30，息屏 10 秒解锁，桌面出现电力恢复时间卡片。",
        "module": scenario_power_restore,
        "group": "停电建议",
        "icon": "bolt",
        "retryable": False,
        "card_keywords": (
            "电力恢复时间", "恢复时间", "电力已恢复", "供电已恢复", "电力恢复",
            "power restoration", "power restored", "restoration time",
            "استعادة الكهرباء", "عودة الكهرباء", "وقت الاستعادة",
        ),
        "params": [
            {"key": "year", "type": "number", "label": "触发年份",
             "value": 2026, "min": 2024, "max": 2100},
            {"key": "month", "type": "number", "label": "触发月份",
             "value": 9, "min": 1, "max": 12},
            {"key": "day", "type": "number", "label": "触发日",
             "value": 18, "min": 1, "max": 31},
            {"key": "hour", "type": "number", "label": "触发小时",
             "value": 16, "min": 0, "max": 23},
            {"key": "minute", "type": "number", "label": "触发分钟",
             "value": 30, "min": 0, "max": 59},
            {"key": "off_sec", "type": "number", "label": "息屏等待",
             "value": 10, "min": 10, "max": 300, "unit": "秒"},
            {"key": "wait_sec", "type": "number", "label": "解锁后等卡片",
             "value": 90, "min": 20, "max": 240, "unit": "秒"},
        ],
        "specs": [
            {"k": "规则", "v": "64381 · KPLC"},
            {"k": "区域", "v": "MATASIA · 16:30"},
            {"k": "前置", "v": "清掉电池 mock"},
        ],
    },
    {
        "id": "smart_traffic",
        "title": "智能路况卡片",
        "tag": "smart · traffic · weather",
        "desc": "对应 atomicbrain 规则 10058（需 08:00~11:59 的末闹 dismiss 时刻、"
                "当天异常天气进记忆、每天 1 次额度）。①Mock：调试页滑到底部先点「清理智能"
                "路况当日计数」再点「MOCK 智能路况卡」，回桌面十几秒出卡。②真实：刷新天气 "
                "App、时间调到 12 点前、写异常天气进记忆，再设「下一分钟」闹钟，"
                "息屏等响、关掉后解锁出卡。",
        "module": scenario_smart_traffic,
        "group": "路况天气",
        "icon": "road",
        "card_keywords": (
            "智能路况", "大雨可能影响车费", "暴雨可能影响", "路况",
            "smart traffic", "traffic conditions", "heavy rain may affect",
            "حركة المرور", "الطرق", "الأمطار",
        ),
        "retryable": False,
        "params": [
            {"key": "method", "type": "select", "label": "触发方式",
             "value": "mock", "options": METHOD_OPTIONS},
            {"key": "abnormal_type", "type": "select", "label": "异常天气",
             "value": 7, "options": [
                 {"v": 7, "t": "暴雨（7）"},
                 {"v": 10, "t": "大雨（10）"},
                 {"v": 12, "t": "中雨（12）"},
                 {"v": 15, "t": "雷雨（15）"},
             ]},
            {"key": "hour", "type": "number", "label": "真实链路系统时间（时）",
             "value": 11, "min": 0, "max": 11},
            {"key": "minute", "type": "number", "label": "真实链路系统时间（分）",
             "value": 28, "min": 0, "max": 59},
            {"key": "wait_sec", "type": "number", "label": "解锁后等卡片",
             "value": 90, "min": 20, "max": 240, "unit": "秒"},
            {"key": "alarm_wait", "type": "number", "label": "等闹钟响",
             "value": 150, "min": 10, "max": 300, "unit": "秒"},
        ],
        "specs": [
            {"k": "规则", "v": "10058 · 智能路况"},
            {"k": "异常天气", "v": "7 暴雨 / 10 大雨 / 12 中雨 / 15 雷雨"},
            {"k": "额度", "v": "每天 1 次"},
        ],
    },
    {
        "id": "festival_xinnian",
        "title": "节日祝福卡片 · 新年",
        "tag": "festival · New Year",
        "desc": "把系统日期调到新年当天（2026-01-01）、时间调到 9:00~22:00"
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。",
        "module": scenario_festival,
        "card_keywords": ("新年", "元旦", "新年快乐", "元旦快乐", "New Year", "Happy New Year"),
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "常亮等待",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"festival": "xinnian"},
        "specs": [
            {"k": "日期", "v": "2026-01-01"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "festival_duanwu",
        "title": "节日祝福卡片 · 端午节",
        "tag": "festival · Dragon Boat",
        "desc": "把系统日期调到端午节当天（2026-06-19）、时间调到 9:00~22:00"
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。",
        "module": scenario_festival,
        "card_keywords": ("端午", "龙舟", "端午安康", "Dragon Boat"),
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "常亮等待",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"festival": "duanwu"},
        "specs": [
            {"k": "日期", "v": "2026-06-19"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "festival_zhongqiu",
        "title": "节日祝福卡片 · 中秋节",
        "tag": "festival · Mid-Autumn",
        "desc": "把系统日期调到中秋节当天（2026-09-25）、时间调到 9:00~22:00"
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。",
        "module": scenario_festival,
        "card_keywords": ("中秋", "月饼", "团圆", "月圆", "Mid-Autumn", "Moon Festival"),
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "常亮等待",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"festival": "zhongqiu"},
        "specs": [
            {"k": "日期", "v": "2026-09-25"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "festival_guoqing",
        "title": "节日祝福卡片 · 国庆节",
        "tag": "festival · National Day",
        "desc": "把系统日期调到国庆节当天（2026-10-01）、时间调到 9:00~22:00"
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。",
        "module": scenario_festival,
        "card_keywords": ("国庆", "National Day"),
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "常亮等待",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"festival": "guoqing"},
        "specs": [
            {"k": "日期", "v": "2026-10-01"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "festival_dongzhi",
        "title": "节日祝福卡片 · 冬至",
        "tag": "festival · Winter Solstice",
        "desc": "把系统日期调到冬至当天（2026-12-21）、时间调到 9:00~22:00"
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。",
        "module": scenario_festival,
        "card_keywords": ("冬至", "Winter Solstice"),
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "常亮等待",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"festival": "dongzhi"},
        "specs": [
            {"k": "日期", "v": "2026-12-21"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "festival_shengdanye",
        "title": "节日祝福卡片 · 圣诞夜",
        "tag": "festival · Christmas Eve",
        "desc": "把系统日期调到圣诞夜当天（2026-12-24）、时间调到 9:00~22:00"
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。",
        "module": scenario_festival,
        "card_keywords": ("圣诞", "平安夜", "Christmas", "Christmas Eve"),
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "常亮等待",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"festival": "shengdanye"},
        "specs": [
            {"k": "日期", "v": "2026-12-24"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "festival_shengdan",
        "title": "节日祝福卡片 · 圣诞节",
        "tag": "festival · Christmas",
        "desc": "把系统日期调到圣诞节当天（2026-12-25）、时间调到 9:00~22:00"
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。",
        "module": scenario_festival,
        "card_keywords": ("圣诞", "Christmas"),
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "常亮等待",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"festival": "shengdan"},
        "specs": [
            {"k": "日期", "v": "2026-12-25"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "festival_chunjie",
        "title": "节日祝福卡片 · 春节",
        "tag": "festival · Spring Festival",
        "desc": "把系统日期调到春节当天（2027-02-06，明年）、时间调到 9:00~22:00"
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。",
        "module": scenario_festival,
        "card_keywords": ("春节", "春节快乐", "Spring Festival", "Chinese New Year"),
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 9, "m": 30},
            {"key": "wait_sec", "type": "number", "label": "常亮等待",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"festival": "chunjie"},
        "specs": [
            {"k": "日期", "v": "2027-02-06（明年）"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "personal_knowledge",
        "title": "个人知识库授权卡片",
        "tag": "privacy · knowledge · card",
        "desc": "蓝色底图的个人知识库服务授权卡片（TPK serviceId=66071 / "
                "规则 10061）。①DemoHost 调试功能下发云端配置；②设置/系统/"
                "增强服务/个人知识库服务关闭（必须点确认弹层）；③把时间拨到"
                "关闭后第 1/4/6/36/72/108 天的 12:35，息屏亮屏解锁出卡。"
                "卡片是自绘 View（控件树无文字），用蓝色像素占比 + 派发日志判定。",
        "module": scenario_personal_knowledge,
        "group": "隐私合规",
        "icon": "spark",
        "retryable": False,
        "params": [
            {"key": "days", "type": "text", "label": "节点日",
             "value": "1,4,6,36,72,108",
             "placeholder": "1,4,6,36,72,108"},
            {"key": "hour", "type": "time", "label": "系统时间", "h": 12, "m": 35},
            {"key": "off_sec", "type": "number", "label": "息屏",
             "value": 8, "min": 3, "max": 60, "unit": "秒"},
            {"key": "wait_sec", "type": "number", "label": "解锁后等卡片",
             "value": 8, "min": 3, "max": 60, "unit": "秒"},
        ],
        "specs": [
            {"k": "规则", "v": "10061 · 蓝色授权卡"},
            {"k": "节点日", "from": "days"},
            {"k": "额度", "v": "总共 6 次 · 每天 1 次"},
        ],
    },
]
SCENARIOS_BY_ID = {s["id"]: s for s in SCENARIOS}

# 已确认存在的常见位置；找不到就在 SEARCH_ROOTS 下按 scrcpy*/scrcpy.exe 扫一层。
SCRPCY_CANDIDATES = [
    r"D:\APPS\scrcpy-win64-v3.3.3\scrcpy.exe",
    r"D:\tools\scrcpy\scrcpy.exe",
    r"C:\tools\scrcpy\scrcpy.exe",
    r"D:\scrcpy\scrcpy.exe",
    r"C:\scrcpy\scrcpy.exe",
]
SCRPCY_SEARCH_ROOTS = ["D:\\APPS", "D:\\tools", "C:\\tools", "D:\\", "C:\\Program Files"]

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}

_lock = threading.Lock()
_events: list[dict] = []
_state = {"running": False, "result": None, "error": None,
          "scenario": None, "started_at": None, "finished_at": None}
# 上一次跑完的场景：id + 是否算成功（confirmed_ok is False 或抛异常 → 失败）。
# 用它兜底：同一个场景上次没触发成功，这次再点运行就自动当「重试」处理（先清原子服务），
# 不依赖前端是否带 retry=1（老页面缓存 JS 时会漏传）。
_prev_run = {"id": None, "ok": False}
_ctrl = {"paused": False, "stop": False}          # 场景线程运行控制（暂停/结束）
_confirm_evt = threading.Event()                  # 场景线程等待前端确认卡片
_confirm_state = {"pending": False, "ok": None}   # pending=等待中；ok=True已触发/False未触发
_ask_evt = threading.Event()                      # 场景线程等待前端回答前置问题
_ask_state = {"pending": False, "ok": None, "prompt": ""}   # 触发前询问（如 OOBE 国家）
_dev: Device | None = None
_selected: str | None = None   # 用户在多个设备里指定的首选串号；失效后自动回落
_model_cache: dict[str, str] = {}   # serial -> ro.product.model，读过就记住
_country_cache: tuple[float, dict] | None = None   # (时间戳, 国家检测结果)，10 秒缓存
_root_cache: tuple[float, dict] | None = None      # (时间戳, root 检测结果)，10 秒缓存
_model_info_cache: tuple[float, dict] | None = None   # (时间戳, 型号检测结果)，30 秒缓存

# NOTE 系列机型：纪念日策划案卡片（anniversary）在这些机型上实测不出卡
# （轮播翻满一圈也找不到），前端据此把按钮置灰。
# 遇到新机型往这里加一行即可 —— 用白名单而不是正则，避免误伤其他机型。
NOTE_MODELS = (
    "X6766", "X6765", "X6878", "X6886", "X6833", "X6836",
)
_last_adb_chase = 0.0   # 最近一次 adb 自愈尝试的时间戳（节流用）
# 启动时解析出的 adb 绝对路径。打包后 PATH 里没有 adb，只有资源目录里那份；
# 源码直跑时通常解析到系统安装的 adb。解析不到就退回裸 "adb" 交给 PATH。
_ADB: str | None = runtime_paths.bootstrap()
_SCRCPY_UNSET = object()
_scrcpy: object = _SCRCPY_UNSET   # 未解析哨兵；解析后缓存 str | None


def _emit(e: dict) -> None:
    with _lock:
        e = dict(e)
        e["id"] = len(_events) + 1
        e["ts"] = round(time.time(), 3)
        _events.append(e)


def _find_scrcpy() -> str | None:
    """定位 scrcpy.exe。结果缓存，避免每 5 秒的 /api/status 反复扫盘。

    顺序：SCRCPY_PATH 环境变量 -> PATH -> 已知候选 -> 常见目录下扫一层。
    """
    global _scrcpy
    if _scrcpy is not _SCRCPY_UNSET:
        return _scrcpy  # type: ignore[return-value]
    found = os.environ.get("SCRCPY_PATH") or shutil.which("scrcpy")
    if not found:
        # 打包后 scrcpy 若一起塞进了资源目录，优先用那份（不依赖用户装在哪）
        for cand in (runtime_paths.resource_path("scrcpy", "scrcpy.exe"),
                     runtime_paths.resource_path("scrcpy.exe")):
            if cand.is_file():
                found = str(cand)
                break
    if not found:
        for cand in SCRPCY_CANDIDATES:
            if Path(cand).is_file():
                found = cand
                break
    if not found:
        for root in SCRPCY_SEARCH_ROOTS:
            r = Path(root)
            if not r.is_dir():
                continue
            hits = sorted(r.glob("*/scrcpy.exe")) + sorted(r.glob("scrcpy*/scrcpy.exe"))
            if hits:
                found = str(hits[0])
                break
    _scrcpy = found or None
    return _scrcpy  # type: ignore[return-value]


def _device_country(dev) -> dict:
    """读设备 OOBE 国家，判断是否为中国。结果给前端做「一键运行」置灰依据。

    为什么需要它：节日祝福卡片（`festival_*`）依赖 OOBE 国家=中国才会触发，
    以前是场景跑到一半弹一个「是否已在 OOBE 里把国家调整到中国？」让人点。
    现在改成开跑前就自动检测，前端把按钮置灰并写明原因，用户点不了也就
    不会白等两分钟再失败。

    判据（实测 X6766）：
      * `persist.tr_oobe.country`  —— 主判据，XOS 在 OOBE 里写入的就是它；
      * `persist.sys.locale` 的 `-CN` 后缀 —— 兜底（部分机型只改语言）。
    两个都读不到时返回 unknown，前端**不**据此置灰（宁可放行也别误拦）。

    每次 /api/status 都调，但 adb 往返一次约 80ms，且带 10 秒缓存，
    对 3~5 秒一次的状态轮询没有压力。
    """
    global _country_cache
    now = time.time()
    if _country_cache and now - _country_cache[0] < 10:
        return _country_cache[1]
    out = {"country": "", "is_cn": None, "source": ""}
    try:
        raw = (dev.shell("getprop persist.tr_oobe.country") or "").strip()
        if raw:
            out.update(country=raw, is_cn=(raw.upper() == "CN"), source="oobe")
        else:
            loc = (dev.shell("getprop persist.sys.locale") or "").strip()
            out["country"] = loc
            if loc:
                out.update(is_cn=loc.upper().endswith("-CN"), source="locale")
    except Exception:  # noqa: BLE001 —— 读不到就当未知，前端不拦
        pass
    _country_cache = (now, out)
    return out


def _device_model(serial: str) -> str:
    """机型名（如 Infinix X6765）。串号是内部编号，界面上给用户看机型更直观。

    只读一次就缓存：同一台机器的 ro.product.model 不会变，而 /api/status
    每 5 秒被拉一次，每次都去问 adb 纯属浪费往返。
    """
    if serial in _model_cache:
        return _model_cache[serial]
    try:
        name = adbutils.adb.device(serial=serial).prop.get("ro.product.model") or ""
    except Exception:
        name = ""
    if name:
        _model_cache[serial] = name
    return name


def _find_scrcpy_async() -> str | None:
    """`_find_scrcpy()` 的非阻塞版：只在后台线程里扫一次，状态接口立刻返回。

    为什么必须这样：`_find_scrcpy` 会去 `D:\\`、`C:\\Program Files` 这类根目录
    各扫一层 `*/scrcpy.exe`。冷缓存时这一步在机械盘上能卡十几秒，而
    `/api/status` 是前端每 3~5 秒拉一次的接口 —— 于是整个页面「连设备都检测
    不出来」，报错却是超时，根本不像 scrcpy 的问题（实测踩过）。

    扫描结果沿用 `_scrcpy` 缓存：第一次返回 None（前端先禁用按钮），
    后台扫完之后的下一轮轮询就能拿到真路径。
    """
    global _scrcpy
    if _scrcpy is not _SCRCPY_UNSET:
        return _scrcpy  # type: ignore[return-value]

    def _work() -> None:
        try:
            _find_scrcpy()
        except Exception:  # noqa: BLE001 —— 扫描失败就当没找到，不该影响状态接口
            pass

    threading.Thread(target=_work, name="find-scrcpy", daemon=True).start()
    return None


def _device_model_info(dev) -> dict:
    """读设备型号并判断是否 NOTE 系列（纪念日策划案卡在 NOTE 系列上不出卡）。

    为什么不能只看 `ro.product.model`：实测这台机器它返回的是 `XYZ`
    （厂商占位名），真正的型号藏在别的属性里：
        ro.product.device      = Infinix-X6766
        ro.product.name        = X6766-OP
        ro.build.product       = Infinix-X6766
        ro.product.odm.model   = Infinix X6766
    所以把几个字段拼起来一起匹配型号编号。

    NOTE 系列判据：型号串里出现 `X6766` / `X6765` / `X6878` 这类 **X+4 位数字**，
    且属于已知 NOTE 型号集。用「已知集合」而不是「X\\d{4} 正则」是故意的：
    以后遇到新的 NOTE 型号，往 NOTE_MODELS 里加一行就行，不会误伤别的机型。
    """
    global _model_info_cache
    now = time.time()
    if _model_info_cache and now - _model_info_cache[0] < 30:
        return _model_info_cache[1]

    props = {}
    for k in ("ro.product.model", "ro.product.device", "ro.product.name",
              "ro.build.product", "ro.product.odm.model", "ro.product.marketname"):
        try:
            props[k] = (dev.shell(f"getprop {k}") or "").strip()
        except Exception:  # noqa: BLE001
            props[k] = ""
    blob = " ".join(v for v in props.values() if v).upper()

    hit = next((m for m in NOTE_MODELS if m.upper() in blob), "")
    out = {
        "model": props.get("ro.product.model", ""),
        "device": props.get("ro.product.name") or props.get("ro.product.device", ""),
        "props": props,
        "is_note": bool(hit),
        "note_match": hit,
    }
    _model_info_cache = (now, out)
    return out


def _device_root(dev) -> dict:
    """检测设备是否 root（停电建议三张卡要求 root 版设备）。

    为什么需要它：`power_outage_warning` / `power_outage_saving` /
    `power_outage_restore` 要向 `com.transsion.tranradionet/.tce.TceService`
    发 action，该服务受 `signature|privileged` 的 `START_TCE_SERVICE` 保护，
    普通 `shell` 用户会被拒。以前是场景跑到一半才在 `_check_root()` 里抛错，
    白等一两分钟；现在开跑前就检测，前端把按钮置灰并小字提示。

    判据：`adb shell id` 输出里有 `uid=0`。实测 X6766 普通机是
    `uid=2000(shell)`；userdebug/eng 版或执行过 `adb root` 的才是 `uid=0(root)`。

    10 秒缓存，避免每 3~5 秒的状态轮询都跑一次 adb。
    """
    global _root_cache
    now = time.time()
    if _root_cache and now - _root_cache[0] < 10:
        return _root_cache[1]
    out = {"is_root": None, "uid": ""}
    try:
        uid = (dev.shell("id") or "").strip()
        out["uid"] = uid[:80]
        if uid:
            # 只认开头的 uid=0（避免把 gid=0 之类误判成 root）
            head = uid.split(" ", 1)[0]
            out["is_root"] = head.startswith("uid=0")
    except Exception:  # noqa: BLE001 —— 读不到就当未知，前端不拦
        pass
    _root_cache = (now, out)
    return out


def _adb_devs() -> list[tuple[str, str]]:
    """实时设备列表 [(serial, state)]，state ∈ device / offline / unauthorized。

    每次都重新查 adb，不缓存——设备随时可能插拔/换机。
    列表为空且距上次自愈超过 10 秒时，先 start-server，再不行就 kill+start 恢复僵死的 adb。
    """
    global _last_adb_chase

    def _list() -> list[tuple[str, str]]:
        try:
            return [(d.serial, d.get_state())
                    for d in adbutils.adb.device_list()]
        except Exception:
            return []

    devs = _list()
    if devs or time.time() - _last_adb_chase < 10:
        return devs
    _last_adb_chase = time.time()
    # 只做 start-server，绝不再 kill-server：一杀 adb server，所有 transport
    # 立刻消失，正在跑的场景会集体报 `device 'xxx' not found` 直接整场报废
    # （实际踩过：一轮 tick 到一半突然 AdbError: device not found）。
    # 运行中更不许自愈，等这一轮跑完再说。
    with _lock:
        if _state["running"]:
            return devs

    def _start(exe: str, env: dict | None = None) -> int:
        """起一次 daemon，返回进程返回码（0 = 成功）。"""
        try:
            return subprocess.run([exe, "start-server"], capture_output=True,
                                  timeout=15, env=env).returncode
        except Exception:
            return -1

    # 用解析出来的 adb 绝对路径：打包后 PATH 里没有 adb，只有资源目录里那份
    rc = _start(_ADB or "adb")
    if rc != 0:
        # 内置 adb 36.0.0 起 daemon 时必定写 `<TEMP>\adb.log`；某些机器上
        # 这个路径对 detached daemon 不可写（`cannot open adb.log: Permission
        # denied`），于是 daemon 直接退出，所有 adb 命令报 cannot connect to
        # daemon —— 设备明明插着却「检测不到」。
        # 判定不能用 Python 写文件（实测 Python 能写、adb 仍失败），只能用
        # 上面这次 start-server 的真实返回码，失败就换到应用目录旁再试一次。
        alt = runtime_paths.adb_temp_dir()
        if alt is not None:
            env = dict(os.environ)
            env["TMP"] = env["TEMP"] = str(alt)
            if _start(_ADB or "adb", env) == 0:
                # 后续 adbutils / phone_ctl 都继承本进程环境，保持一致
                os.environ["TMP"] = os.environ["TEMP"] = str(alt)
    return _list()


def get_device() -> Device:
    """拿到当前操作的 Device。多设备时优先用 _selected（前端指定的），
    它消失/掉线则自动回落：当前 _dev 还在 → 沿用，否则取第一个可用设备。"""
    global _dev, _selected
    devs = _adb_devs()
    good = [s for s, st in devs if st == "device"]
    if not good:
        if devs:
            serial, st = devs[0]
            raise UiError(f"设备 {serial} 状态异常（{st}）：请在手机上点击「允许 USB 调试」，稍候自动重连。")
        raise UiError("未检测到设备。请确认：USB 已连接、已开启 USB 调试、并在手机弹窗点了「允许」。")
    cur = None
    if _selected and _selected in good:
        cur = _selected
    elif _dev is not None and _dev.serial in good:
        cur = _dev.serial
    else:
        cur = good[0]
    if _dev is None or _dev.serial != cur:
        _dev = Device(serial=cur, log=lambda m: _emit({"t": "log", "no": 0, "msg": m}))
    return _dev


def _scenarios_json() -> list[dict]:
    """给前端的场景清单（去掉不可序列化的 module）。

    分组优先用场景自带的 group 字段；不写则沿用旧规则：
    festival_* 归入「节日祝福卡片」，其余日历类归入「重要日卡片」。
    这样以后新增 30+ 种卡片时，只要在 SCENARIOS 里写 group / retryable / icon
    就能直接出现在左侧目录里，前端不需要改代码。"""
    out = []
    for s in SCENARIOS:
        item = {k: s[k] for k in ("id", "title", "tag", "desc", "params", "specs")}
        # 机型不支持的场景仍然列在目录里（保留完整性），但带一句说明，
        # 前端据此在卡片上打标并禁用「一键运行」，免得白等两分钟。
        if s.get("unsupported_note"):
            item["unsupported_note"] = s["unsupported_note"]
        item["group"] = s.get("group") or (
            "节日祝福卡片" if s["id"].startswith("festival_") else "重要日卡片")
        item["retryable"] = bool(s.get("retryable", not s["id"].startswith("festival_")))
        # 所有场景统一追加「触发语言」——共 25 张卡片，逐个写进 params 会漏，
        # 而且以后新增场景又要记得补。这里集中注入，参数校验那边也自动放行。
        keys = [p["key"] for p in item["params"]]
        if "locale" not in keys:
            item["params"] = list(item["params"]) + [dict(LOCALE_PARAM)]
        for opt in ("icon", "accent"):
            if s.get(opt):
                item[opt] = s[opt]
        out.append(item)
    return out


def _allowed_params(sce: dict, params: dict) -> dict:
    """只接受该场景声明过的参数；time 类型对应 hour + minute 两个键。

    offset_months 是前端「重新触发」专用参数（目标日期平移 N 个月）；
    retry 也是「重新触发」专用开关：卡片未触发后点重试时置 1，
    后端据此在跑卡片之前先 pm clear 两个原子服务；
    sce["hidden"] 是隐藏参数（如纪念日场景的 ev_value），不显示在表单里，
    但允许随请求下发，且缺失时填入默认值。"""
    keys: set[str] = set()
    numeric: dict[str, str] = {}   # key -> "int" / "float"，按声明的类型强制转
    for p in sce["params"]:
        if p["type"] == "time":
            keys.update(("hour", "minute"))
            numeric["hour"] = numeric["minute"] = "int"
        else:
            keys.add(p["key"])
            if p["type"] == "number":
                numeric[p["key"]] = "float" if isinstance(p.get("value"), float) else "int"
    keys.add("offset_months")
    numeric["offset_months"] = "int"
    keys.add("retry")
    keys.add("locale")     # 触发语言：跑之前把系统语言切过去
    keys.add("festival")   # 节日场景可指定单个节日（如 "duanwu"），留空遍历全部
    hidden = sce.get("hidden", {})
    keys.update(hidden)
    out = {k: params[k] for k in keys if k in params}
    for k, v in hidden.items():
        out.setdefault(k, v)
    # 表单/接口拿到的一律是字符串，场景里却直接做 timedelta(days=...)、
    # range()、f"{x:02d}" 之类的数值运算，不在这里转就会炸
    # （实际踩过：TypeError: unsupported type for timedelta days component: str）。
    # 但 hour/minute 可能是 "9:30" 这种合并写法（场景里 _to_hm 负责拆），
    # 这种原样往下传，只有纯数字才在这里转。
    for k, kind in numeric.items():
        if k not in out:
            continue
        v = out[k]
        if isinstance(v, (int, float)):
            continue
        s = str(v).strip()
        if s == "":
            continue
        try:
            num = float(s)
        except ValueError:
            if k in ("hour", "minute"):
                continue          # 交给场景里的 _to_hm 拆
            raise UiError(f"参数 {k}={v!r} 不是合法数字")
        out[k] = int(num) if kind == "int" else num
    return out


def _confirm_fn(r) -> bool:
    """场景线程的确认回调：**自动**识别卡片是否出来了，不再问人。

    以前这里会发一个 confirm 事件、阻塞等前端点「已触发 / 未触发」。
    现在改成：拿当前场景声明的关键词（SCENARIOS[*].card_keywords），
    回桌面首页，在**智慧建议小部件**里一张一张滑轮播去找。
    命中就现场截取小部件里的卡片、存进卡片库并返回 True；翻完一轮没有才
    返回 False。

    重要：锁屏 / 顶部灵动岛的原子卡片（atomic_title）是另一种 UI，
    不能当作智慧建议卡片截图归位。哪怕锁屏文案与目标关键词一致，也必须
    继续回桌面找真正的智慧建议卡片，不能用锁屏图片冒充。

    三个决定行为的细节：

    * **没有声明关键词的场景**（例如弹窗类、锁屏通知类）直接返回 True ——
      和以前「不调用就是通过」的行为一致，不能因为识别不了就判失败。
    * **自动识别失败也不弄死整轮流程**：返回 False 只会让前端显示「未触发」，
      场景本身的步骤都跑完了。真正的报错仍然走异常。
    * **找不到就清缓存重来**：每轮识别前若上一轮没命中，执行三条
      `pm clear`（launcher3 / atomicbrain / atomiccore，见
      `Device.clear_atomic_services()`），和网页点「没出卡重试」完全同一套
      命令；这条规则对**所有**卡片生效。节日卡片（festival_*）因为要联网
      拉节日数据、生成最慢，亮屏后先安静等 7 分钟再决定要不要清；其它
      卡片仍是 90 秒快速失败，不跟着干等。
    * 可被暂停/结束打断：识别期间穿插检查，点了「结束」能立刻停。
    """
    sid = _current_scenario_id()
    sce = SCENARIOS_BY_ID.get(sid) or {}
    keywords = sce.get("card_keywords") or ()
    # 有的卡片标题里带随机名字，要等场景跑到一半才知道 —— 允许写成回调
    if callable(keywords):
        keywords = keywords(r)
    keywords = tuple(k for k in (keywords or ()) if k)
    if not keywords:
        _emit({"t": "log", "no": r._no,
               "msg": "本场景没有登记卡片文案，跳过自动识别（按已触发处理）"})
        return True

    _emit({"t": "log", "no": r._no,
           "msg": "自动识别桌面智慧建议卡片（滑动轮播），无需人工确认…"})
    try:
        dev = get_device()
    except Exception as exc:  # noqa: BLE001
        _emit({"t": "log", "no": r._no, "msg": f"自动识别跳过：取不到设备（{exc}）"})
        return True

    log = lambda m: _emit({"t": "log", "no": r._no, "msg": m})
    hit = None

    # 只接受桌面智慧建议卡片。锁屏快照仅用于诊断日志，绝不能作为归位图片。
    lock_texts = list(getattr(r, "lock_texts", None) or [])
    if lock_texts:
        log(f"锁屏原子卡片文案（不作为智慧建议图片）：{' / '.join(lock_texts)}")

    # ── 识别主循环：找不到就清缓存重来 ──────────────────────────────
    #
    # 卡片没出来不一定是真的出不来，更多时候是：
    #   * 小部件还没渲染完（改完系统时间 / pm clear 之后要几十秒）；
    #   * 智慧建议轮播被旧状态卡住（launcher 的 SharedPreferences 里记着
    #     上一轮被划走的卡）；
    #   * 原子服务的节日/规则数据拉取失败后退避（实测 backoff 最长 1 小时，
    #     但 pm clear 会让它重新初始化）。
    #
    # 按用户定的策略，两条规则分开：
    #   * **三条 pm clear**（launcher3 / atomicbrain / atomiccore，和网页点
    #     「没出卡重试」完全同一套命令）加进**所有**卡片的重试链路；
    #   * **节日卡片（festival_*）亮屏之后先安静等 7 分钟再清缓存** ——
    #     实测节日卡是联网拉节日数据后再渲染的，亮屏那一刻往往还没画出来；
    #     这时候立刻 pm clear 会把正在生成的卡片打断，越清越不出。所以先
    #     只「看一眼」（dump 控件树，不动缓存），7 分钟仍没看到才清数据、
    #     翻下一张（节日卡基本只有一次出卡机会，清早了就白跑一张）。
    #     其它卡片保持 90 秒快速失败，不跟着干等。
    is_festival = sid.startswith("festival_")
    FESTIVAL_QUIET_SEC = 7 * 60        # 亮屏后先安静等这么久，不许清数据
    QUIET_POLL_SEC = 60                # 安静期每隔多久看一眼（只看不清）
    # 节日卡只跑一个安静期：7 分钟没出就判「这张没出」，清完数据交给
    # 采集脚本翻下一张（而不是在同一张卡上继续耗）。
    DEADLINE_SEC = FESTIVAL_QUIET_SEC if is_festival else 90
    ROUND_GAP = 12 if is_festival else 6   # 清数据后给 launcher 重建的时间
    started = time.time()
    round_no = 0
    quiet_until = started + FESTIVAL_QUIET_SEC if is_festival else started

    if is_festival:
        log(f"亮屏后先安静等待 {FESTIVAL_QUIET_SEC // 60} 分钟（期间不清任何数据，"
            f"等节日卡片自己渲染出来；{FESTIVAL_QUIET_SEC // 60} 分钟后仍没出就"
            f"清数据、翻下一张）")

    while hit is None and time.time() - started < DEADLINE_SEC:
        if _ctrl["stop"]:
            raise UiError("用户结束场景")
        if _ctrl["paused"]:
            return True      # 暂停中不折腾设备，交给用户继续时再跑
        round_no += 1
        left = int(DEADLINE_SEC - (time.time() - started))
        in_quiet = time.time() < quiet_until
        phase = "，安静期不清数据）" if in_quiet else "）"
        log(f"第 {round_no} 轮识别（剩余约 {left}s{phase}…")
        hit = card_probe.find_card_anywhere(dev, keywords, log=log)
        if hit:
            break

        # 没找到，分两种情况：
        #   * **安静期**（只有节日卡有）：只歇一会儿再看，**不清任何数据**；
        #   * 安静期之外（所有非节日卡，以及节日卡跑过安静期后理论上到不了的
        #     分支）：沿用老策略 —— 三条 pm clear 后重试，90 秒快速失败。
        if time.time() - started >= DEADLINE_SEC:
            break
        if in_quiet:
            wait = min(QUIET_POLL_SEC, max(1, int(quiet_until - time.time())))
            log(f"安静期：卡片还没出来，{wait}s 后再看一眼（不清数据）")
            for _ in range(wait):
                if _ctrl["stop"]:
                    raise UiError("用户结束场景")
                time.sleep(1)
            continue
        log("本轮没找到，执行三条 pm clear（launcher3 / atomicbrain / atomiccore）后重试")
        try:
            dev.clear_atomic_services()
        except Exception as exc:  # noqa: BLE001 —— 清缓存失败也要继续等
            log(f"清缓存失败（继续重试）：{exc}")
        # 清完 launcher 后桌面要重建，期间别急着 dump
        for _ in range(ROUND_GAP // 3):
            if _ctrl["stop"]:
                raise UiError("用户结束场景")
            time.sleep(3)

    if not hit:
        log(f"等了 {int(time.time() - started)}s（{round_no} 轮）仍未找到智慧建议卡片"
            f"（关键词 {tuple(keywords)}）")
        # 节日卡失败后**只清 launcher3，绝不清 atomicbrain / atomiccore**：
        #
        # 节日卡的配置和素材是 atomicbrain 联网下载的（logcat 里
        # `TAB.CardDataManager: getHolidayCardConfig ... cardsCount=11` 之后
        # `TAB.CardDownloader` 把每张 HOLIDAY_*_bg.png / _effect.mp4 存到
        # files/cards/）。`pm clear atomicbrain` 会把这份刚下好的素材一起删掉，
        # 下一张卡就得重新联网下载 —— 表现就是「越清越不出」，一张接一张失败。
        # launcher3 只存小部件布局/轮播位置，清它是安全的。
        if is_festival:
            log("只清 launcher3 的小部件状态（保留 atomicbrain 已下载的节日卡素材）")
            try:
                dev.shell("pm clear com.transsion.launcher3")
            except Exception as exc:  # noqa: BLE001
                log(f"清 launcher3 失败（不影响翻下一张）：{exc}")
            for _ in range(max(1, ROUND_GAP // 3)):
                if _ctrl["stop"]:
                    raise UiError("用户结束场景")
                time.sleep(3)
        _emit({"t": "card", "no": r._no, "ok": False, "scenario": sid})
        return False
    log(f"第 {round_no} 轮命中，共用时 {int(time.time() - started)}s")

    # 命中：截图 → 抠成透明圆角卡片 → 存进卡片库。
    # 截图失败不影响判定（控件树里的文案已经是足够的证据）。
    #
    # 为什么必须抠：整屏 1208x2644 缩到 36px 什么也看不清，直接裁成方块
    # 又会带着桌面的黑底/壁纸。这里按卡片本体的紧框裁切再画圆角 alpha，
    # 前端拿到的就是可以直接贴的素材（和 public/cards/ 里的设计稿一致）。
    #
    # 图源始终是桌面智慧建议小部件的当前画面。禁止用锁屏截图代替：
    # 锁屏原子卡片与桌面智慧建议卡片不是同一个 UI。
    png = _safe_screenshot(dev)
    if png and hit.box:
        try:
            from tools import make_card_art
            png = make_card_art.cutout_png(png, box=hit.box)
        except Exception as exc:  # noqa: BLE001 —— 抠图失败不能让识别白跑
            log(f"抠图失败，改用原始裁切：{exc}")
            try:
                import io
                from PIL import Image
                from tools import make_card_art as _art
                im = Image.open(io.BytesIO(png))
                x1, y1, x2, y2 = hit.box
                im = im.crop((max(0, x1), max(0, y1),
                              min(im.width, x2), min(im.height, y2)))
                # 裁完仍然要画圆角 alpha：裸裁会把桌面的黑色底和圆角残留
                # 一起带进来，贴到深色 UI 上就是一块方角黑边。
                import numpy as _np
                rgb = _np.asarray(im.convert("RGB")).astype(_np.float32)
                h, w, _ = rgb.shape
                art = _art._render_boxed(
                    rgb, (0, 0, w, h), min(w, h) * 0.14, 0, _art.OUT_SIZE)
                buf = io.BytesIO()
                art.save(buf, format="PNG", optimize=True)
                png = buf.getvalue()
            except Exception:  # noqa: BLE001
                pass
    entry = {}
    if png:
        entry = card_gallery.record(
            sid, title=sce.get("title") or sid, png=png,
            text=hit.text, keyword=hit.keyword, where=hit.where)
    log(f"已识别：{hit.where} / 「{hit.text}」"
        + (f"，截图已存入卡片库（{entry.get('file')}）" if entry else "，截图失败"))
    _emit({"t": "card", "no": r._no, "ok": True, "scenario": sid,
           "text": hit.text, "keyword": hit.keyword, "where": hit.where,
           "has_shot": bool(entry)})
    return True


def _safe_screenshot(dev) -> bytes:
    """截图，失败返回 b""。自动识别不该因为截图掉链子而失败。"""
    try:
        return dev.screenshot_png()
    except Exception:  # noqa: BLE001
        return b""


def _last_lockscreen_shot() -> bytes:
    """取本轮场景已经发过的最后一张「锁屏卡片」截图（base64 → bytes）。

    为什么需要它：重要日卡片（生日策划案 / 纪念日 / 追星 / 重要日提醒）
    是**锁屏卡片**，场景在 `r.shot("锁屏卡片")` 拍完就立刻上滑解锁、
    回桌面，然后才调 `r.confirm()`。等我们自动识别时屏幕早就不在锁屏了，
    现截一张只会得到桌面。

    好在 `Runner.shot()` 把当时的 PNG 以 base64 发进了事件流，从事件流里
    取回来就是「卡片确实出现那一刻」的锁屏画面，比事后补截准得多。
    """
    import base64

    with _lock:
        shots = [e for e in _events
                 if e.get("t") == "shot" and "锁屏" in (e.get("tag") or "")]
    if not shots:
        return b""
    try:
        return base64.b64decode(shots[-1].get("png_b64") or "")
    except Exception:  # noqa: BLE001
        return b""


def _current_scenario_id() -> str:
    """当前正在跑（或刚跑完）的场景 id。"""
    with _lock:
        return str(_state.get("scenario") or "")



def _ask_fn(r, prompt: str) -> bool:
    """场景线程的前置询问回调：发 ask 事件给前端，阻塞等用户回答。

    用于触发前询问 OOBE 国家是否为中国等前置条件；选「否」时调用方据此中止。
    可被暂停/结束打断；120 秒无回应默认按「是」继续（兜底不卡死流程）。"""
    with _lock:
        _ask_state.update(pending=True, ok=None, prompt=prompt)
    _ask_evt.clear()
    _emit({"t": "ask", "no": r._no, "prompt": prompt})
    deadline = time.time() + 120
    while time.time() < deadline:
        if _ctrl["stop"]:
            raise UiError("用户结束场景")
        if _ask_evt.wait(0.3):
            with _lock:
                ok = _ask_state["ok"]
                _ask_state["pending"] = False
            return bool(ok)
    with _lock:
        _ask_state["pending"] = False
    return True


def _run_scenario(scenario_id: str, params: dict) -> None:
    sce = SCENARIOS_BY_ID.get(scenario_id)
    with _lock:
        _ctrl.update(paused=False, stop=False)
        _confirm_state.update(pending=False, ok=None)
        # 自动识别回调要靠它查「这个场景该认哪几个文案」
        _state["scenario"] = scenario_id
    try:
        if sce is None:
            raise ValueError(f"未知场景 {scenario_id!r}")
        kwargs = dict(params)
        # retry 是「重新触发」开关，只在这里消费，不往下传给场景 run()。
        # 表单给过来的是字符串，bool("0") 是 True，必须按字面值判。
        is_retry = str(kwargs.pop("retry", "") or "").strip().lower() in (
            "1", "true", "yes", "on")
        # 触发语言只在这里消费（切系统语言 + 可能重启），不下传给场景 run()。
        # 空值表示「不切语言，用手机当前语言」，这是老调用方的行为，保持不变。
        want_locale = str(kwargs.pop("locale", "") or "").strip()
        kwargs["control"] = _ctrl
        kwargs["confirm_fn"] = _confirm_fn
        kwargs["ask_fn"] = _ask_fn
        dev = get_device()
        if want_locale:
            _label = locale_kit.label_for_locale(want_locale)
            _norm = locale_kit.normalize_locale(want_locale)
            _shown = _label if _label.replace("-", "").lower() == _norm.replace("-", "").lower() \
                else f"{_label}（{_norm}）"
            _emit({"t": "log", "no": 0, "msg": f"触发语言：{_shown}"})
            # 用真实 Runner 承载语言切换的日志/步骤事件，前端进度条能看见这一段；
            # 重启后 adb transport 会换掉，所以下面重新取一次设备句柄。
            locale_switch.ensure_locale(
                dev, want_locale,
                scenario_birthday.Runner(dev, emit=_emit, control=_ctrl),
                timeout=240.0)
            dev = get_device()
        # 上一次同一场景以「未触发 / 报错」收尾 → 这次也算重试，照样先清缓存
        with _lock:
            prev_failed = (_prev_run["id"] == scenario_id and not _prev_run["ok"])
        if is_retry or prev_failed:
            why = "点了重新触发" if is_retry else "上次没触发成功"
            _emit({"t": "log", "no": 0,
                   "msg": f"重新触发（{why}）：先清空 launcher3 / atomicbrain / atomiccore"})
            dev.log = lambda m: _emit({"t": "log", "no": 0, "msg": m})
            dev.clear_atomic_services()
        result = sce["module"].run(dev, emit=_emit, **kwargs)
        # 场景中途是否有过卡片确认（ok=True/False）；没有则为 None
        with _lock:
            result["confirmed_ok"] = _confirm_state["ok"]
            _prev_run.update(id=scenario_id,
                             ok=(result["confirmed_ok"] is not False))
        with _lock:
            _state.update(running=False, result=result, error=None,
                          finished_at=time.time())
        _emit({"t": "done", "result": result})
    except Exception as exc:
        with _lock:
            _prev_run.update(id=scenario_id, ok=False)
            _state.update(running=False, error=str(exc), finished_at=time.time())
        # 只留 str(exc) 会把真正的出错位置弄丢，排障全靠猜；
        # 这里把完整 traceback 打到 stderr（服务日志里能看）。
        traceback.print_exc()
        _emit({"t": "error", "msg": f"{type(exc).__name__}: {exc}"})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """浏览器关标签页时的 ConnectionAborted/BrokenPipe 不是错误，别刷屏。"""
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PhoneRemote/1.0"

    def log_message(self, fmt, *args):
        pass

    # ---------- 工具 ----------
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, "application/json; charset=utf-8", body)

    def _bytes(self, data: bytes, mime: str, code=200, cache=False):
        self._send(code, mime, data, cache)

    def _send(self, code, mime, body, cache=False):
        try:
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            if not cache:
                # 静态页完全不缓存：改前端代码后刷新即生效，
                # 也避免页面还拿着旧的 app.js 跑（老 JS 不会带 retry=1）
                self.send_header("Cache-Control", "no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, BrokenPipeError, ConnectionAbortedError):
            pass  # 客户端提前断开，忽略

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---------- GET ----------
    def do_GET(self):
        # 兜住一切异常：以前 handler 里一旦抛错，连接会被直接掐断，
        # 前端只看到 RemoteDisconnected，真正的原因全丢。现在统一回 JSON 500。
        try:
            self._route_get()
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _route_get(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/api/status":
            return self._status()
        if path == "/api/scenarios":
            return self._json({"scenarios": _scenarios_json()})
        if path == "/api/events":
            return self._events_after(parse_qs(url.query).get("after", ["0"])[0])
        if path == "/api/screenshot":
            return self._screenshot()
        if path == "/api/cards":
            return self._json({"cards": card_gallery.list_all()})
        if path.startswith("/api/cards/"):
            return self._card_image(path[len("/api/cards/"):])
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/") and ".." not in path:
            name = path.lstrip("/")
            if (WEB / name).is_file():
                return self._static(name)
        self._json({"error": "not found"}, 404)

    def _card_image(self, rest: str):
        """按场景 id 取卡片截图（自动识别时存下来的那张）。

        `/api/cards/<scenario_id>.png`，前端直接当 <img src> 用。
        `?ts=` 是前端加的时间戳，用来破缓存；服务端不看它。
        """
        sid = rest[:-4] if rest.endswith(".png") else rest
        if not sid or ".." in sid or "/" in sid or "\\" in sid:
            return self._json({"error": "bad id"}, 400)
        png = card_gallery.read_png(sid)
        if png is None:
            return self._json({"error": "not found"}, 404)
        # 卡片图按 id 覆盖写（同一场景重跑就换一张），所以不能让浏览器缓存：
        # 前端每次带 ?ts=，但 no-store 更保险，也省得记 URL 版本。
        self._bytes(png, "image/png")

    def _static(self, name: str):
        try:
            data = (WEB / name).read_bytes()
        except OSError:
            return self._json({"error": "not found"}, 404)
        self._bytes(data, MIME.get(Path(name).suffix, "application/octet-stream"))

    def _status(self):
        info = {"connected": False, "scrcpy": _find_scrcpy_async()}
        with _lock:
            info["run"] = {k: _state[k] for k in ("running", "result", "error")}
            info["run"]["paused"] = _ctrl["paused"]
            info["run"]["scenario"] = _state["scenario"]
        # 已采集到的卡片索引：前端左侧每张卡片据此显示「实拍图」缩略图。
        # 单独一个 /api/cards 也有，但这条和状态同发，首屏就能拿到，省一次请求。
        info["cards"] = card_gallery.list_all()
        devs = _adb_devs()   # 实时列表，前端每 3~5 秒拉一次，插线/换机自动识别
        info["devices"] = [{"serial": s, "state": st, "model": _device_model(s)}
                           for s, st in devs]
        info["selected"] = _selected
        if not devs:
            info["error"] = ("未检测到设备。请确认 USB 已连接、已在开发者选项开启 USB 调试，"
                             "并在手机弹窗点「允许」——正在自动重连。")
            return self._json(info)
        good = [s for s, st in devs if st == "device"]
        if not good:
            serial, st = devs[0]
            info["serial"] = serial
            info["error"] = (f"设备 {serial} 状态异常（{st}）："
                             f"请在手机上点击「允许 USB 调试」后自动重连。")
            return self._json(info)
        try:
            d = get_device()
            w, h = d.screen_size()
            info.update(connected=True, serial=d.serial, model=d.model(),
                        width=w, height=h, focus=d.focus(),
                        keyguard=d.keyguard_showing())
            # 电量与系统版本：读不到就给 -1 / 空串，前端据此隐藏对应显示。
            # 这两项各自一次 adb 往返，失败不影响其它字段。
            try:
                info["battery"] = d.battery_level()
                info["battery_status"] = d.battery_status()
            except Exception:
                info["battery"] = -1
                info["battery_status"] = ""
            try:
                info["android"] = d.android_version()
            except Exception:
                info["android"] = ""
            # OOBE 国家：前端据此把「一键运行」置灰（节日卡片要求中国）
            info["country"] = _device_country(d)
            # root 检测：停电建议三张卡要求 root 版设备
            info["root"] = _device_root(d)
            # 型号检测：NOTE 系列上纪念日策划案卡不出卡
            info["modelInfo"] = _device_model_info(d)
        except Exception as exc:
            info["error"] = str(exc)
        self._json(info)

    def _events_after(self, after: str):
        """返回 id > after 的事件。

        注意：暂停/结束/确认等控制类事件不经过 _emit（直接 append），
        id 和 seq 不一定连续，所以前端游标必须用 id；另外结果事件里带着
        _events 的引用，serialize 时必须排除 "result"，否则会把整个历史
        回放一遍、前端看到的永远是旧场景的 done。"""
        try:
            after_id = int(after)
        except ValueError:
            after_id = 0
        with _lock:
            out = [e for e in _events if e["id"] > after_id]
            run = {k: _state[k] for k in ("running", "result", "error")}
            run["paused"] = _ctrl["paused"]
        # 回放历史事件时不带完整 result（可能很大且已经通过 done 事件给过）
        slim = []
        for e in out:
            if e.get("t") == "done" and isinstance(e.get("result"), dict):
                e = {k: v for k, v in e.items() if k != "result"}
            slim.append(e)
        self._json({"events": slim, "run": run})

    def _screenshot(self):
        try:
            png = get_device().screenshot_png()
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)
        self._bytes(png, "image/png")

    # ---------- POST ----------
    def do_POST(self):
        try:
            self._route_post()
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _route_post(self):
        path = urlparse(self.path).path
        if path == "/api/scenario/pause":
            return self._ctrl_action("pause")
        if path == "/api/scenario/resume":
            return self._ctrl_action("resume")
        if path == "/api/scenario/stop":
            return self._ctrl_action("stop")
        if path == "/api/scenario/confirm":
            return self._confirm_answer()
        if path == "/api/scenario/ask":
            return self._ask_answer()
        if path.startswith("/api/scenario/"):
            return self._start(path[len("/api/scenario/"):])
        if path == "/api/scrcpy":
            return self._scrcpy()
        if path == "/api/device":
            return self._set_device()
        self._json({"error": "not found"}, 404)

    def _ctrl_action(self, action: str):
        """运行中的场景控制：暂停 / 继续 / 结束。"""
        with _lock:
            if not _state["running"]:
                return self._json({"error": "当前没有运行中的任务"}, 400)
            if action == "pause":
                _ctrl["paused"] = True
            elif action == "resume":
                _ctrl["paused"] = False
            elif action == "stop":
                _ctrl["stop"] = True
        _emit({"t": action, "no": 0})
        self._json({"ok": True, "paused": _ctrl["paused"]})

    def _confirm_answer(self):
        """前端对「卡片是否已触发」的答复。ok: true=已触发 / false=未触发。"""
        body = self._body()
        if "ok" not in body:
            return self._json({"error": "缺少 ok 字段（true=已触发 / false=未触发）"}, 400)
        with _lock:
            if not _confirm_state["pending"]:
                return self._json({"error": "当前没有等待中的卡片确认"}, 400)
            _confirm_state["ok"] = bool(body["ok"])
        _confirm_evt.set()
        self._json({"ok": True})

    def _ask_answer(self):
        """前端对触发前询问（如 OOBE 国家是否为中国）的答复。ok: true=是 / false=否。"""
        body = self._body()
        if "ok" not in body:
            return self._json({"error": "缺少 ok 字段（true=是 / false=否）"}, 400)
        with _lock:
            if not _ask_state["pending"]:
                return self._json({"error": "当前没有等待中的询问"}, 400)
            _ask_state["ok"] = bool(body["ok"])
        _ask_evt.set()
        self._json({"ok": True})

    def _set_device(self):
        """多设备时指定要操作的设备串号。只接受当前在线（state=device）的串号。"""
        global _selected
        body = self._body()
        serial = str(body.get("serial") or "").strip()
        good = [s for s, st in _adb_devs() if st == "device"]
        if serial not in good:
            return self._json(
                {"error": f"设备 {serial!r} 不在可用列表中（当前可用：{good}）"}, 400)
        _selected = serial
        self._json({"selected": _selected, "devices": good})

    def _start(self, scenario_id: str):
        sce = SCENARIOS_BY_ID.get(scenario_id)
        if sce is None:
            return self._json({"error": f"未知场景 {scenario_id!r}"}, 404)
        with _lock:
            if _state["running"]:
                return self._json({"error": "已有任务在运行"}, 409)
            _state.update(running=True, result=None, error=None,
                          started_at=time.time(), finished_at=None)
        try:
            allowed = _allowed_params(sce, self._body())
        except UiError as exc:
            with _lock:
                _state.update(running=False, error=str(exc), finished_at=time.time())
            return self._json({"error": str(exc)}, 400)
        threading.Thread(target=_run_scenario, args=(scenario_id, allowed),
                         daemon=True).start()
        self._json({"started": True, "scenario": scenario_id, "params": allowed})

    def _scrcpy(self):
        exe = _find_scrcpy()
        if not exe:
            return self._json({
                "error": "未找到 scrcpy.exe。请到 GitHub 的 Genymobile/scrcpy releases "
                         "下载 Windows 版解压到 D:\\tools\\scrcpy\\，或用 --scrcpy 指定路径，"
                         "或设置环境变量 SCRCPY_PATH。"}, 404)
        try:
            d = get_device()
            subprocess.Popen([exe, "-s", d.serial],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)
        self._json({"launched": exe})


def main():
    global _scrcpy
    ap = argparse.ArgumentParser(description="手机遥控台")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--scrcpy", default=None, help="手动指定 scrcpy.exe 路径")
    args = ap.parse_args()

    if args.scrcpy:
        if Path(args.scrcpy).is_file():
            _scrcpy = str(Path(args.scrcpy))
        else:
            print(f"警告：--scrcpy 指定的路径不存在，改为自动查找：{args.scrcpy}")

    url = f"http://{args.host}:{args.port}"
    try:
        srv = Server((args.host, args.port), Handler)
    except OSError:
        print(f"端口 {args.port} 已被占用 —— 大概率是另一个遥控台实例正在跑。")
        print(f"直接打开 {url} 即可（重复实例无需再启动）。")
        if not args.no_open:
            webbrowser.open(url)
        return

    print(f"手机遥控台已启动: {url}")
    print(f"scrcpy: {_find_scrcpy() or '未找到（网页上对应按钮会置灰）'}")
    print(f"adb: {_ADB or '未找到（请确认已安装 adb 并在 PATH 里）'}")
    print(f"状态目录: {runtime_paths.state_dir()}")
    print("只监听 127.0.0.1，局域网不可访问。Ctrl+C 退出。")

    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        srv.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 打包成 exe 双击运行时没有父终端，异常一抛窗口就关掉了，
        # 用户只看到黑框一闪。停在这儿让报错留在屏幕上。
        traceback.print_exc()
        if runtime_paths.is_frozen():
            try:
                input("\n出错了，按回车关闭窗口…")
            except Exception:
                pass
        raise

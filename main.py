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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import adbutils
import scenario_alarm
import scenario_alarm_close
import scenario_alarm_prompt
import scenario_app_suggest
import scenario_birthday
import scenario_festival
import scenario_greeting
import scenario_satellite
import scenario_summary_report
from phone_ctl import Device, UiError

HOST = "127.0.0.1"
PORT = 8765
WEB = Path(__file__).parent / "web"

# 场景注册表：前端左侧列表按此渲染，POST /api/scenario/<id> 按此分发。
# params 用声明式描述，前端据此动态生成参数行（time 类型会拆出 hour/minute 两个输入）。
# 新增场景时还可以按需加几个可选字段（都不写也能正常工作）：
#   group      左侧目录分组名；不写则按 id 前缀推断（festival_* → 节日祝福卡片，其余 → 重要日卡片）
#   retryable  卡片未触发时是否提供「下月同日重跑」；不写则节日场景 False、其余 True
#   icon       卡片图标键：cake / heart / exam / ticket / pin / lantern / spark / calendar / gift / star / clock ...
#   accent     保留字段，前端目前按 group 自动配色
SCENARIOS = [
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
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "v": "生日当天"},
        ],
    },
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
            {"key": "name", "type": "text", "label": "姓名",
             "placeholder": "留空则随机 · 仅 ASCII"},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "from": "offset_days", "prefix": "今天 + ", "suffix": " 天"},
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
        "params": [
            {"key": "offset_days", "type": "number", "label": "纪念日 = 今天 +",
             "value": 4, "min": 1, "max": 27, "unit": "天"},
            {"key": "hour", "type": "time", "label": "系统时间", "h": 10, "m": 30},
            {"key": "name", "type": "text", "label": "名称",
             "placeholder": "留空则随机 · 仅 ASCII"},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "anniversary", "ev_display": "纪念日",
                  "desktop_wait_sec": 60},
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
                   "desktop_wait_sec": 60},
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
            {"key": "name", "type": "text", "label": "考试名称",
             "placeholder": "留空则随机 · 仅 ASCII"},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "exam", "ev_display": "考试"},
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
        "desc": "把手机时间调到日历里设置的观演日（Show Day）当天，息屏静候约 1 分钟，"
                "再亮屏上滑解锁，查看锁屏上的追星提醒卡片。日历里没有观演日事件时"
                "会自动在「今天+1」新建一个（重要日里勾选 Show Day）。",
        "module": scenario_greeting,
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 10, "m": 30},
            {"key": "name", "type": "text", "label": "观演名称",
             "placeholder": "留空则随机 · 仅 ASCII"},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "performance", "ev_display": "观演日"},
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
            {"key": "name", "type": "text", "label": "重要日名称",
             "placeholder": "留空则随机 · 仅 ASCII"},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"ev_value": "none", "ev_display": "重要日", "no_lookup": True},
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "v": "重要日当天"},
        ],
    },
    {
        "id": "wake_alarm_delay",
        "title": "起床闹钟延迟卡片",
        "tag": "wake alarm · delay",
        "desc": "刷机后先在 22:00 保持 10 分钟亮屏使用数据；设置并启用每天 04:01 的闹钟；"
                "把系统时间调到周三 23:39，息屏等待 60 秒到 23:40 再亮屏，"
                "检查锁屏/通知栏是否出现「起床闹钟延迟」卡片。"
                "首次刷机预热保持 10 分钟，日常已有使用数据可设为 0。",
        "module": scenario_alarm,
        "group": "时间管理",
        "icon": "clock",
        "retryable": False,
        "params": [
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
        "desc": "先设置每天 04:05 闹钟并关闭（闹钟仍在列表里，但处于关闭状态）；"
                "系统时间调到周日 19:09，先息屏等待 60 秒，再亮屏等待 60 秒；"
                "之后桌面「智慧建议」应出现「明天是工作日 / 要开启明天的闹钟吗？」。",
        "module": scenario_alarm_prompt,
        "group": "时间管理",
        "icon": "clock",
        "retryable": False,
        "params": [
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
        "params": [
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
        "desc": "foodpanda 一键点餐卡片，仅午餐 10:45~13:00、晚餐 17:00~19:00。"
                "设置系统时间在窗口内后发送 AppSuggestEvent"
                "（app_list=com.global.foodpanda.android）。",
        "module": scenario_app_suggest,
        "group": "生活服务卡片",
        "icon": "food",
        "retryable": False,
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
        "id": "satellite_call",
        "title": "卫星通话卡片",
        "tag": "tips · satellite",
        "desc": "先检查 ro.tr_telephony.satellite.support 是否为 1；"
                "清理原子化模拟器 com.transsion.atomicbrain，断开网络再重连；"
                "把日期推到 3 天后（>72h）、时间设 09:59，等到 10:00，"
                "桌面/锁屏出现卫星通话玩机技巧卡片。",
        "module": scenario_satellite,
        "group": "玩机技巧卡片",
        "icon": "satellite",
        "retryable": False,
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
        "id": "festival_xinnian",
        "title": "节日祝福卡片 · 新年",
        "tag": "festival · New Year",
        "desc": "把系统日期调到新年当天（2026-01-01）、时间调到 9:00~22:00"
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。"
                "触发前先询问 OOBE 国家是否已调到中国（否则中止）。",
        "module": scenario_festival,
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
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。"
                "触发前先询问 OOBE 国家是否已调到中国（否则中止）。",
        "module": scenario_festival,
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
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。"
                "触发前先询问 OOBE 国家是否已调到中国（否则中止）。",
        "module": scenario_festival,
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
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。"
                "触发前先询问 OOBE 国家是否已调到中国（否则中止）。",
        "module": scenario_festival,
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
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。"
                "触发前先询问 OOBE 国家是否已调到中国（否则中止）。",
        "module": scenario_festival,
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
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。"
                "圣诞夜不依赖中国 OOBE，触发前不询问国家。",
        "module": scenario_festival,
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
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。"
                "圣诞节不依赖中国 OOBE，触发前不询问国家。",
        "module": scenario_festival,
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
                "之间，回桌面常亮等待 1 分钟，锁屏后上滑解锁，检查锁屏节日祝福卡片。"
                "触发前先询问 OOBE 国家是否已调到中国（否则中止）。",
        "module": scenario_festival,
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
          "started_at": None, "finished_at": None}
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
_last_adb_chase = 0.0   # 最近一次 adb 自愈尝试的时间戳（节流用）
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
    try:
        subprocess.run(["adb", "start-server"], capture_output=True, timeout=15)
        devs = _list()
        if not devs:
            subprocess.run(["adb", "kill-server"], capture_output=True, timeout=15)
            time.sleep(1.5)
            devs = _list()
    except Exception:
        pass
    return devs


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
        item["group"] = s.get("group") or (
            "节日祝福卡片" if s["id"].startswith("festival_") else "重要日卡片")
        item["retryable"] = bool(s.get("retryable", not s["id"].startswith("festival_")))
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
    for p in sce["params"]:
        keys.update(("hour", "minute") if p["type"] == "time" else (p["key"],))
    keys.add("offset_months")
    keys.add("retry")
    keys.add("festival")   # 节日场景可指定单个节日（如 "duanwu"），留空遍历全部
    hidden = sce.get("hidden", {})
    keys.update(hidden)
    out = {k: params[k] for k in keys if k in params}
    for k, v in hidden.items():
        out.setdefault(k, v)
    return out


def _confirm_fn(r) -> bool:
    """场景线程的确认回调：发 confirm 事件给前端，阻塞等用户点「已触发/未触发」。
    可被暂停/结束打断；120 秒无回应默认按「已触发」继续（兜底不卡死流程）。"""
    with _lock:
        _confirm_state.update(pending=True, ok=None)
    _confirm_evt.clear()
    _emit({"t": "confirm", "no": r._no, "msg": "卡片是否已成功触发？"})
    deadline = time.time() + 120
    while time.time() < deadline:
        if _ctrl["stop"]:
            raise UiError("用户结束场景")
        if _confirm_evt.wait(0.3):
            with _lock:
                ok = _confirm_state["ok"]
                _confirm_state["pending"] = False
            return bool(ok)
    with _lock:
        _confirm_state["pending"] = False
    return True


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
    try:
        if sce is None:
            raise ValueError(f"未知场景 {scenario_id!r}")
        kwargs = dict(params)
        # retry 是「重新触发」开关，只在这里消费，不往下传给场景 run()
        is_retry = bool(kwargs.pop("retry", False))
        kwargs["control"] = _ctrl
        kwargs["confirm_fn"] = _confirm_fn
        kwargs["ask_fn"] = _ask_fn
        dev = get_device()
        # 上一次同一场景以「未触发 / 报错」收尾 → 这次也算重试，照样先清缓存
        with _lock:
            prev_failed = (_prev_run["id"] == scenario_id and not _prev_run["ok"])
        if is_retry or prev_failed:
            why = "点了重新触发" if is_retry else "上次没触发成功"
            _emit({"t": "log", "no": 0,
                   "msg": f"重新触发（{why}）：先清空 atomicbrain / atomiccore"})
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
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/") and ".." not in path:
            name = path.lstrip("/")
            if (WEB / name).is_file():
                return self._static(name)
        self._json({"error": "not found"}, 404)

    def _static(self, name: str):
        try:
            data = (WEB / name).read_bytes()
        except OSError:
            return self._json({"error": "not found"}, 404)
        self._bytes(data, MIME.get(Path(name).suffix, "application/octet-stream"))

    def _status(self):
        info = {"connected": False, "scrcpy": _find_scrcpy()}
        with _lock:
            info["run"] = {k: _state[k] for k in ("running", "result", "error")}
            info["run"]["paused"] = _ctrl["paused"]
        devs = _adb_devs()   # 实时列表，前端每 3~5 秒拉一次，插线/换机自动识别
        info["devices"] = [{"serial": s, "state": st} for s, st in devs]
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
        except Exception as exc:
            info["error"] = str(exc)
        self._json(info)

    def _events_after(self, after: str):
        try:
            after_id = int(after)
        except ValueError:
            after_id = 0
        with _lock:
            out = [e for e in _events if e["id"] > after_id]
            run = {k: _state[k] for k in ("running", "result", "error")}
            run["paused"] = _ctrl["paused"]
        self._json({"events": out, "run": run})

    def _screenshot(self):
        try:
            png = get_device().screenshot_png()
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)
        self._bytes(png, "image/png")

    # ---------- POST ----------
    def do_POST(self):
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
        allowed = _allowed_params(sce, self._body())
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
    main()

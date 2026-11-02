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
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "from": "offset_days", "prefix": "今天 + ", "suffix": " 天"},
        ],
    },
    {
        "id": "exam",
        "title": "考试提醒卡片",
        "tag": "exam · card",
        "desc": "建明天开始的 3 天考试日程，把系统时间调到考试前 1 天 22:00，"
                "息屏 60 秒后亮屏上滑解锁，验证锁屏考试提醒卡片。",
        "module": scenario_birthday,
        "params": [
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "v": "考试前一天 22:00"},
        ],
    },
    {
        "id": "ticket",
        "title": "行程提醒卡片",
        "tag": "ticket · card",
        "desc": "建明天出发的高铁行程，把系统时间调到出发当天 06:30，"
                "息屏 60 秒后亮屏上滑解锁，验证锁屏行程提醒卡片。",
        "module": scenario_birthday,
        "params": [
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "specs": [
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
            {"k": "目标", "v": "出发当天 06:30"},
        ],
    },
    {
        "id": "alarm",
        "title": "闹钟提醒卡片",
        "tag": "alarm · card",
        "desc": "建一个 3 分钟后响的闹钟，闹钟响后锁屏上滑，"
                "验证锁屏闹钟提醒卡片。",
        "module": scenario_alarm,
        "params": [],
        "specs": [],
    },
    {
        "id": "alarm_close",
        "title": "闹钟关闭卡片",
        "tag": "alarm · close",
        "desc": "建一个 3 分钟后响的闹钟，闹钟响后锁屏上滑，"
                "验证锁屏闹钟关闭卡片。",
        "module": scenario_alarm_close,
        "params": [],
        "specs": [],
    },
    {
        "id": "alarm_prompt",
        "title": "闹钟提示卡片",
        "tag": "alarm · prompt",
        "desc": "建一个 3 分钟后响的闹钟，闹钟响后锁屏上滑，"
                "验证锁屏闹钟提示卡片。",
        "module": scenario_alarm_prompt,
        "params": [],
        "specs": [],
    },
    {
        "id": "one_tap_taxi",
        "title": "生活服务卡片 · 一键打车",
        "tag": "service · taxi",
        "group": "生活服务卡片",
        "desc": "直接通过 SMB 网络共享路径 adb install 安装 yango.apk，"
                "安装完成后息屏 60 秒，亮屏上滑解锁，检查一键打车智能建议卡片。"
                "任意时间点均可触发。",
        "module": scenario_app_suggest,
        "params": [
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"scenario": "taxi"},
        "specs": [
            {"k": "安装包", "v": "\\\\10.205.4.20\\Odc_Temp_File\\archermind\\zixin.mei\\apk\\yango.apk"},
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "one_tap_food",
        "title": "生活服务卡片 · 一键点外卖",
        "tag": "service · food",
        "group": "生活服务卡片",
        "desc": "直接通过 SMB 网络共享路径 adb install 安装 foodpanda.apk，"
                "安装完成后把系统时间调到 10:45~13:00 或 17:00~19:00 时段内，"
                "息屏 60 秒，亮屏上滑解锁，检查一键点外卖智能建议卡片。",
        "module": scenario_app_suggest,
        "params": [
            {"key": "hour", "type": "time", "label": "系统时间", "h": 11, "m": 0},
            {"key": "wait_sec", "type": "number", "label": "息屏",
             "value": 60, "min": 5, "max": 300, "unit": "秒"},
        ],
        "hidden": {"scenario": "food"},
        "specs": [
            {"k": "安装包", "v": "\\\\10.205.4.20\\archermind\\zixin.mei\\apk\\foodpanda.apk"},
            {"k": "触发时段", "v": "10:45~13:00 / 17:00~19:00"},
            {"k": "息屏", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "satellite_call",
        "title": "玩机技巧卡片 · 卫星通话",
        "tag": "play · satellite",
        "group": "玩机技巧卡片",
        "desc": "先检查 ro.tr_telephony.satellite.support=1，清空 atomicbrain，"
                "打开卫星模式开关，断开网络后保持在线超过 72 小时，"
                "系统时间调到 10:00，亮屏检查卫星通话智能建议卡片。",
        "module": scenario_satellite,
        "params": [],
        "specs": [
            {"k": "前置条件", "v": "ro.tr_telephony.satellite.support=1"},
            {"k": "在线时长", "v": ">72h"},
            {"k": "触发时间", "v": "10:00"},
        ],
    },
    {
        "id": "monthly_summary",
        "title": "体验报告卡片 · 月度总结",
        "tag": "report · monthly",
        "group": "体验报告卡片",
        "desc": "把系统时间调到下个月第二个周一 08:59，息屏 60 秒，"
                "上滑解锁后等待 1~2 分钟，检查月度总结智能建议卡片。",
        "module": scenario_summary_report,
        "params": [
            {"key": "wait_sec", "type": "number", "label": "等待",
             "value": 60, "min": 30, "max": 180, "unit": "秒"},
        ],
        "hidden": {"scenario": "monthly"},
        "specs": [
            {"k": "触发日期", "v": "下个月第二个周一 08:59"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
        ],
    },
    {
        "id": "yearly_summary",
        "title": "体验报告卡片 · 年度总结",
        "tag": "report · yearly",
        "group": "体验报告卡片",
        "desc": "把系统时间调到当年 12 月 25 日 08:59，息屏 60 秒，"
                "上滑解锁后等待 1~2 分钟，检查年度总结智能建议卡片。",
        "module": scenario_summary_report,
        "params": [
            {"key": "wait_sec", "type": "number", "label": "等待",
             "value": 60, "min": 30, "max": 180, "unit": "秒"},
        ],
        "hidden": {"scenario": "yearly"},
        "specs": [
            {"k": "触发日期", "v": "当年 12 月 25 日 08:59"},
            {"k": "等待", "from": "wait_sec", "suffix": "s"},
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
]
SCRCPY_SEARCH_ROOTS = [
    Path("D:\\"),
    Path("C:\\"),
]


def _find_scrcpy() -> str | None:
    for cand in SCRPCY_CANDIDATES:
        if Path(cand).exists():
            return cand
    for root in SCRCPY_SEARCH_ROOTS:
        if not root.exists():
            continue
        for parent in root.iterdir():
            if not parent.is_dir() or not parent.name.lower().startswith("scrcpy"):
                continue
            exe = parent / "scrcpy.exe"
            if exe.exists():
                return str(exe)
    return None


SCRCPY_PATH = _find_scrcpy()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        print(fmt % args)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((WEB / "index.html").read_bytes())
            return
        if url.path == "/app.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write((WEB / "app.js").read_bytes())
            return
        if url.path == "/api/meta":
            self.send_json({
                "port": PORT,
                "scrcpy_found": SCRCPY_PATH is not None,
                "scenarios": SCENARIOS,
            })
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/api/scrcpy":
            if not SCRCPY_PATH:
                self.send_json({"ok": False, "error": "未找到 scrcpy.exe"})
                return
            subprocess.Popen([SCRCPY_PATH])
            self.send_json({"ok": True})
            return
        if url.path.startswith("/api/scenario/"):
            sid = url.path.removeprefix("/api/scenario/")
            scenario = SCENARIOS_BY_ID.get(sid)
            if not scenario:
                self.send_json({"ok": False, "error": "场景不存在"})
                return
            try:
                body = self.rfile.read(int(self.headers["Content-Length"] or 0))
                qs = parse_qs(body.decode("utf-8"))
                kwargs = {}
                for key, values in qs.items():
                    if not values:
                        continue
                    raw = values[-1]
                    # 前端 time 拆成 hour/minute 两个独立参数，拼回 datetime.time
                    if key == "hour":
                        kwargs["hour"] = int(raw)
                        continue
                    if key == "minute":
                        kwargs["minute"] = int(raw)
                        continue
                    # 其余参数按场景声明的类型自动转
                    try:
                        kwargs[key] = int(raw)
                    except ValueError:
                        kwargs[key] = raw
                dev = Device()
                scenario["module"].run(dev, **kwargs)
                self.send_json({"ok": True})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"ok": False, "error": str(e)})
            return
        self.send_response(404)
        self.end_headers()

    def send_json(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    global HOST, PORT, SCRCPY_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--scrcpy", default=SCRCPY_PATH)
    args = parser.parse_args()

    HOST = args.host
    PORT = args.port
    if args.scrcpy and Path(args.scrcpy).exists():
        SCRCPY_PATH = args.scrcpy
    elif args.scrcpy:
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

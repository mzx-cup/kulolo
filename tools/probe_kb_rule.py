"""临时调试：个人知识库卡片（KnowledgeAuthorizationIntent）规则探测。

每次循环：设时间 → 息屏/亮屏/解锁 → 从 logcat 抓 KnowledgeAuthorizationIntent 行。

用法：
    python tools/probe_kb_rule.py 2026-10-08 12:31
    python tools/probe_kb_rule.py 2026-10-08 12:31 --no-lock   # 只设时间不锁屏
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phone_ctl  # noqa: E402
import scenario_birthday as sb  # noqa: E402
from phone_ctl import KEY_POWER, KEY_WAKEUP  # noqa: E402


def knowledge_lines(dev) -> list[str]:
    out = dev.shell_timeout("logcat -d -t 1500", 40)
    return [ln for ln in out.splitlines() if "Knowledge" in ln or "knowledge" in ln]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", help="YYYY-MM-DD")
    ap.add_argument("hhmm", help="HH:MM")
    ap.add_argument("--no-lock", action="store_true")
    args = ap.parse_args()

    day = dt.date.fromisoformat(args.date)
    hh, mm = (int(x) for x in args.hhmm.split(":"))

    dev = phone_ctl.Device()
    r = sb.Runner(dev)

    dev.shell_timeout("logcat -c", 20)
    sb.set_system_datetime(dev, r, day, hh, mm)
    print("设备时间:", dev.shell("date").strip())

    if args.no_lock:
        time.sleep(3)
    else:
        dev.stayon(False)
        time.sleep(0.4)
        dev.key(KEY_POWER)
        time.sleep(4)
        dev.key(KEY_WAKEUP)
        time.sleep(1)
        dev.stayon(True)
        time.sleep(6)
        w, h = dev.screen_size()
        dev.swipe(w // 2, h - 200, w // 2, h // 3, 300)
        time.sleep(3)

    lines = knowledge_lines(dev)
    print(f"\n命中 {len(lines)} 行:")
    for ln in lines[-30:]:
        print(" ", ln[:220])

    Path("_kb_rule.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

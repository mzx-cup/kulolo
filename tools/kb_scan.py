"""临时调试：扫描「个人知识库卡片」在不同 diffDays 下的 match 结果。

对每个 given 天数：设时间(12:35) → 息屏 → 亮屏 → 解锁 → 抓 logcat 判定。
checkTime 锚点 = 2026-10-01 12:31:05（关掉服务开关的时刻，日志实证）。

用法：
    python tools/kb_scan.py 37 67 97
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

ANCHOR = dt.date(2026, 10, 1)
PAT = re.compile(r"diffDays=(-?\d+)\s+match=(\w+)")


def kb(dev) -> tuple[str, str]:
    out = dev.shell_timeout("logcat -d -t 1200", 40)
    lines = [ln for ln in out.splitlines() if "KnowledgeAuthorizationIntent" in ln]
    if not lines:
        return "?", "?"
    m = PAT.search(lines[-1])
    return (m.group(1), m.group(2)) if m else ("?", "?")


def one(dev, r, d: int, hour: int, minute: int) -> None:
    target = ANCHOR + dt.timedelta(days=d)
    dev.shell_timeout("logcat -c", 20)
    sb.set_system_datetime(dev, r, target, hour, minute)
    now = dev.shell("date").strip()

    dev.stayon(False)
    time.sleep(0.4)
    dev.key(KEY_POWER)
    time.sleep(4)
    dev.key(KEY_WAKEUP)
    time.sleep(1)
    dev.stayon(True)
    time.sleep(5)
    w, h = dev.screen_size()
    dev.swipe(w // 2, h - 200, w // 2, h // 3, 300)
    time.sleep(3)

    diff, match = kb(dev)
    print(f"day+{d:<4} {now}  diffDays={diff:<4} match={match}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="+", type=int)
    ap.add_argument("--hour", type=int, default=12)
    ap.add_argument("--minute", type=int, default=35)
    args = ap.parse_args()

    dev = phone_ctl.Device()
    r = sb.Runner(dev)
    for d in args.days:
        one(dev, r, d, args.hour, args.minute)


if __name__ == "__main__":
    main()

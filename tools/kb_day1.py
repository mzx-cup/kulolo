"""临时调试：day+1（diffDays match=true 的那天）深挖，抓 TAB.* 全量日志 + 锁屏/桌面截图。

用法：
    python tools/kb_day1.py --shot _d1
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phone_ctl  # noqa: E402
import scenario_birthday as sb  # noqa: E402
from phone_ctl import KEY_HOME, KEY_POWER, KEY_WAKEUP  # noqa: E402

ANCHOR = dt.date(2026, 10, 1)


def dump_texts(dev, tag: str) -> None:
    print(f"\n----- {tag} focus={dev.focus()}")
    for n in dev.dump():
        t = (n.text or "").strip() or (n.desc or "").strip()
        if t:
            print(f"  {n.cls.split('.')[-1][:18]:18} {n.rid.split('/')[-1][:24]:24} | {t[:60]:60} | {n.bounds}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--hour", type=int, default=12)
    ap.add_argument("--minute", type=int, default=35)
    ap.add_argument("--wait", type=int, default=70)
    ap.add_argument("--shot", default="")
    args = ap.parse_args()

    dev = phone_ctl.Device()
    r = sb.Runner(dev)
    target = ANCHOR + dt.timedelta(days=args.days)
    sb.set_system_datetime(dev, r, target, args.hour, args.minute)
    print("时间:", dev.shell("date").strip())

    dev.stayon(False)
    time.sleep(0.4)
    dev.shell_timeout("logcat -c", 20)
    dev.key(KEY_POWER)
    print(f"息屏 {args.wait}s…")
    time.sleep(args.wait)
    dev.key(KEY_WAKEUP)
    time.sleep(1)
    dev.stayon(True)
    time.sleep(8)

    if args.shot:
        Path(args.shot + "-lock.png").write_bytes(dev.screenshot_png())
    dump_texts(dev, "锁屏")

    w, h = dev.screen_size()
    dev.swipe(w // 2, h - 200, w // 2, h // 3, 300)
    time.sleep(3)
    if args.shot:
        Path(args.shot + "-unlock.png").write_bytes(dev.screenshot_png())
    dump_texts(dev, "解锁后")

    dev.key(KEY_HOME)
    time.sleep(3)
    if args.shot:
        Path(args.shot + "-home.png").write_bytes(dev.screenshot_png())
    dump_texts(dev, "桌面")

    log = dev.shell_timeout("logcat -d -t 20000", 90)
    Path("_d1.log").write_text(log, encoding="utf-8", errors="replace")
    keep = [ln for ln in log.splitlines()
            if ("TAB." in ln or "Knowledge" in ln or "ServiceCard" in ln or "aitips" in ln.lower())]
    Path("_d1_tab.log").write_text("\n".join(keep), encoding="utf-8", errors="replace")
    print(f"\nTAB 相关日志 {len(keep)} 行 -> _d1_tab.log")


if __name__ == "__main__":
    main()

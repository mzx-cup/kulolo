"""临时调试：个人知识库卡片出卡探测。

先关掉「个人知识库服务」，再把时间往前拨，息屏/亮屏/解锁，看锁屏与桌面有没有卡。

用法：
    python tools/probe_kb.py                 # 默认 +2 天 12:35
    python tools/probe_kb.py --days 5        # +5 天
    python tools/probe_kb.py --days 2 --dry  # 只设时间不出卡
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
from phone_ctl import KEY_POWER, KEY_WAKEUP  # noqa: E402


def show(dev, tag: str) -> None:
    print(f"\n===== {tag} =====  focus={dev.focus()}")
    for n in dev.dump():
        t = (n.text or "").strip()
        d = (n.desc or "").strip()
        if not (t or d):
            continue
        cls = n.cls.split(".")[-1]
        if cls in ("View", "ViewGroup", "FrameLayout"):
            continue
        print(f"{cls[:16]:16} {n.rid.split('/')[-1][:26]:26} | {t[:44]:44} | {d[:18]:18} | {n.bounds}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--hour", type=int, default=12)
    ap.add_argument("--minute", type=int, default=35)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--shot", default="")
    ap.add_argument("--wait", type=int, default=60, help="息屏保持秒数")
    ap.add_argument("--log", default="", help="把 logcat 存到这个文件")
    args = ap.parse_args()

    dev = phone_ctl.Device()
    r = sb.Runner(dev)
    today = sb.device_date(dev)
    target = today + dt.timedelta(days=args.days)
    print(f"设备当前日期 {today} -> 目标 {target} {args.hour:02d}:{args.minute:02d}")

    sb.set_system_datetime(dev, r, target, args.hour, args.minute)
    print("设置后设备时间:", dev.shell("date").strip())
    if args.dry:
        return

    dev.stayon(False)
    time.sleep(0.5)
    dev.key(KEY_POWER)
    print(f"已息屏，等 {args.wait} 秒…")
    time.sleep(args.wait)
    if args.log:
        dev.shell_timeout("logcat -c", 20)
    dev.key(KEY_WAKEUP)
    time.sleep(1)
    dev.stayon(True)          # 亮屏立刻常亮，否则 dump/截图期间又睡回去（会截到全黑）
    print("亮屏后屏幕状态:", dev.screen_on())
    time.sleep(7)
    if args.shot:
        Path(args.shot + "-lock.png").write_bytes(dev.screenshot_png())
    show(dev, "亮屏")

    w, h = dev.screen_size()
    dev.swipe(w // 2, h - 200, w // 2, h // 3, 300)
    time.sleep(3)
    if args.shot:
        Path(args.shot + "-unlock.png").write_bytes(dev.screenshot_png())
    show(dev, "解锁后")
    dev.key(phone_ctl.KEY_HOME)
    time.sleep(2)
    show(dev, "回桌面")
    if args.shot:
        Path(args.shot + "-home.png").write_bytes(dev.screenshot_png())
    if args.log:
        out = dev.shell_timeout("logcat -d -t 4000", 60)
        Path(args.log).write_text(out, encoding="utf-8", errors="replace")
        print(f"logcat 已存 {args.log}（{len(out)} 字节）")


if __name__ == "__main__":
    main()

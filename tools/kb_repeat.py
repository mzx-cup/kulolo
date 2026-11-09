"""临时调试：同一 diffDays 重复多次，看 match 是否稳定（区分「按天数」还是「随机/被其他卡挤掉」）。

用法：
    python tools/kb_repeat.py 2 --n 3
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
WIDGET = (611, 213, 1153, 801)


def widget_texts(dev) -> list[str]:
    out = []
    for n in dev.dump():
        if not n.bounds:
            continue
        x1, y1, x2, y2 = n.bounds
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        if WIDGET[0] <= cx <= WIDGET[2] and WIDGET[1] <= cy <= WIDGET[3]:
            t = (n.text or "").strip() or (n.desc or "").strip()
            if t:
                out.append(t)
    return out


def one(dev, r, d: int, hour: int, minute: int, idx: int) -> None:
    target = ANCHOR + dt.timedelta(days=d)
    dev.shell_timeout("logcat -c", 20)
    sb.set_system_datetime(dev, r, target, hour, minute)

    dev.stayon(False)
    time.sleep(0.4)
    dev.key(KEY_POWER)
    time.sleep(12)
    dev.key(KEY_WAKEUP)
    time.sleep(1)
    dev.stayon(True)
    time.sleep(6)

    w, h = dev.screen_size()
    dev.swipe(w // 2, h - 200, w // 2, h // 3, 300)
    time.sleep(2)
    dev.key(KEY_HOME)
    time.sleep(3)

    lines = [ln for ln in dev.shell_timeout("logcat -d -t 1500", 40).splitlines()
             if "KnowledgeAuthorizationIntent" in ln]
    tag = lines[-1].split("KnowledgeAuthorizationIntent:", 1)[-1].strip() if lines else "(无日志)"
    texts = widget_texts(dev)
    print(f"[{idx}] day+{d} {target}  {tag}")
    print(f"     小部件文案: {texts}")
    if any("知识库" in t for t in texts):
        p = Path(f"_kbhit_{d}_{idx}.png")
        p.write_bytes(dev.screenshot_png())
        print(f"     >>> 命中！截图 {p}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("days", type=int)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--hour", type=int, default=12)
    ap.add_argument("--minute", type=int, default=35)
    args = ap.parse_args()

    dev = phone_ctl.Device()
    r = sb.Runner(dev)
    for i in range(args.n):
        one(dev, r, args.days, args.hour, args.minute, i + 1)


if __name__ == "__main__":
    main()

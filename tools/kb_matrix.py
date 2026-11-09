"""临时调试：个人知识库卡片触发规则矩阵扫描。

对每个候选时间点：设时间 → 息屏/亮屏/解锁 → 抓 logcat 里的
KnowledgeAuthorizationIntent 行，打印 diffDays / match，并顺带看桌面小部件文案。

用法：
    python tools/kb_matrix.py                 # 默认扫描 day 2/5/7
    python tools/kb_matrix.py 2 5 7 37        # 自定义天数
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

ANCHOR = dt.datetime(2026, 10, 1, 12, 31, 5)   # 关掉开关的时刻（= logcat checkTime）
PAT = re.compile(r"diffDays=(\d+)\s+match=(\w+)")


def kb_lines(dev) -> list[str]:
    out = dev.shell_timeout("logcat -d -t 2500", 40)
    return [ln for ln in out.splitlines() if "KnowledgeAuthorizationIntent" in ln]


def widget_text(dev) -> str:
    dev.key(phone_ctl.KEY_HOME)
    time.sleep(1.2)
    texts = []
    for n in dev.dump():
        if not n.bounds:
            continue
        l, t, r, b = n.bounds
        if 600 <= l <= 1160 and 200 <= t <= 800:      # 智慧建议小部件区域
            s = (n.text or n.desc or "").strip()
            if s:
                texts.append(s)
    return " / ".join(dict.fromkeys(texts))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="*", type=int, default=[2, 5, 7])
    ap.add_argument("--hour", type=int, default=12)
    ap.add_argument("--minute", type=int, default=35)
    args = ap.parse_args()

    dev = phone_ctl.Device()
    r = sb.Runner(dev)
    print(f"锚点 checkTime = {ANCHOR}\n")

    for d in args.days:
        target = ANCHOR.date() + dt.timedelta(days=d)
        dev.shell_timeout("logcat -c", 20)
        sb.set_system_datetime(dev, r, target, args.hour, args.minute)
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

        lines = kb_lines(dev)
        m = [PAT.search(ln) for ln in lines]
        m = [x for x in m if x]
        diff = m[-1].group(1) if m else "?"
        match = m[-1].group(2) if m else "?"
        print(f"day+{d:<3} {now}  diffDays={diff:<3} match={match:<6} widget=[{widget_text(dev)}]")
        Path(f"_kb_d{d}.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

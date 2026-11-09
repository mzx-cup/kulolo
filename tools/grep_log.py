"""临时调试：抓 logcat，按多个关键词分组打印，方便找卡片触发规则。

用法：
    python tools/grep_log.py                 # 默认关键词
    python tools/grep_log.py --lines 5000    # 抓更多行
    python tools/grep_log.py --kw foo bar    # 自定义关键词（小写匹配）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phone_ctl  # noqa: E402

DEFAULT_KW = (
    "knowledge", "personalknow", "privacy", "atomicbrain", "aitips",
    "no_card", "action_status", "intentMatch", "rule_", "wisdom",
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=4000)
    ap.add_argument("--kw", nargs="*", default=list(DEFAULT_KW))
    ap.add_argument("--tail", type=int, default=120)
    args = ap.parse_args()

    dev = phone_ctl.Device()
    out = dev.shell_timeout(f"logcat -d -t {args.lines}", 60)
    kws = [k.lower() for k in args.kw]
    hits = [ln for ln in out.splitlines() if any(k in ln.lower() for k in kws)]
    print(f"抓取 {len(out.splitlines())} 行，命中 {len(hits)} 行\n")
    for ln in hits[-args.tail:]:
        print(ln[:240])


if __name__ == "__main__":
    main()

"""临时调试：抓取某一时刻 atomicbrain 的完整能力匹配日志，找知识库卡片规则细节。

用法：python tools/kb_trace.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phone_ctl  # noqa: E402
from phone_ctl import KEY_POWER, KEY_WAKEUP  # noqa: E402

KEYS = ("knowledge", "authoriz", "privacy", "personal", "TAB.", "aitips")


def main() -> None:
    dev = phone_ctl.Device()
    print("设备时间:", dev.shell("date").strip())
    dev.shell_timeout("logcat -c", 20)

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
    time.sleep(4)

    out = dev.shell_timeout("logcat -d -t 4000", 60)
    lines = out.splitlines()
    hits = [ln for ln in lines if any(k in ln for k in KEYS)]
    print(f"总 {len(lines)} 行，命中 {len(hits)}")
    Path("_kb_trace.txt").write_text("\n".join(lines), encoding="utf-8")
    print("全文已写 _kb_trace.txt")
    for ln in hits[:80]:
        print(ln[:230])


if __name__ == "__main__":
    main()

"""临时调试：抓 logcat 里和「个人知识库」卡片相关的行。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phone_ctl  # noqa: E402

PATTERNS = ("knowledge", "PersonalKnow", "privacy", "Privacy", "kb_", "know_")


def main() -> None:
    dev = phone_ctl.Device()
    if "--wake" in sys.argv:
        dev.key(phone_ctl.KEY_WAKEUP)
    out = dev.shell_timeout("logcat -d -t 3000", 40) if hasattr(dev, "shell_timeout") else dev.shell("logcat -d -t 3000")
    hits = []
    for line in out.splitlines():
        low = line.lower()
        if any(p.lower() in low for p in PATTERNS):
            hits.append(line)
    print("\n".join(hits[-80:]) if hits else "(no hits)")


if __name__ == "__main__":
    main()

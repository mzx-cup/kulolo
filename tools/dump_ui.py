"""临时调试工具：把当前界面的控件树打出来（带 rid / 文案 / 区域 / 开关状态）。

用法：
    python tools/dump_ui.py            # 只打印有文案的节点
    python tools/dump_ui.py --all      # 连没有文案的节点一起打印（找 switch 用）
    python tools/dump_ui.py --shot x.png
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phone_ctl  # noqa: E402


def main() -> None:
    dev = phone_ctl.Device()
    print("focus:", dev.focus())
    print("screen:", dev.screen_size(), "on:", dev.screen_on(), "locked:", dev.locked())
    nodes = dev.dump()
    print("nodes:", len(nodes))
    show_all = "--all" in sys.argv
    for n in nodes:
        t = (n.text or "").strip()
        d = (n.desc or "").strip()
        cls = n.cls.split(".")[-1]
        interesting = show_all or t or d
        if not interesting:
            continue
        if not show_all and cls in ("View", "ViewGroup", "FrameLayout"):
            continue
        rid = n.rid.split("/")[-1] if n.rid else ""
        flags = []
        if n.clickable:
            flags.append("click")
        if n.attrs.get("checkable") == "true":
            flags.append("checkable")
        if n.attrs.get("checked") == "true":
            flags.append("CHECKED")
        if n.attrs.get("enabled") == "false":
            flags.append("disabled")
        print(f"{cls[:18]:18} {rid[:34]:34} | {t[:34]:34} | {d[:26]:26} | {n.bounds} | {' '.join(flags)}")
    if "--shot" in sys.argv:
        out = sys.argv[sys.argv.index("--shot") + 1]
        Path(out).write_bytes(dev.screenshot_png())
        print("shot ->", out)


if __name__ == "__main__":
    main()

"""临时调试：关掉个人知识库服务开关，看会不会弹二次确认。

用法：python tools/probe_pk.py [--restore]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phone_ctl  # noqa: E402

PK_CMP = ("com.transsion.atomiccore/"
          "com.transsion.atomiccore.settings.impl.activity.PersonalKnowledgeActivity")


def dump(dev, tag):
    print(f"\n===== {tag} =====")
    print("focus:", dev.focus())
    for n in dev.dump():
        t = (n.text or "").strip()
        d = (n.desc or "").strip()
        if not (t or d or n.attrs.get("checkable") == "true"):
            continue
        cls = n.cls.split(".")[-1]
        flags = []
        if n.clickable:
            flags.append("click")
        if n.attrs.get("checkable") == "true":
            flags.append("checkable")
        if n.attrs.get("checked") == "true":
            flags.append("CHECKED")
        print(f"{cls[:14]:14} {n.rid.split('/')[-1][:30]:30} | {t[:30]:30} | {n.bounds} | {' '.join(flags)}")


def main() -> None:
    dev = phone_ctl.Device()
    dev.log = lambda m: print("  [dev]", m)
    dev.shell(f"am start -n {PK_CMP}")
    time.sleep(1.5)
    dump(dev, "打开个人知识库服务页")

    main_switch = dev.find_opt(rid="toggle_switch")
    if main_switch is None:
        raise SystemExit("找不到 toggle_switch")
    print("主开关:", main_switch)
    x, y = main_switch.center
    dev.tap(x, y)
    time.sleep(1.2)
    dump(dev, "点击主开关后")
    Path("_pk_after.png").write_bytes(dev.screenshot_png())


if __name__ == "__main__":
    main()

"""临时调试：把与 Knowledge 有关的日志全部抓下来（不限关键词大小写），并附带开关状态。

用法：python tools/kb_deep.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phone_ctl  # noqa: E402

PK_CMP = ("com.transsion.atomiccore/"
          "com.transsion.atomiccore.settings.impl.activity.PersonalKnowledgeActivity")


def main() -> None:
    dev = phone_ctl.Device()
    print("设备时间:", dev.shell("date").strip())

    dev.shell(f"am start -n {PK_CMP}")
    import time
    time.sleep(1.5)
    nodes = dev.dump()
    sw = [n for n in nodes if n.attrs.get("checkable") == "true"]
    for n in sw:
        print("switch:", n.bounds, "checked=", n.attrs.get("checked"))
    main_sw = [n for n in sw if n.bounds[1] < 700]
    if main_sw:
        print("主开关 checked =", main_sw[0].attrs.get("checked"))
    dev.key(phone_ctl.KEY_HOME)

    out = dev.shell_timeout("logcat -d -t 8000", 60)
    hits = [ln for ln in out.splitlines() if "nowledge" in ln]
    print(f"\n===== Knowledge 相关 {len(hits)} 行 =====")
    for ln in hits[-60:]:
        print(ln[:260])
    Path("_kb_deep.txt").write_text("\n".join(hits), encoding="utf-8")


if __name__ == "__main__":
    main()

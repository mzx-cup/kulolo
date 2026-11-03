"""体验报告卡片：月度总结 / 年度总结。

触发方式：
  月度总结：系统时间调到下个月的下个周一 08:59，息屏 60 秒，上滑解锁，等待 1-2 分钟
  年度总结：系统时间调到当年 12月25日 08:59，息屏 60 秒，上滑解锁，等待 1-2 分钟
"""
from __future__ import annotations

import time
from datetime import date, timedelta

from phone_ctl import Device, KEY_POWER, UiError

from scenario_birthday import (
    Runner,
    _cli_emit,
    _prepare,
    device_date,
    ensure_home_before_confirm,
    set_system_datetime,
)


def _next_month_second_monday(d: date) -> date:
    """计算「下个月的下个周一」：
    例：2026-11-04 → 下个月是 12月，12月第一个周一是 12月1日，下个周一就是 12月8日？
    不对，用户例子 11月4号 → 12月14号，说明是「下个月的第二个周一」：
    下个月第一天往后数，跳过第一个周一，取第二个周一。
    """
    # 下个月第一天
    if d.month == 12:
        first_next = date(d.year + 1, 1, 1)
    else:
        first_next = date(d.year, d.month + 1, 1)
    # first_next.weekday(): 0=周一, 6=周日
    # 下个月第一个周一
    first_monday = first_next + timedelta(days=(7 - first_next.weekday()) % 7)
    # 第二个周一（下个周一）
    second_monday = first_monday + timedelta(days=7)
    # 用户例子 11月4日 → 12月：12月1日是周二 → first_monday=12月7日 → second_monday=12月14日，完全匹配
    return second_monday


def run(dev: Device | None = None, emit=None, *,
        report_type: str, wait_sec: int = 90,
        control: dict | None = None, confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    if report_type not in ("monthly", "yearly"):
        raise UiError(f"report_type 必须是 'monthly' 或 'yearly'，收到 {report_type!r}")
    if not (30 <= wait_sec <= 180):
        raise UiError("wait_sec 必须在 30~180 秒之间")

    result = {"report_type": report_type, "wait_sec": wait_sec}
    _prepare(dev, r)

    now = device_date(dev)
    r.log(f"当前设备时间：{now}")

    if report_type == "monthly":
        target_date = _next_month_second_monday(now)
        r.step(f"月度总结：设置时间到下个月的第二个周一 {target_date} 08:59")
    else:
        target_date = date(now.year, 12, 25)
        r.step(f"年度总结：设置时间到当年 12月25日 {target_date} 08:59")

    set_system_datetime(dev, r, target_date, 8, 59)
    r.ok(f"时间已设为 {target_date} 08:59")
    result["target_date"] = str(target_date)

    r.step("息屏等待 60 秒")
    dev.key(KEY_POWER)
    time.sleep(60)

    r.step("上滑解锁")
    w, h = dev.screen_size()
    dev.swipe(w // 2, h - 200, w // 2, h // 3, 300)
    time.sleep(1)

    r.step(f"等待卡片出现 {wait_sec} 秒…")
    time.sleep(wait_sec)

    ensure_home_before_confirm(dev, r)
    r.shot("桌面")
    ok = r.confirm()
    dev.shell("cmd statusbar expand-notifications")
    time.sleep(0.5)
    r.shot("通知栏")
    ok = ok or r.confirm()
    dev.shell("cmd statusbar collapse")
    time.sleep(0.4)
    if ok:
        ensure_home_before_confirm(dev, r)

    if not ok:
        raise UiError("桌面和通知栏都没有确认到体验报告卡片")

    r.ok("已确认体验报告卡片")
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (
        f"完成。已触发{'月度' if report_type == 'monthly' else '年度'}总结卡片，"
        f"桌面应出现体验报告类卡片。")
    return result


if __name__ == "__main__":
    import sys

    typ = sys.argv[1] if len(sys.argv) > 1 else "monthly"
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    try:
        out = run(emit=_cli_emit, report_type=typ, wait_sec=wait)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

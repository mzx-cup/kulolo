"""提前关闭提示卡片（时间管理）。

按测试说明：
  1. 设置每天 04:05 闹钟，并保持每日闹钟开启。
  2. 系统时间调到周五 19:09。
  3. 回桌面保持亮屏等待 1 分钟；19:10 桌面「智慧建议」应出现：
     「明天是休息日 / 要关闭明天的闹钟吗？」
  4. 截图 → 前端确认。
"""
from __future__ import annotations

import datetime as _dt
import time

from phone_ctl import KEY_HOME, KEY_WAKEUP, Device, UiError

from scenario_alarm import _set_daily_alarm
from scenario_birthday import (
    Runner,
    _cli_emit,
    _unlock_with_retries,
    _wait_screen_on,
    device_date,
    set_system_datetime,
)

ALARM_HOUR = 4
ALARM_MINUTE = 5
TEST_HOUR = 19
TEST_MINUTE = 9
_FRIDAY = 4  # date.weekday(): Monday=0


def _next_friday(today: _dt.date) -> _dt.date:
    """今天就是周五就用今天，否则取最近的周五。"""
    delta = (_FRIDAY - today.weekday()) % 7
    return today + _dt.timedelta(days=delta)


def _wait_card(dev: Device, r: Runner, day: _dt.date, wait_sec: int) -> None:
    r.step(f"系统时间调到周五 {TEST_HOUR:02d}:{TEST_MINUTE:02d}，"
           f"息屏 {wait_sec} 秒再亮屏 {wait_sec} 秒")
    set_system_datetime(dev, r, day, TEST_HOUR, TEST_MINUTE)

    # 第一步：灭屏等待
    dev.key(KEY_HOME)
    time.sleep(0.5)
    dev.stayon(False)
    time.sleep(0.3)
    dev.key(223)
    if not _wait_screen_on(dev, False, timeout=1.2):
        r.log("警告：灭屏后屏幕仍为亮起状态")
    r.log(f"屏幕已灭，等待 {wait_sec} 秒")
    for elapsed in range(wait_sec):
        r.check()
        remain = wait_sec - elapsed
        if elapsed % 5 == 0 or remain == 1:
            r.tick(remain)
        time.sleep(1)

    # 第二步：亮屏并解锁，保持亮屏等待
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    time.sleep(0.8)
    dev.stayon(True)
    _unlock_with_retries(dev, r, 3)
    dev.key(KEY_HOME)
    time.sleep(0.5)
    r.log(f"已亮屏解锁，保持亮屏等待 {wait_sec} 秒")
    for elapsed in range(wait_sec):
        r.check()
        remain = wait_sec - elapsed
        if elapsed % 5 == 0 or remain == 1:
            r.tick(remain)
        time.sleep(1)

    time.sleep(0.3)
    now = dev.shell("date '+%H:%M:%S'").strip()
    r.shot("桌面 19:11 提前关闭提示")

    r.step("确认提前关闭提示卡片是否出现")
    if not r.confirm():
        r.log("桌面未确认，展开通知栏再检查一次")
        dev.shell("cmd statusbar expand-notifications")
        time.sleep(1.0)
        r.shot("通知栏")
        ok = r.confirm()
        dev.shell("cmd statusbar collapse")
        time.sleep(0.4)
        if not ok:
            raise UiError("桌面和通知栏都没有确认到「提前关闭提示」卡片")
    r.ok(f"设备时间 {now}，19:10 桌面已检查")


def run(dev: Device | None = None, emit=None, *, wait_sec: int = 60,
        control: dict | None = None, confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log
    if not (5 <= wait_sec <= 300):
        raise UiError("wait_sec 必须在 5~300 秒之间")

    today = device_date(dev)
    day = _next_friday(today)
    result = {
        "device_today": today.isoformat(),
        "test_date": day.isoformat(),
        "alarm": f"{ALARM_HOUR:02d}:{ALARM_MINUTE:02d}",
        "wait_sec": wait_sec,
    }
    r.log(f"目标：周五 {day} {TEST_HOUR:02d}:{TEST_MINUTE:02d}，"
          f"每日闹钟 {ALARM_HOUR:02d}:{ALARM_MINUTE:02d} 开启")

    # 04:05 每日闹钟保持开启
    _set_daily_alarm(dev, r, ALARM_HOUR, ALARM_MINUTE)
    _wait_card(dev, r, day, wait_sec)

    dev.stayon(False)
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (
        f"完成。每天 {ALARM_HOUR:02d}:{ALARM_MINUTE:02d} 闹钟保持开启；"
        f"系统时间已到周五 {day} {TEST_HOUR:02d}:{TEST_MINUTE:02d}，"
        f"亮屏等待 {wait_sec}s 到 19:10，桌面智慧建议应出现「要关闭明天的闹钟吗？」。")
    return result


if __name__ == "__main__":
    import sys

    kwargs = {}
    if len(sys.argv) > 1:
        kwargs["wait_sec"] = int(sys.argv[1])
    try:
        out = run(emit=_cli_emit, **kwargs)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

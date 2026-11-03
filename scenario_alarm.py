"""起床闹钟延迟卡片触发场景（时间管理）。

按测试说明实现：
  1. 刷机后预热：把时间调到周三 22:00，保持亮屏 10 分钟，生成正常使用/窗口数据。
  2. 设置并启用每天 04:01 的闹钟。
  3. 把系统时间调到周三 23:39，**息屏等待 60 秒**到 23:40，再亮屏。
  4. 23:40 检查锁屏卡片；未看到则解锁并展开通知栏再看一次。
  5. 截图 → 前端确认 → 解锁。

闹钟通过系统 SET_ALARM intent 直接创建（SKIP_UI），不依赖时钟 App UI；
预热分钟数为 0 可跳过（已经刷机并正常使用过时可跳过）。

可独立运行： python scenario_alarm.py [预热分钟] [等待秒数]
"""
from __future__ import annotations

import datetime as _dt
import re
import time

from phone_ctl import KEY_HOME, KEY_WAKEUP, Device, UiError

from scenario_birthday import (
    Runner,
    _cli_emit,
    _fast_unlock,
    _unlock_with_retries,
    _wait_screen_on,
    device_date,
    disconnect_network,
    ensure_home_before_confirm,
    restore_network,
    set_system_datetime,
)

DESKCLOCK_PKG = "com.transsion.deskclock"
ALARM_CLOCK_PKG = "com.android.deskclock"
ALARM_HOUR = 4
ALARM_MINUTE = 1
WARMUP_HOUR = 22
TEST_HOUR = 23
TEST_MINUTE = 39       # 23:39 息屏，23:40 亮屏等卡片
_WEDNESDAY = 2         # date.weekday(): Monday=0


def _next_wednesday(today: _dt.date) -> _dt.date:
    """今天就是周三就用今天，否则取最近的周三。"""
    delta = (_WEDNESDAY - today.weekday()) % 7
    return today + _dt.timedelta(days=delta)


def _set_daily_alarm(dev: Device, r: Runner,
                     hour: int = ALARM_HOUR, minute: int = ALARM_MINUTE) -> str:
    """用 SET_ALARM intent 创建每天 hour:minute 的闹钟，并用 dumpsys alarm 校验。"""
    r.step(f"设置并启用每日闹钟 {hour:02d}:{minute:02d}")
    cmd = (
        "am start -a android.intent.action.SET_ALARM"
        f" --ei android.intent.extra.alarm.HOUR {hour}"
        f" --ei android.intent.extra.alarm.MINUTES {minute}"
        " --eia android.intent.extra.alarm.DAYS 1,2,3,4,5,6,7"
        " --ez android.intent.extra.alarm.SKIP_UI true"
        f" -p {DESKCLOCK_PKG}"
    )
    out = dev.shell(cmd)
    if "Error" in out or "Exception" in out:
        raise UiError(f"创建每日闹钟失败：{out.strip()[:300]}")
    time.sleep(0.8)

    raw = dev.shell("dumpsys alarm")
    pat = re.compile(
        r"Alarm clock:\s*\n\s*triggerTime=(\d{4}-\d{2}-\d{2}) "
        r"(\d{2}):(\d{2}):(\d{2})")
    found = None
    for m in pat.finditer(raw):
        if (int(m.group(2)), int(m.group(3))) == (hour, minute):
            found = m
            break
    if found is None:
        raise UiError(
            f"闹钟设置后没有在 AlarmManager 里找到 {hour:02d}:{minute:02d} "
            f"的 Alarm clock，时钟 App 可能未响应 SET_ALARM")
    r.ok(f"每日闹钟已启用，下次触发 {found.group(1)} "
         f"{found.group(2)}:{found.group(3)}")
    return f"{found.group(1)} {found.group(2)}:{found.group(3)}"


def _warm_up(dev: Device, r: Runner, day: _dt.date, minutes: int) -> None:
    """刷机预热：周三 22:00 亮屏保持 N 分钟，生成使用/窗口数据。"""
    if minutes <= 0:
        r.log("跳过刷机预热（warmup_min=0，适用于已正常使用过的设备）")
        return
    r.step(f"刷机后预热：{WARMUP_HOUR}:00 亮屏保持 {minutes} 分钟")
    set_system_datetime(dev, r, day, WARMUP_HOUR, 0)
    dev.stayon(True)
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    time.sleep(0.8)
    _fast_unlock(dev, r)
    dev.key(KEY_HOME)
    time.sleep(0.5)
    dev.stayon(True)
    r.log("保持亮屏，可正常使用手机，让系统生成 10 分钟使用/窗口数据")

    total = minutes * 60
    for elapsed in range(total):
        r.check()
        remain = total - elapsed
        if elapsed % 30 == 0 or remain == 1:
            r.tick(remain)
        time.sleep(1)
    # 只改时间并保持亮屏，不再额外读时间/做预热校验。
    r.ok("预热完成")


def _wait_card(dev: Device, r: Runner, day: _dt.date, wait_sec: int,
               unlock_retries: int) -> str:
    """调到周三 23:39，息屏等待到 23:40，再亮屏看卡片。"""
    r.step(f"系统时间调到周三 {TEST_HOUR:02d}:{TEST_MINUTE:02d}，"
           f"息屏等待 {wait_sec} 秒到 23:40")
    set_system_datetime(dev, r, day, TEST_HOUR, TEST_MINUTE)

    dev.stayon(False)
    time.sleep(0.3)
    dev.key(223)                      # KEYCODE_SLEEP
    if not _wait_screen_on(dev, False, timeout=1.2):
        r.log("警告：灭屏后屏幕仍为亮起状态")
    r.log("屏幕已灭，开始息屏等待")

    for elapsed in range(wait_sec):
        r.check()
        remain = wait_sec - elapsed
        if elapsed % 5 == 0 or remain == 1:
            r.tick(remain)
        time.sleep(1)

    # 23:40 才亮屏，给系统刷新卡片
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    time.sleep(0.8)
    dev.stayon(True)
    time.sleep(3.0)
    now = dev.shell("date '+%H:%M:%S'").strip()
    r.shot("锁屏卡片 23:40")
    r.ok(f"设备时间 {now}，已到 23:40 并亮屏")

    # 先拍锁屏，再自动上滑到桌面，最后让用户确认卡片
    _unlock_with_retries(dev, r, unlock_retries)
    dev.stayon(True)
    time.sleep(0.8)
    ensure_home_before_confirm(dev, r)
    r.shot("解锁后")
    r.step("确认起床闹钟延迟卡片是否出现（已自动解锁到桌面）")
    if r.confirm():
        r.ok("桌面已检查到卡片")
        return "桌面"

    r.log("桌面未确认，展开通知栏再检查")
    dev.shell("cmd statusbar expand-notifications")
    time.sleep(1.0)
    r.shot("通知栏卡片")
    ok = r.confirm()
    dev.shell("cmd statusbar collapse")
    time.sleep(0.4)
    if not ok:
        raise UiError("桌面和通知栏都没有确认到「起床闹钟延迟」卡片")
    ensure_home_before_confirm(dev, r)
    r.ok("通知栏已看到卡片")
    return "通知栏"


def run(dev: Device | None = None, emit=None, *, warmup_min: int = 10,
        wait_sec: int = 60, unlock_retries: int = 3, method: str = "real",
        control: dict | None = None,
        confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    # 时间管理三张卡片：第一步就断网。卡片只靠本地时间 + 本地闹钟判定，
    # 联网会引入在线时长之类的额外条件，把触发结果搞脏。
    disconnect_network(dev, r)
    try:
        return _run_trigger(dev, r, warmup_min=warmup_min, wait_sec=wait_sec,
                            unlock_retries=unlock_retries, method=method)
    finally:
        restore_network(dev, r)


def _run_trigger(dev: Device, r: Runner, *, warmup_min: int, wait_sec: int,
                 unlock_retries: int, method: str) -> dict:
    # Mock 触发：装 TransAtomicBrain → 点「MOCK 睡得有点晚卡」→ 回桌面出卡。
    # 不建闹钟、不改系统时间、不息屏等待，几秒钟就能出卡。
    if method == "mock":
        from scenario_atomic_mock import run_mock
        result = run_mock(dev, r, "delay", wait_sec)
        result["warmup_min"] = 0
        return result
    if method != "real":
        raise UiError(f"未知触发方式 {method!r}，只能是 real / mock")

    if not (0 <= warmup_min <= 30):
        raise UiError("warmup_min 必须在 0~30 分钟之间")
    if not (5 <= wait_sec <= 300):
        raise UiError("wait_sec 必须在 5~300 秒之间")

    today = device_date(dev)
    day = _next_wednesday(today)
    result = {
        "device_today": today.isoformat(),
        "test_date": day.isoformat(),
        "alarm": f"{ALARM_HOUR:02d}:{ALARM_MINUTE:02d}",
        "warmup_min": warmup_min,
        "wait_sec": wait_sec,
    }
    r.log(f"目标：周三 {day} {TEST_HOUR:02d}:{TEST_MINUTE:02d}，"
          f"每日闹钟 {ALARM_HOUR:02d}:{ALARM_MINUTE:02d}")

    # 按测试说明：先有 10 分钟正常使用数据，再设置每日闹钟。
    _warm_up(dev, r, day, warmup_min)

    # 闹钟创建/启用后再把时间拨到 23:39。
    result["alarm_next"] = _set_daily_alarm(dev, r)
    result["confirmed_on"] = _wait_card(dev, r, day, wait_sec, unlock_retries)

    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (
        f"完成。每日闹钟 {ALARM_HOUR:02d}:{ALARM_MINUTE:02d} 已启用；"
        f"系统时间已调到周三 {day} {TEST_HOUR:02d}:{TEST_MINUTE:02d}，"
        f"息屏等待 {wait_sec}s 到 23:40 后亮屏，起床闹钟延迟卡片应在锁屏/通知栏出现。")
    return result


if __name__ == "__main__":
    import sys

    kwargs = {}
    if len(sys.argv) > 1:
        kwargs["warmup_min"] = int(sys.argv[1])
    if len(sys.argv) > 2:
        kwargs["wait_sec"] = int(sys.argv[2])
    try:
        out = run(emit=_cli_emit, **kwargs)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

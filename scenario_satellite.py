"""卫星通话 / 玩机技巧卡片触发场景。

前置条件（用户提供）：
  1. `getprop ro.tr_telephony.satellite.support` 必须输出 1
  2. `pm clear com.transsion.atomicbrain` 清理原子化模拟器
  3. 断开网络再重新连接
  4. 联网 3 天（>72h），且当地时间到 10:00
     —— 场景把日期直接推到 +3 天、时间设 09:59，等到 10:00 触发

卡片属于「玩机技巧卡片」分组。
"""
from __future__ import annotations

import datetime as _dt
import time

from phone_ctl import (
    KEY_HOME,
    KEY_POWER,
    KEY_WAKEUP,
    Device,
    UiError,
)

from scenario_birthday import (
    Runner,
    _cli_emit,
    _prepare,
    _unlock_with_retries,
    _wait_screen_on,
    device_date,
    ensure_home_before_confirm,
    set_system_datetime,
)

SUPPORT_PROP = "ro.tr_telephony.satellite.support"
SATELLITE_MODE_SETTING = "satellite_mode_enabled"
PLAY_CARD_SETTING = "os_island_play_card_switch"
ATOMICBRAIN_PKG = "com.transsion.atomicbrain"
ONLINE_DAYS = 3
TRIGGER_HOUR = 10
TRIGGER_MIN = 0
PRESET_HOUR = 9
PRESET_MIN = 59


def _check_support(dev: Device) -> str:
    value = dev.shell(f"getprop {SUPPORT_PROP}").strip()
    if value != "1":
        raise UiError(
            f"当前设备不支持卫星通话：{SUPPORT_PROP}={value!r}，需要输出 1。"
            "请换支持卫星通话的机型，或先用 SPD 打开卫星通话/玩机技巧支持。")
    return value


def _ensure_satellite_mode(dev: Device, r: Runner) -> None:
    """SPD 开了支持属性后，部分机器卫星模式仍是关闭的，需要置 1。"""
    r.step("确认卫星模式已开启")
    value = dev.shell("settings get global satellite_mode_enabled").strip()
    if value != "1":
        dev.shell("settings put global satellite_mode_enabled 1")
        time.sleep(1.0)
        value = dev.shell("settings get global satellite_mode_enabled").strip()
    if value != "1":
        raise UiError(f"satellite_mode_enabled={value!r}，无法打开卫星模式；"
                      "请先用 SPD 开启卫星通话/玩机技巧支持")
    r.ok("satellite_mode_enabled = 1")


def _ensure_play_card(dev: Device, r: Runner) -> None:
    """SPD 的「玩机技巧」支持对应的 OS island play card 开关。"""
    r.step("确认玩机技巧卡片开关")
    value = dev.shell(f"settings get global {PLAY_CARD_SETTING}").strip()
    if value != "1":
        dev.shell(f"settings put global {PLAY_CARD_SETTING} 1")
        time.sleep(1.0)
        value = dev.shell(f"settings get global {PLAY_CARD_SETTING}").strip()
    if value != "1":
        raise UiError(f"{PLAY_CARD_SETTING}={value!r}，玩机技巧卡片开关未打开")
    r.ok(f"{PLAY_CARD_SETTING} = 1")


def _clear_atomicbrain(dev: Device, r: Runner) -> None:
    r.step(f"清理原子化模拟器 {ATOMICBRAIN_PKG}")
    out = dev.shell(f"pm clear {ATOMICBRAIN_PKG}").strip()
    if "Success" not in out:
        raise UiError(f"pm clear {ATOMICBRAIN_PKG} 失败：{out[:300]}")
    r.ok("Success")
    time.sleep(1.0)


def _toggle_network(dev: Device, r: Runner) -> None:
    """断开 Wi-Fi + 数据，再重新连接；等网络真正恢复。"""
    r.step("断开网络后重新连接")
    dev.shell("svc wifi disable")
    dev.shell("svc data disable")
    time.sleep(6)
    r.log("网络已断开 6 秒，重新连接")
    dev.shell("svc data enable")
    dev.shell("svc wifi enable")
    time.sleep(8)

    online = False
    for _ in range(20):
        r.check()
        out = dev.shell("ping -c 1 -W 1 8.8.8.8")
        if "1 received" in out or "1 packets received" in out:
            online = True
            break
        time.sleep(1)
    if not online:
        r.log("ping 8.8.8.8 未成功，但 Wi-Fi/数据已重新打开，继续")
    r.ok("网络已重新连接")


def _set_three_days_later(dev: Device, r: Runner) -> str:
    base = device_date(dev)
    target = base + _dt.timedelta(days=ONLINE_DAYS)
    set_system_datetime(dev, r, target, PRESET_HOUR, PRESET_MIN)
    return target.isoformat()


def _check_card_after_lock(dev: Device, r: Runner, unlock_retries: int = 3) -> bool:
    r.step("锁屏后再亮屏检查玩机技巧卡片")
    dev.key(KEY_HOME)
    time.sleep(0.4)
    dev.stayon(False)
    time.sleep(0.3)
    dev.key(223)                         # KEYCODE_SLEEP
    _wait_screen_on(dev, False, timeout=2.0)
    time.sleep(3.0)
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    time.sleep(8.0)                      # 等亮屏卡片渲染
    r.shot("亮屏-锁屏卡片")
    _unlock_with_retries(dev, r, unlock_retries)
    dev.stayon(True)
    time.sleep(0.8)
    ensure_home_before_confirm(dev, r)
    r.shot("解锁后")
    return r.confirm()


def run(dev: Device | None = None, emit=None, *, wait_sec: int = 75,
        control: dict | None = None, confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log
    if not (65 <= wait_sec <= 300):
        raise UiError("wait_sec 必须在 65~300 秒之间（9:59 要等到 10:00 之后）")

    result = {"wait_sec": wait_sec, "online_days": ONLINE_DAYS}

    r.step("检查卫星通话支持")
    support = _check_support(dev)
    result["satellite_support"] = support
    r.ok(f"{SUPPORT_PROP} = {support}")

    _ensure_satellite_mode(dev, r)
    _ensure_play_card(dev, r)
    _clear_atomicbrain(dev, r)

    # 关键：网络重连必须发生在 09:58，这样 +3 天后 10:00 才是 >72h。
    # 如果在下午重连、再把日期+3、时间设 09:59，实际只过了 66h，卡片不会出。
    r.step("先把系统时间设到 09:58，再断网重连")
    set_system_datetime(dev, r, device_date(dev), 9, 58)

    _toggle_network(dev, r)
    target = _set_three_days_later(dev, r)
    result["target_date"] = target
    r.log(f"已模拟联网 {ONLINE_DAYS} 天（>{ONLINE_DAYS * 24}h），"
          f"日期 {target}，时间 09:59，等待 10:00")

    r.step("回桌面并保持亮屏，等待 10:00 正常触发")
    _prepare(dev, r)
    dev.key(KEY_HOME)
    time.sleep(0.6)
    dev.stayon(True)
    for remain in range(wait_sec, 0, -1):
        r.check()
        r.tick(remain)
        time.sleep(1)
    now = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    r.ok(f"设备时间 {now}")
    r.shot("卫星通话卡片")

    r.step("确认智慧建议卡片")
    ensure_home_before_confirm(dev, r)
    ok = r.confirm()
    if not ok:
        r.step("锁屏后再检查智慧建议卡片")
        ok = _check_card_after_lock(dev, r)
    if not ok:
        raise UiError("桌面和锁屏都没有确认到卫星通话智慧建议卡片")
    r.ok("已确认卫星通话智慧建议卡片")

    dev.stayon(False)
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (
        "完成。已清理原子化模拟器、断网重连，并把日期推到 +3 天、"
        "时间从 09:59 等到 10:00；桌面/锁屏应出现卫星通话玩机技巧卡片。")
    return result


if __name__ == "__main__":
    import sys

    wait = int(sys.argv[1]) if len(sys.argv) > 1 else 75
    try:
        out = run(emit=_cli_emit, wait_sec=wait)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

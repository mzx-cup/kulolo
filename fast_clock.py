"""极速系统时间设置：adb shell cmd alarm set-time。

前提：设备 shell 拥有 android.permission.SET_TIME（Android 12+ 的
`cmd alarm set-time` 会检查该权限；Infinix/Android 17 实测可用）。
这比进设置页滚年/月/日/时/分快几个数量级，也不受设置页弹窗影响。

不支持的设备返回 False，由调用方回退到原来的设置界面滚轮。
"""
from __future__ import annotations

import datetime as dt
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from phone_ctl import Device


def _tz_from_offset(raw: str) -> dt.tzinfo | None:
    """把 date +%z 的 +0300 / +03:00 转成 timezone。"""
    m = re.match(r"([+-])(\d{2}):?(\d{2})", raw.strip())
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    return dt.timezone(sign * dt.timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def device_timezone(dev: Device) -> dt.tzinfo:
    """优先用系统时区 ID，拿不到就按当前 UTC 偏移兜底。"""
    raw = dev.shell("getprop persist.sys.timezone").strip()
    if raw:
        try:
            return ZoneInfo(raw)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    raw = dev.shell("date '+%z'").strip()
    return _tz_from_offset(raw) or dt.timezone.utc


def epoch_ms_for(dev: Device, target: dt.date, hour: int, minute: int) -> int:
    tz = device_timezone(dev)
    value = dt.datetime(target.year, target.month, target.day,
                        int(hour), int(minute), tzinfo=tz)
    return int(value.timestamp() * 1000)


_SUPPORT_CACHE: dict[str, bool] = {}


def supported(dev: Device) -> bool:
    """缓存 capability，避免每次设置都多一次 adb。"""
    key = dev.serial
    if key in _SUPPORT_CACHE:
        return _SUPPORT_CACHE[key]
    try:
        out = dev.shell("cmd alarm help")
        ok = "set-time" in out
    except Exception:
        ok = False
    _SUPPORT_CACHE[key] = ok
    return ok


def _read_clock(dev: Device) -> tuple[dt.date, int, int] | None:
    raw = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", raw)
    if not m:
        return None
    return (dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
            int(m.group(4)), int(m.group(5)))


def set_datetime(dev: Device, target: dt.date, hour: int, minute: int, log=None) -> bool:
    """直接设置系统日期/时间；成功返回 True。

    调用后保持 auto_time=0（与旧流程一致，卡片触发期间时间不会被网络覆盖）。
    失败（无权限/命令不存在/校验不一致）返回 False，由旧设置界面流程兜底。
    """
    if not supported(dev):
        return False
    try:
        epoch = epoch_ms_for(dev, target, hour, minute)
        dev.shell("settings put global auto_time 0")
        # 先跳到前一天再跳回目标日：强制产生一次时间/日期变化广播。
        # 同一目标日期重复跑时，OEM 锁屏卡片可能复用上次的通知而不刷新；
        # 这一步只多两个几十毫秒的 shell 调用，可避免显示上一轮的旧卡片。
        try:
            dev.shell(f"cmd alarm set-time {epoch - 86400000}")
            time.sleep(0.12)
        except Exception:
            pass
        out = dev.shell(f"cmd alarm set-time {epoch}")
        if any(x in out for x in ("Exception", "Error", "Permission denial", "SecurityException")):
            if log:
                log(f"直设时间失败：{out.strip()[:160]}")
            return False
        # 时钟在 adb 返回后可能还在同步广播，短暂轮询确认
        deadline = time.time() + 2.0
        while time.time() < deadline:
            cur = _read_clock(dev)
            if cur and cur[0] == target and cur[1] == int(hour) and cur[2] == int(minute):
                if log:
                    log(f"已直设系统时间：{target} {int(hour):02d}:{int(minute):02d}")
                return True
            time.sleep(0.15)
        cur = _read_clock(dev)
        if log:
            log(f"直设时间校验不一致：当前 {cur}，期望 {target} {int(hour):02d}:{int(minute):02d}")
        return False
    except Exception as exc:
        if log:
            log(f"直设时间异常，回退设置界面：{type(exc).__name__}: {exc}")
        return False

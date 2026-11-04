"""生日祝福卡片场景。

流程（对应用户描述）：
  1. 判断日历里是否已有「生日」事件：有就直接用它最新的那个；
     没有就在「今天+1」新建一个（复用生日策划案场景的日历操作）。
  2. 把系统时间调到该生日当天，时间取参数 hour:minute（默认 09:30）。
  3. 校验系统日期正是生日当天。
  4. 息屏等待约 1 分钟 → 亮屏 → 上滑解锁，查看锁屏上的祝福卡片。

可独立运行： python scenario_greeting.py [息屏秒数]
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import time

import fixtures
from phone_ctl import Device, UiError

from scenario_birthday import (
    CALENDAR_CMP,
    Runner,
    _add_important_event,
    _EV_TYPES,
    _cli_emit,
    _focus_or_close_shade,
    _prepare,
    _select_calendar_day,
    _shift_months,
    device_date,
    gen_name,
    screen_off_wait_unlock,
    set_system_datetime,
)

EXT_PROPS_URI = "content://com.android.calendar/extendedproperties"
EVENTS_URI = "content://com.android.calendar/events"
CAL_TYPE_NAME = "private:ts_cal_event_type"
# 观演日（Show Day）的类型标记 name 没有 private: 前缀（实机验证）
CAL_TYPE_NAME_NO_PREFIX = "ts_cal_event_type"
CAL_TYPE_BIRTHDAY = "birthday"
CAL_TYPE_ANNIVERSARY = "anniversary"

_ROW_RE = re.compile(r"^\s*Row:\s*\d+\s+(.*)$")


def _query(dev: Device, uri: str, projection: str, where: str | None = None) -> list[dict]:
    """跑一次 content query，把 'Row: N k=v, k=v' 解析成 dict 列表。"""
    cmd = f"content query --uri {uri} --projection {projection}"
    if where:
        cmd += f' --where "{where}"'
    out = dev.shell(cmd)
    rows: list[dict] = []
    for line in out.splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        row = {}
        for part in m.group(1).split(", "):
            if "=" in part:
                k, v = part.split("=", 1)
                row[k.strip()] = v.strip()
        rows.append(row)
    return rows


def find_important_day(dev: Device, ev_value: str) -> tuple[_dt.date, str, int] | None:
    """找日历里最新的指定类型重要日事件（生日/纪念日/考试/观演日），返回 (日期, 标题, event_id)。

    类型标记在 extendedproperties 里：name=private:ts_cal_event_type（生日/纪念日/考试）
    或 name=ts_cal_event_type（观演日 Show Day，无前缀），value=ev_value，
    取 event_id 最大（最新创建）的那个，再去 events 表读它的 dtstart。
    """
    rows = _query(dev, EXT_PROPS_URI, "event_id:name:value",
                  f"(name='{CAL_TYPE_NAME}' OR name='{CAL_TYPE_NAME_NO_PREFIX}')")
    ids = [int(r["event_id"]) for r in rows
           if r.get("value") == ev_value and r.get("event_id", "").isdigit()]
    if not ids:
        return None
    eid = max(ids)
    ev = _query(dev, EVENTS_URI, "_id:title:dtstart", f"_id={eid}")
    if not ev or "dtstart" not in ev[0]:
        return None
    # 全天事件 dtstart 是 UTC 零点，用 UTC 取日期才不偏移
    bday = _dt.datetime.fromtimestamp(int(ev[0]["dtstart"]) / 1000,
                                      tz=_dt.timezone.utc).date()
    return bday, ev[0].get("title", ""), eid


def find_birthday(dev: Device) -> tuple[_dt.date, str, int] | None:
    """兼容入口：按生日类型查找。"""
    return find_important_day(dev, CAL_TYPE_BIRTHDAY)


def _run_fast(dev: Device, r: Runner, *, today: _dt.date, hour: int, minute: int,
              wait_sec: int, unlock_retries: int, name: str | None,
              offset_months: int, desktop_wait_sec: int, second_off_sec: float,
              ev_value: str,
              ev_display: str) -> dict:
    """极速祝福卡片：fixture 更新 + 直设时间，不打开日历 UI。"""
    target = today + _dt.timedelta(days=1)
    if offset_months:
        target = _shift_months(target, offset_months)
        r.log(f"重新触发：目标日期平移 +{offset_months} 月 → {target}")
    name = name or gen_name(today)
    et = _EV_TYPES.get(ev_value, _EV_TYPES[CAL_TYPE_BIRTHDAY])

    fx = fixtures.get(dev, ev_value)
    fx_row = fixtures.get_event(dev, int(fx["event_id"])) if fx else None
    fast_mode = fx_row is not None
    if fast_mode and not fixtures.event_has_type(dev, int(fx_row["_id"]), ev_value):
        r.log(f"fixture #{fx_row['_id']} 已不是「{ev_display}」重要日事件"
              f"（类型标记丢失或被普通事件复用），清除后重新走一次日历 seed")
        fixtures.clear(dev, ev_value)
        fx_row = None
        fast_mode = False
    if fast_mode:
        r.log(f"极速模式：fixture #{fx_row['_id']} 已登记，跳过解锁/日历准备")
    else:
        _prepare(dev, r)

    def _seed_event() -> None:
        _select_calendar_day(dev, r, target, "今天+1", "1天后")
        _add_important_event(dev, r, name, ev_value=ev_value,
                             type_cn=et["cn"], type_en=et["en"], placeholder=et["ph"],
                             type_labels=et.get("labels"))

    created = False
    if fast_mode:
        r.step("极速模式：更新 fixture 事件（不打开日历）")
        if fixtures.update_event(dev, fx_row, name, target):
            fx = fx_row
            r.ok(f"事件 #{fx_row['_id']} → {name} / {target}")
        else:
            r.log("fixture 更新失败，回退到 UI 重建（仅这一次）")
            fixtures.clear(dev, ev_value)
            _prepare(dev, r)
            _seed_event()
            fx = fixtures.find_latest(dev, ev_value, name)
            if not fx:
                raise UiError("回退重建 fixture 后仍找不到事件")
            fixtures.register(dev, ev_value, fx)
            created = True
            r.ok(f"已重新登记 fixture #{fx['_id']}")
    else:
        _seed_event()
        fx = fixtures.find_latest(dev, ev_value, name)
        if not fx:
            raise UiError("首次创建后仍未在 CalendarProvider 中找到 fixture 事件")
        fixtures.register(dev, ev_value, fx)
        created = True
        r.log(f"已登记 fixture #{fx['_id']}，下次开始走极速更新，不再进日历 UI")
        if not fixtures.update_event(dev, fx, name, target):
            r.log("警告：fixture 首次更新失败，沿用刚创建的 UI 事件")

    result = {
        "device_today": today.isoformat(),
        "fixture_event_id": int(fx["_id"]),
        "fixture_created": created,
    }
    set_system_datetime(dev, r, target, hour, minute)
    raw = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", raw)
    if not m:
        raise UiError(f"无法解析设备时间：{raw!r}")
    cur = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if cur != target:
        raise UiError(f"系统日期 {cur} 与{ev_display} {target} 不一致")
    result["device_time"] = raw
    r.ok(f"设备时间 {raw}，{ev_display}卡片目标日 {target}")

    result["device_time_after"] = screen_off_wait_unlock(
        dev, r, wait_sec, unlock_retries, desktop_wait_sec=desktop_wait_sec,
        second_off_sec=second_off_sec)
    result.update(birthday=target.isoformat(), created=created, name=name,
                  steps=r._no, ok=True)
    result["summary"] = (
        f"完成。{ev_display} {target}（{'首次建 fixture' if created else '极速复用'}），"
        f"系统时间已到{ev_display}当天，锁屏应显示「{name}·{ev_display}」祝福卡片。")
    return result


def run(dev: Device | None = None, emit=None, *, hour: int = 9, minute: int = 30,
        wait_sec: int = 60, unlock_retries: int = 3, name: str | None = None,
        offset_months: int = 0, desktop_wait_sec: int = 0,
        second_off_sec: float = 0,
        ev_value: str = CAL_TYPE_BIRTHDAY, ev_display: str = "生日",
        no_lookup: bool = False, control: dict | None = None,
        confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    # 默认走极速通道；PHONE_REMOTE_LEGACY=1 可回到旧的查找/复用事件流程。
    if os.environ.get("PHONE_REMOTE_LEGACY") != "1":
        return _run_fast(
            dev, r, today=device_date(dev), hour=hour, minute=minute,
            wait_sec=wait_sec, unlock_retries=unlock_retries, name=name,
            offset_months=offset_months, desktop_wait_sec=desktop_wait_sec,
            second_off_sec=second_off_sec,
            ev_value=ev_value, ev_display=ev_display)

    today = device_date(dev)
    result = {"device_today": today.isoformat()}

    _prepare(dev, r)

    r.step(f"判断日历里是否已有{ev_display}")
    if no_lookup:
        # 不查找已有事件（如 None 类型无类型标记查不到），每次直接新建
        bday = today + _dt.timedelta(days=1)
        name = name or gen_name(today)
        created = True
        r.log(f"不查找已有事件，直接在「今天+1」= {bday} 新建：{name}")
        r.ok("未找到，将在今天+1 新建")
        _select_calendar_day(dev, r, bday, "今天+1", "1天后")
        et = _EV_TYPES.get(ev_value, _EV_TYPES[CAL_TYPE_BIRTHDAY])
        _add_important_event(dev, r, name, ev_value=ev_value,
                             type_cn=et["cn"], type_en=et["en"], placeholder=et["ph"],
                             type_labels=et.get("labels"))
    else:
        found = find_important_day(dev, ev_value)
        if found:
            bday, name, eid = found
            created = False
            r.log(f"已有{ev_display}事件 #{eid}（{name}），日期 {bday}")
            r.ok(f"{bday}（复用已有）")
        else:
            bday = today + _dt.timedelta(days=1)
            name = name or gen_name(today)
            created = True
            r.log(f"日历里没有{ev_display}，改在「今天+1」= {bday} 新建一个：{name}")
            r.ok("未找到，将在今天+1 新建")
            _select_calendar_day(dev, r, bday, "今天+1", "1天后")
            et = _EV_TYPES.get(ev_value, _EV_TYPES[CAL_TYPE_BIRTHDAY])
            _add_important_event(dev, r, name, ev_value=ev_value,
                                 type_cn=et["cn"], type_en=et["en"], placeholder=et["ph"],
                             type_labels=et.get("labels"))

    # 重新触发：卡片本月已触发过，把目标日期整体平移 n 个月再试
    if offset_months:
        bday = _shift_months(bday, offset_months)
        r.log(f"重新触发：目标日期平移 +{offset_months} 月 → {bday}")

    set_system_datetime(dev, r, bday, hour, minute)

    r.step(f"校验系统日期确为{ev_display}当天 {bday}")
    dev.shell("am start -n " + CALENDAR_CMP)
    _focus_or_close_shade(dev, "calendar", timeout=10)
    time.sleep(0.4)
    raw = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", raw)
    if not m:
        raise UiError(f"无法解析设备时间：{raw!r}")
    cur = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if cur != bday:
        raise UiError(f"系统日期 {cur} 与{ev_display} {bday} 不一致")
    result["device_time"] = raw
    r.ok(f"设备时间 {raw}")

    result["device_time_after"] = screen_off_wait_unlock(
        dev, r, wait_sec, unlock_retries, desktop_wait_sec=desktop_wait_sec,
        second_off_sec=second_off_sec)
    result.update(birthday=bday.isoformat(), created=created, name=name,
                  steps=r._no, ok=True)
    result["summary"] = (
        f"完成。{ev_display} {bday}（{'新建' if created else '复用已有'}），"
        f"已把系统时间调到{ev_display}当天并解锁，锁屏应显示「{name}·{ev_display}」祝福卡片。")
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

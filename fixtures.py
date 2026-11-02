"""设备 fixture（测试事件）登记与极速更新。

为什么不直接插入新的「重要日」事件？
------------------------------------------------
Transsion 日历把重要日类型存在 CalendarProvider 的 extendedproperties 表：
    name = private:ts_cal_event_type 或 ts_cal_event_type
但该表只允许 sync adapter 写入，普通 shell/App 会被拒绝。因此本工具不新建
类型行，而是复用一次（首次通过 UI 创建）的 fixture 事件，之后只改它的
title / dtstart。每次运行都得到一个新的日期和姓名，类型扩展属性保持不变。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shlex
from pathlib import Path

from phone_ctl import Device

FIXTURE_FILE = Path(__file__).with_name("fixtures.json")
EVENTS_URI = "content://com.android.calendar/events"
EXTPROPS_URI = "content://com.android.calendar/extendedproperties"
TYPE_NAMES = ("private:ts_cal_event_type", "ts_cal_event_type")
_ROW_RE = re.compile(r"^\s*Row:\s*\d+\s+(.*)$")


# ── 配置文件 ───────────────────────────────────────────────────────
def _load() -> dict:
    try:
        data = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    tmp = FIXTURE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FIXTURE_FILE)


def get(dev: Device, ev_value: str) -> dict | None:
    data = _load()
    return (data.get("devices", {}).get(dev.serial, {}) or {}).get(ev_value)


def register(dev: Device, ev_value: str, event: dict) -> None:
    data = _load()
    devices = data.setdefault("devices", {})
    per_dev = devices.setdefault(dev.serial, {})
    per_dev[ev_value] = {
        "event_id": int(event["_id"]),
        "calendar_id": int(event.get("calendar_id") or 0),
        "title": event.get("title", ""),
        "registered_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)


def clear(dev: Device | None = None, ev_value: str | None = None) -> None:
    data = _load()
    devices = data.get("devices", {})
    if dev is None:
        data = {}
    elif ev_value is None:
        devices.pop(dev.serial, None)
    else:
        devices.get(dev.serial, {}).pop(ev_value, None)
    _save(data)


# ── 查询 ───────────────────────────────────────────────────────────
def _query(dev: Device, uri: str, projection: str, where: str | None = None) -> list[dict]:
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


def get_event(dev: Device, event_id: int) -> dict | None:
    rows = _query(dev, EVENTS_URI,
                  "_id:title:calendar_id:dtstart:dtend:duration:allDay:rrule",
                  f"_id={int(event_id)}")
    return rows[0] if rows else None


def event_exists(dev: Device, event_id: int) -> bool:
    return get_event(dev, event_id) is not None


def event_has_type(dev: Device, event_id: int, ev_value: str) -> bool:
    """fixture 事件是否仍带正确的「重要日类型」扩展属性。

    只看事件是否还存在不够：同一个 event_id 可能被普通事件复用，
    或 fixture 被删后重建成了普通全天事件。这时极速更新只会改标题/日期，
    日历里不会出现重要日提醒，必须让调用方重新走一次 UI seed。
    none 类型没有 extendedproperties，不要求类型标记。
    """
    if ev_value == "none":
        return True
    rows = _query(dev, EXTPROPS_URI, "event_id:name:value",
                  f"event_id={int(event_id)}")
    return any(r.get("value") == ev_value for r in rows)


def _latest_typed(dev: Device, ev_value: str) -> dict | None:
    names = " OR ".join(f"name='{n}'" for n in TYPE_NAMES)
    rows = _query(dev, EXTPROPS_URI, "event_id:name:value",
                  f"({names}) AND value='{ev_value}'")
    ids = [int(r["event_id"]) for r in rows if r.get("event_id", "").isdigit()]
    if not ids:
        return None
    return get_event(dev, max(ids))


def _by_title(dev: Device, title: str) -> dict | None:
    if not title:
        return None
    safe = title.replace("'", "''")
    rows = _query(dev, EVENTS_URI,
                  "_id:title:calendar_id:dtstart:dtend:duration:allDay:rrule",
                  f"title='{safe}'")
    if not rows:
        return None
    return max(rows, key=lambda r: int(r.get("_id", "0")))


def find_latest(dev: Device, ev_value: str, title: str | None = None) -> dict | None:
    """优先按类型找最新事件；无类型或找不到时按标题找。"""
    if ev_value != "none":
        ev = _latest_typed(dev, ev_value)
        if ev:
            return ev
    if title:
        return _by_title(dev, title)
    return None


# ── 极速更新 ───────────────────────────────────────────────────────
def _date_to_utc_ms(day: dt.date) -> int:
    value = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    return int(value.timestamp() * 1000)


def update_event(dev: Device, event: dict, title: str, day: dt.date) -> bool:
    """只改 title/dtstart；保留 duration/dtend 中已有的那个，避免 DTEND+DURATION 冲突。"""
    if not title or ":" in title:
        # content 的 --bind 用冒号分段，标题里有冒号会破坏参数；交给 UI 兜底
        return False
    eid = int(event["_id"])
    dtstart = _date_to_utc_ms(day)
    qtitle = shlex.quote(title)
    bind = f"--bind title:s:{qtitle} --bind dtstart:l:{dtstart}"
    duration = (event.get("duration") or "").strip()
    dtend = (event.get("dtend") or "").strip()
    if duration in ("", "NULL") and dtend not in ("", "NULL"):
        bind += f" --bind dtend:l:{dtstart + 86400000}"
    cmd = f'content update --uri {EVENTS_URI} {bind} --where "_id={eid}"'
    out = dev.shell(cmd)
    if any(x in out for x in ("Exception", "Error", "SecurityException", "IllegalArgument")):
        return False
    got = get_event(dev, eid)
    if not got:
        return False
    return (got.get("title") == title
            and got.get("dtstart") == str(dtstart))


def ensure_fixture(dev: Device, ev_value: str, *, title: str, day: dt.date,
                   seed) -> tuple[dict, bool]:
    """返回 (event, 是否本次新建 fixture)。

    seed 是首次创建用的回调：它负责走一次原日历 UI 建事件，创建完成后
    这里会自动查询并登记。之后所有运行都只做 content update。
    """
    fx = get(dev, ev_value)
    if fx:
        ev = get_event(dev, int(fx["event_id"]))
        if ev and event_has_type(dev, int(ev["_id"]), ev_value):
            return ev, False
        clear(dev, ev_value)

    seed()
    ev = find_latest(dev, ev_value, title)
    if not ev:
        raise RuntimeError("fixture 创建后仍未在 CalendarProvider 中找到事件")
    register(dev, ev_value, ev)
    return ev, True

"""一次性预置所有「重要日」fixture（每种类型只 seed 一次）。

用法（手机已连接、日历 App 可用）：
    python seed_important_days.py

之后生日/纪念日/考试/观演日/重要日提醒的极速路径都不再打开日历。
已经登记过且事件仍存在的类型会自动跳过。
"""
from __future__ import annotations

import sys
import time

from phone_ctl import Device, UiError
from fixtures import find_latest, get as get_fixture, get_event, register
from scenario_birthday import (
    Runner,
    _EV_TYPES,
    _add_important_event,
    _prepare,
    _select_calendar_day,
    device_date,
)

# (ev_value, fixture 名称, 目标日期 = 今天 + N 天)
TYPES = [
    ("birthday", "SeedBday", 1),
    ("anniversary", "SeedAnniv", 2),
    ("exam", "SeedExam", 3),
    ("performance", "SeedShow", 4),
    ("none", "SeedDay", 5),
]


def _emit(e: dict) -> None:
    t = e.get("t")
    if t == "step":
        if e.get("state") == "start":
            print(f"\n[{e['no']}] {e['title']}", flush=True)
        else:
            print(f"      OK {e.get('ms', 0)}ms {e.get('detail', '')}", flush=True)
    elif t == "log":
        print(f"      · {e['msg']}", flush=True)


def main() -> int:
    dev = Device()
    r = Runner(dev, _emit)
    dev.log = r.log

    today = device_date(dev)
    print(f"设备 {dev.serial}，今天 {today}，开始预置重要日 fixture", flush=True)

    _prepare(dev, r)
    made = 0
    skipped = 0
    for ev_value, name, offset in TYPES:
        et = _EV_TYPES[ev_value]
        fx = get_fixture(dev, ev_value)
        if fx and get_event(dev, int(fx["event_id"])):
            print(f"\n== {ev_value} 已有 fixture #{fx['event_id']}，跳过 ==", flush=True)
            skipped += 1
            continue
        day = today.__class__.fromordinal(today.toordinal() + offset)
        print(f"\n== 预置 {ev_value}: {name} / {day} ==", flush=True)
        try:
            _select_calendar_day(dev, r, day, f"今天+{offset}", f"{offset}天后")
            _add_important_event(
                dev, r, name, ev_value=ev_value,
                type_cn=et["cn"], type_en=et["en"], placeholder=et["ph"])
            time.sleep(0.8)
            got = find_latest(dev, ev_value, name)
            if not got:
                raise UiError(
                    f"保存后在 CalendarProvider 里找不到 {ev_value} 的 fixture（{name}）")
            register(dev, ev_value, got)
            made += 1
            print(f"      OK 登记 {ev_value} -> event #{got['_id']}", flush=True)
        except UiError as exc:
            print(f"      ERR {ev_value} 失败：{exc}", flush=True)

    dev.stayon(False)
    print(f"\n完成：新登记 {made} 个，跳过 {skipped} 个。"
          f"当前 fixtures.json 已按设备 {dev.serial} 保存。", flush=True)
    return 0 if made or skipped else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        sys.exit(130)

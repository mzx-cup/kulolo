"""节日祝福卡片触发场景。

流程（对应用户描述，去掉语言/地区自动设置——由用户自行保证 OOBE 国家=中国）：
  0. 中国节日前置询问：OOBE 国家是否已调整到中国？选「否」立即中止。
     圣诞节 / 圣诞夜不走中国 OOBE 逻辑，不询问，直接触发。
  1. 遍历已配置节日，对每个节日：
     a. 进入日期与时间设置，关闭自动设置时间，日期设为节日当天、
        时间设为 9:00~22:00 之间（默认 09:30）。
     b. 校验系统日期正是节日当天。
     c. 回桌面屏幕常亮等待约 1 分钟 → 锁屏 → 亮屏上滑解锁，
        查看锁屏上的节日祝福卡片。
     d. 截图 + 让用户在网页端确认卡片是否已触发（UI 检查）。

节日表：除春节是明年（2027），其余都是今年（2026）。

可独立运行： python scenario_festival.py [wait_sec]
"""
from __future__ import annotations

import datetime as _dt
import re
import time

from phone_ctl import (
    KEY_HOME,
    KEY_POWER,
    KEY_WAKEUP,
    Device,
    UiError,
)

from scenario_birthday import (
    CALENDAR_CMP,
    Runner,
    _cli_emit,
    _focus_or_close_shade,
    _prepare,
    _unlock_with_retries,
    _wait_screen_on,
    device_date,
    set_system_datetime,
)

# 已配置节日：春节是明年（2027），其余为今年（2026）
FESTIVALS = [
    {"id": "chunjie",    "name": "春节",   "date": _dt.date(2027, 2, 6)},
    {"id": "duanwu",     "name": "端午节", "date": _dt.date(2026, 6, 19)},
    {"id": "zhongqiu",   "name": "中秋节", "date": _dt.date(2026, 9, 25)},
    {"id": "guoqing",    "name": "国庆节", "date": _dt.date(2026, 10, 1)},
    {"id": "xinnian",    "name": "新年",   "date": _dt.date(2026, 1, 1)},
    {"id": "dongzhi",    "name": "冬至",   "date": _dt.date(2026, 12, 21)},
    {"id": "shengdan",   "name": "圣诞节", "date": _dt.date(2026, 12, 25)},
    {"id": "shengdanye", "name": "圣诞夜", "date": _dt.date(2026, 12, 24)},
]
FESTIVALS_BY_ID = {f["id"]: f for f in FESTIVALS}
# 圣诞节/圣诞夜不依赖中国 OOBE，触发前不询问
NO_OOBE_FESTIVALS = {"shengdan", "shengdanye"}

_TIME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})")


def _check_time_range(hour: int, minute: int) -> None:
    """系统时间必须在 9:00~22:00 之间，否则节日卡片不触发。"""
    hour, minute = int(hour), int(minute)
    ok = 9 <= hour <= 21 or (hour == 22 and minute == 0)
    if not ok:
        raise UiError(f"系统时间 {hour:02d}:{minute:02d} 不在 9:00~22:00 之间，"
                      f"节日卡片无法正常触发")


def _stayon_wait_lock_unlock(dev: Device, r: Runner, wait_sec: int,
                             unlock_retries: int) -> str:
    """回桌面，屏幕常亮等待 wait_sec 秒，再锁屏 → 亮屏 → 上滑解锁。

    返回解锁后的设备时间字符串。常亮等待期间暂停/结束可随时响应（check 每轮执行）。
    """
    r.step(f"回桌面屏幕常亮等待 {wait_sec} 秒")
    dev.key(KEY_HOME)
    time.sleep(0.5)
    dev.stayon(True)
    for remain in range(wait_sec, 0, -1):
        r.check()
        if remain % 5 == 0 or remain == 1:
            r.tick(remain)
        time.sleep(1)
    now = dev.shell("date '+%H:%M:%S'").strip()
    r.ok(f"设备时间 {now}")

    r.step("锁屏后亮屏上滑解锁")
    dev.stayon(False)
    time.sleep(0.3)
    dev.key(KEY_POWER)
    if not _wait_screen_on(dev, False, timeout=3.0):
        r.log("警告：息屏后屏幕仍为亮起状态")
    time.sleep(3)                        # 锁屏停留几秒，给系统刷新节日卡片的机会
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    time.sleep(8)                        # 亮屏后等卡片渲染（同纪念日二次流程，太早截图会全黑）
    r.shot("亮屏-锁屏卡片")
    _unlock_with_retries(dev, r, unlock_retries)
    dev.stayon(True)
    time.sleep(0.8)                      # 等桌面渲染完再截，避免截到锁屏残影
    now = dev.shell("date '+%H:%M:%S'").strip()
    r.ok(f"设备时间 {now}")
    return now


def _run_one_festival(dev: Device, r: Runner, f: dict, hour: int, minute: int,
                      wait_sec: int, unlock_retries: int) -> dict:
    """单个节日的完整流程：调日期时间 → 校验 → 常亮等待 → 锁屏解锁 → 确认卡片。"""
    r.log(f"———— 开始节日：{f['name']}（{f['date']}）————")
    set_system_datetime(dev, r, f["date"], hour, minute)

    r.step(f"校验系统日期确为{f['name']}当天")
    dev.shell("am start -n " + CALENDAR_CMP)   # 让日历感知时间变更
    dev.wait_focus("calendar", timeout=10)
    time.sleep(0.4)
    raw = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    m = _TIME_RE.match(raw)
    if not m:
        raise UiError(f"无法解析设备时间：{raw!r}")
    cur = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if cur != f["date"]:
        raise UiError(f"系统日期 {cur} 与预期节日当天 {f['date']} 不一致")
    r.ok(f"设备时间 {raw}，正是{f['name']}当天")

    _stayon_wait_lock_unlock(dev, r, wait_sec, unlock_retries)

    r.step(f"确认 {f['name']} 卡片是否已触发")
    r.confirm()
    r.ok()
    r.shot("解锁后")
    return {"festival": f["name"], "date": f["date"].isoformat()}


def run(dev: Device | None = None, emit=None, *, hour: int = 9, minute: int = 30,
        wait_sec: int = 60, unlock_retries: int = 3, festival: str | None = None,
        control: dict | None = None, confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    _check_time_range(hour, minute)
    today = device_date(dev)
    result = {"device_today": today.isoformat(), "results": []}

    _prepare(dev, r)

    fests = ([FESTIVALS_BY_ID[festival]] if festival in FESTIVALS_BY_ID
             else FESTIVALS)

    # 只有中国节日需要 OOBE 中国；圣诞节/圣诞夜跳过询问。
    needs_oobe = any(f["id"] not in NO_OOBE_FESTIVALS for f in fests)
    if needs_oobe:
        r.step("询问用户：OOBE 国家是否已调整到中国")
        if not r.ask("是否已在 OOBE 里把国家调整到中国？"
                     "只有中国节日才需要调整到中国，才能正常触发节日卡片。"):
            raise UiError("用户确认未把国家调到中国，已中止触发。请先在 OOBE 中把国家调整到中国后重试")
        r.ok("国家为中国，继续触发")
    else:
        r.log("圣诞节/圣诞夜不依赖中国 OOBE，跳过国家询问")

    for f in fests:
        res = _run_one_festival(dev, r, f, hour, minute, wait_sec, unlock_retries)
        result["results"].append(res)

    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (f"节日卡片遍历完成（{len(fests)} 个）："
                         + "、".join(f['name'] for f in fests)
                         + "。锁屏应依次出现对应节日祝福卡片。")
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

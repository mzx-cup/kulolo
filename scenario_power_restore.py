"""停电恢复卡片（KPLC Power Outage Restoration）触发场景。

对应 atomicbrain 规则 **64381**（`AITIPS_Power_outage_restoration`，intent 同预警卡）：

  33  TimeSlotAbility        时段触发（0 = 到点触发）
  29  CountryAbility         国家必须 CONTAIN "KE"
  21  MinTimeIntervalAbility 两张恢复卡之间至少 60 分钟（extra.type = MIN）

**与省电卡的关键差别**：
- 不需要 mock 电量（规则 64381 根本不检查电量和充电状态）；
- 时间调到停电公告结束前 2 小时（16:30），而不是停电进行中的 12:30；
- **必须先 `dumpsys battery reset`**：三张停电卡同属 `conflict_group:
  kplc_power_outage_active`，先到的会把后来的 DROP 掉。上一轮省电卡留下的
  `dumpsys battery set level 30` 是持久的，不清就会让省电卡一直先出，
  日志里能看到 `TAB.BlackoutIntent: sendIntent: blocked by conflict_group,
  scenario=RESTORATION`。

流程（用户 m08836 指定：在省电卡基础上去掉电量 mock、时间改 16:30）：
  保网络 → 装 TransAtomicBrain → 时区内罗毕 + 国家 KE → 清掉电池 mock →
  系统时间 09-18 12:29 → pm clear atomiccore + atomicbrain → 打开 debug 页滚到底 →
  点「查询 KPLC API」→ 时间调到 16:30 → 息屏 10 秒 → 亮屏上滑解锁 → 出卡
"""
from __future__ import annotations

import datetime as _dt
import time

from phone_ctl import KEY_HOME, KEY_WAKEUP, Device, UiError

from scenario_atomic_mock import ensure_installed
from scenario_birthday import (
    Runner,
    _cli_emit,
    _unlock_with_retries,
    ensure_home_before_confirm,
    set_system_datetime,
)
from scenario_power_outage import COUNTRY, TIMEZONE, _clear_atomic, _ensure_network, _set_timezone
from scenario_power_saving import (
    DEFAULT_DAY,
    DEFAULT_MONTH,
    DEFAULT_YEAR,
    KPLC_AREA,
    SETUP_HOUR,
    SETUP_MIN,
    check_kplc_fields,
    open_debug_page,
    query_kplc,
    reset_battery,
    screen_off_and_unlock,
    scroll_to_kplc,
    wait_card,
)

# 恢复卡默认 16:30（= 公告 05:30~14:00 UTC 即 08:30~17:00 EAT 结束前 2 小时）
TRIGGER_HOUR = 16
TRIGGER_MIN = 30
OFF_SECONDS = 10
WAIT_CARD_SEC = 90

# 卡片文案（中/英/阿）—— 与省电卡区分开
RESTORE_HINTS_ZH = ("电力恢复时间", "恢复时间", "电力已恢复", "供电已恢复", "电力恢复")
RESTORE_HINTS_EN = ("power restoration", "power restored", "restoration time",
                    "electricity restored", "power is back", "restored")
RESTORE_HINTS_AR = ("استعادة الكهرباء", "عودة الكهرباء", "وقت الاستعادة",
                    "تم استعادة", "الكهرباء", "استعادة")


def run(dev: Device | None = None, emit=None, *,
        year: int = DEFAULT_YEAR, month: int = DEFAULT_MONTH, day: int = DEFAULT_DAY,
        hour: int = TRIGGER_HOUR, minute: int = TRIGGER_MIN,
        off_sec: int = OFF_SECONDS, wait_sec: int = WAIT_CARD_SEC,
        unlock_retries: int = 3, control: dict | None = None,
        confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    if not (10 <= off_sec <= 300):
        raise UiError("off_sec（息屏等待）必须在 10~300 秒之间")
    if not (20 <= wait_sec <= 240):
        raise UiError("wait_sec（等卡片）必须在 20~240 秒之间")
    if not (0 <= hour <= 23):
        raise UiError("触发小时必须在 0~23 之间")

    try:
        target = _dt.date(int(year), int(month), int(day))
    except ValueError as exc:
        raise UiError(f"触发日期不合法：{year}-{month}-{day}（{exc}）") from exc

    result = {
        "target_date": target.isoformat(),
        "trigger_at": f"{int(hour):02d}:{int(minute):02d}",
        "setup_at": f"{SETUP_HOUR:02d}:{SETUP_MIN:02d}",
        "kplc_area": KPLC_AREA,
        "off_sec": int(off_sec),
        "wait_sec": int(wait_sec),
        "timezone": TIMEZONE,
        "country": COUNTRY,
    }

    ensure_installed(dev, r)
    _ensure_network(dev, r)
    _set_timezone(dev, r)

    # 上一轮省电卡留下的 battery mock 是持久的，不清会让省电卡一直先出、
    # 恢复卡被 conflict_group 直接 DROP。
    r.step("清掉上一轮残留的电池 mock（否则省电卡会抢占 conflict_group）")
    reset_battery(dev, r)

    r.step("先解锁回桌面")
    dev.stayon(True)
    dev.key(KEY_WAKEUP)
    time.sleep(0.8)
    if dev.locked():
        _unlock_with_retries(dev, r, unlock_retries)
    dev.key(KEY_HOME)
    time.sleep(0.8)
    r.ok("已在桌面")

    r.step(f"把系统时间调到 {target.isoformat()} "
           f"{SETUP_HOUR:02d}:{SETUP_MIN:02d}（让 KPLC 日期框默认成当天）")
    set_system_datetime(dev, r, target, SETUP_HOUR, SETUP_MIN)
    r.ok(f"设备时间 {dev.shell('date').strip()}")

    _clear_atomic(dev, r)

    hit = None
    try:
        open_debug_page(dev, r)
        scroll_to_kplc(dev, r)
        check_kplc_fields(dev, r, target)
        result["kplc_result"] = query_kplc(dev, r, target)[:400]

        r.step(f"把系统时间调到 {target.isoformat()} {int(hour):02d}:{int(minute):02d}"
               "（停电结束前 2 小时）")
        set_system_datetime(dev, r, target, int(hour), int(minute))
        r.ok(f"设备时间 {dev.shell('date').strip()}")

        off_at, wake_at = screen_off_and_unlock(dev, r, int(off_sec), unlock_retries)
        result["screen_off_at"] = off_at
        result["screen_on_at"] = wake_at

        hit = wait_card(dev, r, int(wait_sec),
                        RESTORE_HINTS_ZH, RESTORE_HINTS_EN, RESTORE_HINTS_AR,
                        "停电恢复卡片")
        result["card_text"] = hit
    finally:
        reset_battery(dev, r)

    r.step("确认智慧建议卡片")
    ensure_home_before_confirm(dev, r)
    ok = bool(hit) or r.confirm()
    if not ok:
        raise UiError(
            f"解锁后等了 {int(wait_sec)} 秒，既没在桌面看到电力恢复卡片，"
            "日志里也没有 tvTitle=电力恢复时间 的渲染记录。"
            "常见原因：①电量 mock 没清掉，省电卡抢了同一个 conflict_group；"
            f"②{KPLC_AREA} / {target.isoformat()} 当天没有停电公告；"
            "③恢复卡需要落在公告结束前 2 小时内，时间点不对就不会触发。")
    r.ok(f"已确认停电恢复卡片：{hit or '人工确认'}")

    dev.stayon(False)
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S %Z'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (
        f"完成。时区 {TIMEZONE}、国家 {COUNTRY}，KPLC 区域 {KPLC_AREA}；"
        f"清掉电池 mock 后查过 KPLC 接口确认当天有停电公告，"
        f"把时间设到 {target.isoformat()} {int(hour):02d}:{int(minute):02d}"
        f"（结束前 2 小时），息屏 {int(off_sec)} 秒再亮屏上滑解锁，"
        "桌面出现电力恢复时间的卡片。")
    return result


if __name__ == "__main__":
    import sys

    off = int(sys.argv[1]) if len(sys.argv) > 1 else OFF_SECONDS
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else WAIT_CARD_SEC
    try:
        out = run(emit=_cli_emit, off_sec=off, wait_sec=wait)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

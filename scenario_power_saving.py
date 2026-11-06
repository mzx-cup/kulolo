"""停电省电建议卡片（KPLC Power Outage Saving）触发场景。

对应 atomicbrain 规则 **64380**（`AITIPS_Power_outage_saving`，intent 与预警卡相同
`transsion.intent.aitips.AITIPS_Power_outage`，卡片由 `businessData.tvTitle` 区分）：

  33  TimeSlotAbility        时段触发（0 = 到点触发）
  29  CountryAbility         国家必须 CONTAIN "KE"
  51  ChargingAbility         **不在充电**（values ["false"]）
  31  BatteryAbility          电量 ≤ 49%

同族 `conflict_group: kplc_power_outage_active`（三张停电卡互斥，先到的把后来的
DROP 掉），所以触发恢复卡前必须先 `dumpsys battery reset` 清掉省电卡的电池 mock，
否则省电卡会一直先出、恢复卡被 `blocked by conflict_group, scenario=RESTORATION`。

流程（用户 m08836 指定）：
  保网络 → 装 TransAtomicBrain → 时区内罗毕 + 国家 KE → 系统时间 09-18 12:29 →
  pm clear atomiccore + atomicbrain → 打开 debug 页滚到底 →
  `dumpsys battery set level 30` / `set status 1` → 点「Mock 电量=30」→
  点「查询 KPLC API」→ 时间调到 12:30 → 息屏 10 秒 → 亮屏上滑解锁 → 出卡

**两个真机踩出来的前提**：
1. **先设系统时间、再重启 debug App**。KPLC 调试区的日期框默认值取的是「当天」，
   先设好时间再 `am force-stop` + `am start`，日期框就自动是 2026-09-18，
   **完全不用手动输入** —— 键盘弹出后整个 KPLC 区块会滚出屏幕，坐标点击极不可靠。
2. **`dumpsys battery set` 是持久的**（会一直覆盖真实电量直到 `dumpsys battery reset`），
   跑完必须 reset，否则后面所有跟电量相关的判断都被污染。
"""
from __future__ import annotations

import datetime as _dt
import re
import time

from phone_ctl import KEY_HOME, KEY_WAKEUP, Device, UiError

from scenario_atomic_mock import (
    ATOMIC_ACTIVITY,
    ATOMIC_PACKAGE,
    ensure_installed,
)
from scenario_birthday import (
    Runner,
    _cli_emit,
    _unlock_with_retries,
    _wait_screen_on,
    ensure_home_before_confirm,
    set_system_datetime,
)
from scenario_power_outage import (
    ATOMIC_CORE_PKG,
    COUNTRY,
    TIMEZONE,
    _clear_atomic,
    _ensure_network,
    _set_timezone,
)

# KPLC 调试区（TransAtomicBrain 17.11.00.104 起的 debug 页）
RID_KPLC_AREA = "com.transsion.atomicbrain:id/et_kplc_area"
RID_KPLC_DATE = "com.transsion.atomicbrain:id/et_kplc_date"
RID_KPLC_QUERY = "com.transsion.atomicbrain:id/btn_kplc_query"
RID_KPLC_RESULT = "com.transsion.atomicbrain:id/text_kplc_result"
RID_KPLC_LOG = "com.transsion.atomicbrain:id/text_kplc_log"
RID_MOCK_BATTERY = "com.transsion.atomicbrain:id/btn_mock_battery_30"

# 默认区域：MATASIA（内罗毕）。2026-09-18 该区有一条
# area="MATASIA, OLOIKA, NKOROI" / 05:30~14:00 UTC(=08:30~17:00 EAT) 的公告，
# 12:30 落在停电区间内 → 省电卡；16:30 落在结束前 2 小时 → 恢复卡。
KPLC_AREA = "MATASIA"
DEFAULT_YEAR = 2026
DEFAULT_MONTH = 9
DEFAULT_DAY = 18
# 先把时间设到 12:29（debug 页日期框会取当天），mock 完再拨到 12:30 触发
SETUP_HOUR = 12
SETUP_MIN = 29
TRIGGER_HOUR = 12
TRIGGER_MIN = 30
OFF_SECONDS = 10
WAIT_CARD_SEC = 90

# 电池 mock：规则 31 要求 ≤49%，用户指定 30
MOCK_LEVEL = 30

# 卡片文案（中/英/阿）—— 注意「省电」不能和「电力恢复」混
SAVING_HINTS_ZH = ("省电建议", "开启省电模式", "省电模式", "建议您及时开启省电")
SAVING_HINTS_EN = ("power saving", "battery saver", "save power", "power-saving",
                   "enable power saving")
SAVING_HINTS_AR = ("توفير الطاقة", "توفير البطارية", "وضع توفير", "توفير الكهرباء", "توفير")
# logcat 里的 tvTitle 会被日志系统截断成 `توفير ال***`，所以匹配时要用短词
SAVING_LOG_HINTS_AR = ("توفير",)


def _card_texts(nodes) -> list[str]:
    out = []
    for n in nodes:
        for value in (n.text, n.desc):
            value = (value or "").strip()
            if value:
                out.append(value)
    return out


def match_card(nodes, hints_zh, hints_en, hints_ar) -> str | None:
    """在控件树里按三种语言的文案找卡片，返回命中的那一条文本。"""
    for text in _card_texts(nodes):
        low = text.lower()
        for hint in hints_zh:
            if hint in text:
                return text
        for hint in hints_en:
            if hint in low:
                return text
        for hint in hints_ar:
            if hint in text:
                return text
    return None


def card_dispatched(dev: Device, titles) -> str | None:
    """卡片不一定在桌面第一屏（智慧建议是轮播），退一步查 logcat 是否已渲染。

    `TpkServiceCardProvider ... cardInfo: CardInfo(...businessData={"data":{"tvTitle":"省电建议"...`
    这一行同时带着卡片标题，是「已经生成出这张卡」最直接的证据。

    **titles 要传多语言**：卡片标题会跟随系统语言（英语 `Save Power` /
    阿拉伯语 `توفير الطاقة`），只比中文会漏判。
    """
    if isinstance(titles, str):
        titles = (titles,)
    out = dev.shell("logcat -d -s TpkServiceCardProvider:D TACS-DynamicManager:D")
    if not out.strip():
        return None
    wanted = [t.lower() for t in titles if t]
    for line in out.splitlines():
        if "tvTitle" not in line:
            continue
        low = line.lower()
        if any(t in low for t in wanted):
            return line.strip()[:180]
    return None


def open_debug_page(dev: Device, r: Runner) -> None:
    """先设好时间再 force-stop + start，让 KPLC 日期框默认成目标日。

    开跑前必须先唤醒 + 解锁：`am start` 在锁屏/通知栏状态下会把界面推到
    NotificationShade 后面，`wait_focus("atomicbrain")` 直接超时（实测）。
    """
    r.step("重启 TransAtomicBrain 调试页（让 KPLC 日期默认成今天）")
    # 锁屏 / 亮着通知栏时 am start 起不来，先唤醒解锁
    if not dev.screen_on():
        dev.key(KEY_WAKEUP)
        _wait_screen_on(dev, True, timeout=4.0)
    if dev.locked():
        _unlock_with_retries(dev, r, 3)
        time.sleep(0.6)
    dev.shell(f"am force-stop {ATOMIC_PACKAGE}")
    time.sleep(1.6)
    out = dev.shell(f"am start -n {ATOMIC_ACTIVITY}")
    if "Error" in out or "Exception" in out:
        raise UiError(f"启动 {ATOMIC_ACTIVITY} 失败：{out.strip()[:300]}")
    try:
        dev.wait_focus("atomicbrain", timeout=20.0)
    except UiError:
        # 偶尔焦点还留在 launcher / 通知栏，再解锁一次重试
        r.log(f"启动后焦点还在 {dev.focus()!r}，解锁后重试一次")
        _unlock_with_retries(dev, r, 3)
        dev.shell(f"am start -n {ATOMIC_ACTIVITY}")
        dev.wait_focus("atomicbrain", timeout=15.0)
    time.sleep(1.2)
    r.ok(dev.focus())


def scroll_to_kplc(dev: Device, r: Runner, max_rounds: int = 10) -> None:
    """滚到底部的 KPLC 停电卡片 debug 区，直到查询按钮出现在屏内。"""
    r.step("滚到调试页底部的「KPLC 停电卡片 debug」区域")
    w, h = dev.screen_size()
    for i in range(1, max_rounds + 1):
        btn = dev.find_opt(rid=RID_KPLC_QUERY)
        if btn is not None and 0 < btn.center[1] < h - 40:
            r.ok(f"已滚到 KPLC 区（第 {i} 次后按钮在 {btn.center}）")
            return
        dev.swipe(w // 2, int(h * 0.82), w // 2, int(h * 0.30), 260)
        time.sleep(0.45)
    raise UiError("滑了 10 次仍没看到「查询 KPLC API」按钮，调试页结构可能变了。")


def check_kplc_fields(dev: Device, r: Runner, target: _dt.date) -> None:
    """确认区域/日期已经是期望值（日期靠「先设系统时间」自然带出来）。"""
    r.step("确认 KPLC 调试区的区域与日期")
    area = dev.find_opt(rid=RID_KPLC_AREA)
    date_node = dev.find_opt(rid=RID_KPLC_DATE)
    area_text = (area.text if area else "").strip()
    date_text = (date_node.text if date_node else "").strip()
    r.log(f"区域={area_text!r} 日期={date_text!r}")
    if area_text.upper() != KPLC_AREA.upper():
        raise UiError(
            f"KPLC 区域是 {area_text!r}，期望 {KPLC_AREA!r}。"
            "这个输入框在有键盘时会滚出屏幕、坐标点击不可靠，"
            "请手动确认调试页里 area 是 MATASIA 后重试。")
    if date_text != target.isoformat():
        raise UiError(
            f"KPLC 日期是 {date_text!r}，期望 {target.isoformat()!r}。"
            "日期框的默认值取「设备当天」，所以必须**先设系统时间再重启 App**；"
            f"当前设备时间 {dev.shell('date').strip()}")
    r.ok(f"区域 {KPLC_AREA} / 日期 {date_text}")


def mock_battery(dev: Device, r: Runner, level: int = MOCK_LEVEL) -> None:
    """把电池 mock 成指定电量 + 放电中，再点调试页的「Mock 电量=30」。

    两步都要做：`dumpsys battery set` 改的是系统 BatteryManager 的读数（规则 31/51
    读的就是它），调试页的按钮额外注入一条 BATTERY_LEVEL 事件推原子化立刻重算。
    """
    r.step(f"把电量 mock 成 {level}% 且处于放电中")
    dev.shell(f"dumpsys battery set level {level}")
    dev.shell("dumpsys battery set status 1")          # 1 = DISCHARGING
    # set status 1 不一定能把 usb powered 关掉，一起改成 false 才会让规则 51 成立
    dev.shell("dumpsys battery unplug")
    time.sleep(0.8)
    raw = dev.shell("dumpsys battery")
    level_now = re.search(r"level:\s*(\d+)", raw)
    status_now = re.search(r"status:\s*(\d+)", raw)
    r.log(f"dumpsys battery → level={level_now.group(1) if level_now else '?'} "
          f"status={status_now.group(1) if status_now else '?'}")
    if not level_now or int(level_now.group(1)) != level:
        raise UiError(f"电量没 mock 成功，当前 {level_now.group(1) if level_now else '未知'}%")

    r.step(f"点调试页的「Mock 电量={level}」按钮")
    btn = dev.wait_node(rid=RID_MOCK_BATTERY, timeout=10.0)
    dev.tap_node(btn, 0.8)
    time.sleep(2.0)
    log_node = dev.find_opt(rid=RID_KPLC_LOG)
    tail = (log_node.text if log_node else "") or ""
    if "Mock BATTERY_LEVEL" in tail:
        r.ok("调试页已确认注入 BATTERY_LEVEL")
    else:
        r.log(f"调试页日志里没看到 Mock BATTERY_LEVEL，继续（tail={tail[-160:]!r}）")


def reset_battery(dev: Device, r: Runner | None = None) -> None:
    """还原电池读数 —— 不还原会污染后续所有跟电量相关的卡片。"""
    try:
        dev.shell("dumpsys battery reset")
        time.sleep(0.5)
        raw = dev.shell("dumpsys battery")
        level_now = re.search(r"level:\s*(\d+)", raw)
        if r:
            r.log(f"已还原电池读数（level={level_now.group(1) if level_now else '?'}）")
    except Exception as exc:                       # 收尾失败不影响结果
        if r:
            r.log(f"还原电池读数时出错（不影响卡片）：{exc}")


def query_kplc(dev: Device, r: Runner, target: _dt.date) -> str:
    """点「查询 KPLC API」并等结果；结果里必须有该地区的停电公告。"""
    r.step("点「查询 KPLC API」")
    btn = dev.wait_node(rid=RID_KPLC_QUERY, timeout=10.0)
    dev.tap_node(btn, 0.5)
    last = ""
    for i in range(1, 21):
        time.sleep(1.0)
        node = dev.find_opt(rid=RID_KPLC_RESULT)
        last = ((node.text if node else "") or "").strip()
        if not last:
            continue
        if "未查询到" in last or "失败" in last:
            raise UiError(
                f"KPLC 接口在 {KPLC_AREA} / {target.isoformat()} 上没有停电公告：{last[:300]}。"
                "这张卡要靠真实公告里的停电时段来判断「正在停电」，"
                "请换一个有公告的日期（调试页「今天/明天」按钮或改系统日期）。")
        r.log(f"第 {i} 秒返回：{last[:240]}")
        return last
    raise UiError(f"点了「查询 KPLC API」后 20 秒仍没有结果，最后一条：{last[:200]!r}")


def screen_off_and_unlock(dev: Device, r: Runner, off_sec: int,
                          unlock_retries: int = 3) -> tuple[str, str]:
    """息屏 off_sec 秒再亮屏上滑解锁 —— 规则 33（时段触发）就靠这次亮屏唤醒。"""
    r.step(f"息屏 {off_sec} 秒再亮屏上滑解锁")
    dev.shell("input keyevent 111")                # 收键盘
    time.sleep(0.4)
    dev.key(KEY_HOME)
    time.sleep(0.8)
    dev.stayon(False)
    dev.key(223)                                   # KEYCODE_SLEEP
    _wait_screen_on(dev, False, timeout=4.0)
    off_at = dev.shell("date '+%H:%M:%S'").strip()
    r.log(f"已息屏，当前 {off_at}")
    left = max(0, int(off_sec))
    while left > 0:
        r.check()
        step = min(5, left)
        r.tick(left)
        time.sleep(step)
        left -= step
    dev.shell("logcat -c")                         # 别被上一轮的派发日志骗到
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=5.0)
    dev.stayon(True)
    time.sleep(1.2)
    _unlock_with_retries(dev, r, unlock_retries)
    ensure_home_before_confirm(dev, r)
    wake_at = dev.shell("date '+%H:%M:%S'").strip()
    r.shot("解锁后桌面")
    return off_at, wake_at


def wait_card(dev: Device, r: Runner, wait_sec: int,
              hints_zh, hints_en, hints_ar, title: str) -> str | None:
    """解锁后等卡片；控件树看不到就退一步查 logcat 里是否已渲染。

    智慧建议是轮播的，卡片不一定在第一屏 —— 英语/阿拉伯语下经常被别的卡占位，
    这时 logcat 里 `TpkServiceCardProvider ... tvTitle=...` 才是最可靠的证据。
    """
    r.step(f"等待{title}出现")
    start = time.time()
    while time.time() - start < wait_sec:
        r.check()
        elapsed = int(time.time() - start)
        try:
            nodes = dev.dump()
        except UiError:
            time.sleep(2.0)
            continue
        found = match_card(nodes, hints_zh, hints_en, hints_ar)
        if found:
            r.log(f"第 {elapsed} 秒在桌面命中：「{found}」，控件 {len(nodes)} 个")
            r.shot(title)
            return found
        if elapsed >= 5:
            dispatched = card_dispatched(dev, (*hints_zh, *hints_en, *hints_ar))
            if dispatched:
                r.log(f"第 {elapsed} 秒卡片已渲染（不在第一屏）：{dispatched}")
                r.shot(title)
                return "已派发到智慧建议轮播（未在第一屏）"
        if elapsed and elapsed % 10 == 0:
            r.log(f"第 {elapsed} 秒还没有{title}（控件 {len(nodes)} 个）")
        time.sleep(2.0)
    r.shot(f"{title}（超时）")
    return None


def run(dev: Device | None = None, emit=None, *,
        year: int = DEFAULT_YEAR, month: int = DEFAULT_MONTH, day: int = DEFAULT_DAY,
        hour: int = TRIGGER_HOUR, minute: int = TRIGGER_MIN,
        off_sec: int = OFF_SECONDS, wait_sec: int = WAIT_CARD_SEC,
        battery: int = MOCK_LEVEL, unlock_retries: int = 3,
        control: dict | None = None, confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    if not (10 <= off_sec <= 300):
        raise UiError("off_sec（息屏等待）必须在 10~300 秒之间")
    if not (20 <= wait_sec <= 240):
        raise UiError("wait_sec（等卡片）必须在 20~240 秒之间")
    if not (1 <= battery <= 100):
        raise UiError("battery（mock 电量）必须在 1~100 之间")
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
        "battery": int(battery),
        "off_sec": int(off_sec),
        "wait_sec": int(wait_sec),
        "timezone": TIMEZONE,
        "country": COUNTRY,
    }

    ensure_installed(dev, r)
    _ensure_network(dev, r)
    _set_timezone(dev, r)

    # 先解锁回桌面，否则 pm clear 之后的第一次解锁会被这次用掉
    r.step("先解锁回桌面")
    dev.stayon(True)
    dev.key(KEY_WAKEUP)
    time.sleep(0.8)
    if dev.locked():
        _unlock_with_retries(dev, r, unlock_retries)
    dev.key(KEY_HOME)
    time.sleep(0.8)
    r.ok("已在桌面")

    # 日期框默认取「设备当天」，所以时间必须比 App 启动更早设好
    r.step(f"把系统时间调到 {target.isoformat()} "
           f"{SETUP_HOUR:02d}:{SETUP_MIN:02d}（比触发时间早一分钟）")
    set_system_datetime(dev, r, target, SETUP_HOUR, SETUP_MIN)
    r.ok(f"设备时间 {dev.shell('date').strip()}")

    _clear_atomic(dev, r)

    hit = None
    try:
        open_debug_page(dev, r)
        scroll_to_kplc(dev, r)
        check_kplc_fields(dev, r, target)
        mock_battery(dev, r, int(battery))
        result["kplc_result"] = query_kplc(dev, r, target)[:400]

        r.step(f"把系统时间调到 {target.isoformat()} {int(hour):02d}:{int(minute):02d}")
        set_system_datetime(dev, r, target, int(hour), int(minute))
        r.ok(f"设备时间 {dev.shell('date').strip()}")

        off_at, wake_at = screen_off_and_unlock(dev, r, int(off_sec), unlock_retries)
        result["screen_off_at"] = off_at
        result["screen_on_at"] = wake_at

        hit = wait_card(dev, r, int(wait_sec),
                        SAVING_HINTS_ZH, SAVING_HINTS_EN, SAVING_HINTS_AR,
                        "停电省电建议卡片")
        result["card_text"] = hit
    finally:
        # 电池 mock 不还原会污染后续所有跟电量相关的卡片
        reset_battery(dev, r)

    r.step("确认智慧建议卡片")
    ensure_home_before_confirm(dev, r)
    ok = bool(hit) or r.confirm()
    if not ok:
        raise UiError(
            f"解锁后等了 {int(wait_sec)} 秒，既没在桌面看到省电建议卡片，"
            "日志里也没有 tvTitle=省电建议 的渲染记录。"
            "常见原因：①电量没低于 49% 或设备被判定在充电（规则 51/31）；"
            f"②{KPLC_AREA} / {target.isoformat()} 当天没有停电公告；"
            "③当天的停电卡额度已经被预警卡用掉（三张卡同属 conflict_group"
            " kplc_power_outage_active，先到的会把后来的 DROP）。")
    r.ok(f"已确认停电省电建议卡片：{hit or '人工确认'}")

    dev.stayon(False)
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S %Z'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (
        f"完成。时区 {TIMEZONE}、国家 {COUNTRY}，KPLC 区域 {KPLC_AREA}；"
        f"电量 mock 成 {int(battery)}% 且放电中，查过 KPLC 接口确认当天有停电公告后，"
        f"把时间设到 {target.isoformat()} {int(hour):02d}:{int(minute):02d}，"
        f"息屏 {int(off_sec)} 秒再亮屏上滑解锁，桌面出现停电省电建议卡片。")
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


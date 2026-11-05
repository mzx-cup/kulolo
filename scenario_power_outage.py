"""停电预警卡（KPLC Power Outage Warning）触发场景。

对应 atomicbrain 规则 **64379**（`AITIPS_Power_outage_warning`，intent
`transsion.intent.aitips.AITIPS_Power_outage`），五个 ability：

  1  UnlockAbility          解锁触发
  2  TimeAbility            时间窗 08:00~23:59
  36 FirstUnlockAfterAbility 当天 8 点后首次解锁
  29 CountryAbility         国家必须 CONTAIN "KE"
  22 DayCountAbility        当天最多 1 次

**关键卡点：常住区（County Resident）**。卡片不是靠 GPS 定位出卡的，
`BlackoutIntent` 会向 `TceService.queryLocationSemantic(power_outage_alert)`
要一个「常住县城」，拿到 `KE-30/Nairobi` 才去 KPLC 接口按 `keywords=[Nairobi, KE-30]`
匹配次日停电公告。默认情况下国内测试机返回的是 `CN-CQ/重庆`，
于是请求 `area=重庆` → `no matched outage` → 永不出卡。

所以本场景必须先「注入常住区证据」：向 `com.transsion.tranradionet/.tce.TceService`
发调试 action（受 signature|privileged 的 START_TCE_SERVICE 保护，**必须 adb root**）：

  SET_COUNTRY_OVERRIDE country=ke
  RESET_COUNTY         scope=all
  INJECT_COUNTY_LOC    lat=-1.286389 lng=36.817223 time_ms=<EAT 23:00 epoch>  ×5 夜
  QUERY_COUNTY         business_id=power_outage_alert   ← 断言 recommend=KE-30

这套动作等价于共享盘上的 `设置常住区-0727.bat`，这里用纯 adb 实现，不依赖 PowerShell。

流程（用户 m08205 指定）：
  root 校验 → 保网络 → 时区内罗毕 → 注入常住区 → pm clear 两个包 →
  时间设到目标日 11:49 → 息屏 60 秒 → 亮屏上滑解锁 → 等卡片出现

注意执行顺序：`pm clear com.transsion.atomicbrain` 会清掉「当天已触发次数」和
「今天是否已首次解锁」两个标记，所以 **pm clear 之后的那一次解锁必须留给 11:49**，
中间不能再自己去解锁亮屏。
"""
from __future__ import annotations

import datetime as _dt
import re
import time
from zoneinfo import ZoneInfo

from phone_ctl import (
    KEY_HOME,
    KEY_WAKEUP,
    Device,
    UiError,
)

from scenario_birthday import (
    Runner,
    _cli_emit,
    _unlock_with_retries,
    _wait_screen_on,
    ensure_home_before_confirm,
    set_system_datetime,
)

TCE_COMPONENT = "com.transsion.tranradionet/.tce.TceService"
TCE_ACTION = "com.transsion.tranradionet.tce.action"
TCE_PKG = "com.transsion.tranradionet"

ATOMIC_PKG = "com.transsion.atomicbrain"
ATOMIC_CORE_PKG = "com.transsion.atomiccore"

TIMEZONE = "Africa/Nairobi"
COUNTRY = "KE"
BUSINESS_ID = "power_outage_alert"

# Nairobi CBD —— 与官方 设置常住区-0727.bat 一致
NAIROBI_LAT = -1.286389
NAIROBI_LNG = 36.817223
NIGHT_HOUR = 23
NIGHT_COUNT = 5

# 默认触发日：2026-10-15，次日 2026-10-16 有一条
# region="NAIROBI REGION" / area="PART OF PANGANI" / 06:00~14:00 UTC(=09:00~17:00 EAT)
# 的历史公告，正好能匹配上，卡片会显示「明天 / 09:00-17:00」。
DEFAULT_YEAR = 2026
DEFAULT_MONTH = 10
DEFAULT_DAY = 15
TRIGGER_HOUR = 11
TRIGGER_MIN = 49
OFF_SECONDS = 60

# 卡片文案（中/英/阿）—— 任一条命中即认为出卡
CARD_HINTS_ZH = ("停电预警", "请提前做好电力储备", "停电", "电力储备")
CARD_HINTS_EN = ("power outage", "power outage warning", "outage", "kplc",
                 "power supply", "electricity")
CARD_HINTS_AR = ("انقطاع التيار", "انقطاع الكهرباء", "الكهرباء", "الطاقة")

WAIT_CARD_SEC = 90


def _naive_epoch_ms(y: int, m: int, d: int, hour: int) -> int:
    """EAT（UTC+3，无夏令时）某天某点的 epoch 毫秒。"""
    tz = ZoneInfo(TIMEZONE)
    moment = _dt.datetime(y, m, d, hour, 0, 0, tzinfo=tz)
    return int(moment.timestamp() * 1000)


def _card_visible(nodes) -> str | None:
    """在控件树里找停电卡文案，返回命中的文本。"""
    for n in nodes:
        text = (n.text or "").strip()
        desc = (n.desc or "").strip()
        if not text and not desc:
            continue
        low = text.lower()
        low_desc = desc.lower()
        for hint in CARD_HINTS_ZH:
            if hint in text:
                return text
        for hint in CARD_HINTS_EN:
            if hint in low or hint in low_desc:
                return text or desc
        for hint in CARD_HINTS_AR:
            if hint in text:
                return text
    return None


def _card_dispatched(dev: Device) -> str | None:
    """卡片不一定在这一屏：桌面智慧建议是轮播，常被「早上好」「Premier League」等
    更高优先级卡片占到第一屏。所以除了看控件树，还要看卡片有没有被真正派发出去。

    日志特征（按出现先后）：
      TAB.BlackoutIntent: matchWarning 命中 → 说明 KPLC 有匹配的停电公告
      TACS-ExternalProvider: handleGetTpkPackage, serviceId: 64379 → 原子化把 TPK 下发
      TpkServiceCardProvider: displayMap: [...AITIPS_Power_outage...] → 进了轮播队列
      SuggestionServiceCard: ... AITIPS_Power_outage ... onShow → 已经展示过
    """
    out = dev.shell("logcat -d -s TAB.BlackoutIntent:D TpkServiceCardProvider:D "
                    "SuggestionServiceCard:I TACS-ExternalProvider:I")
    if not out.strip():
        return None
    hints = (
        "AITIPS_Power_outage",
        "onShow ServiceInfo(transsion.intent.aitips.AITIPS_Power_outage",
        "handleGetTpkPackage, serviceId: 64379",
        "displayMap: [0-transsion.intent.aitips.AITIPS_Power_outage",
    )
    for hint in hints:
        if hint in out:
            for line in out.splitlines():
                if hint in line:
                    return line.strip()[:180]
    return None


def _check_root(dev: Device, r: Runner) -> None:
    """TceService 受 START_TCE_SERVICE 保护，只有 root adbd 能发。"""
    r.step("检查设备是否 root")
    out = dev.shell("id").strip()
    if "uid=0(root)" not in out and "uid=0" not in out:
        raise UiError(
            "这张卡需要 root 版设备：向 TceService 注入常住区要求 START_TCE_SERVICE "
            f"（signature|privileged），普通 adb shell 会被拒绝。当前 `id` = {out[:120]!r}。"
            "请换 userdebug/eng 版本机型，或先执行 adb root。")
    r.ok("uid=0(root)")


def _ensure_network(dev: Device, r: Runner) -> None:
    r.step("确认设备联网（全程需要联网）")
    dev.shell("svc wifi enable")
    dev.shell("svc data enable")
    online = False
    for _ in range(12):
        r.check()
        out = dev.shell("ping -c 1 -W 1 8.8.8.8")
        if "1 received" in out or "1 packets received" in out:
            online = True
            break
        time.sleep(1)
    if not online:
        raise UiError("设备没有网络，停电卡要向 KPLC 接口拉停电公告，必须先联网。")
    r.ok("联网正常")


def _set_timezone(dev: Device, r: Runner) -> None:
    r.step(f"时区改到内罗毕（{TIMEZONE}）、国家改到 {COUNTRY}")
    dev.shell("settings put global auto_time_zone 0")
    dev.shell(f"setprop persist.tr_oobe.country {COUNTRY}")
    dev.shell(f"setprop persist.sys.timezone {TIMEZONE}")
    time.sleep(0.6)
    tz = dev.shell("getprop persist.sys.timezone").strip()
    country = dev.shell("getprop persist.tr_oobe.country").strip()
    if tz != TIMEZONE:
        raise UiError(f"persist.sys.timezone 写入后读回是 {tz!r}，期望 {TIMEZONE!r}")
    r.ok(f"timezone={tz} country={country}")


def _tce(dev: Device, action: str, *extras: str) -> str:
    """向 TceService 发一条调试 action（需要 root，否则会被 START_TCE_SERVICE 挡住）。"""
    cmd = ["am", "startservice", "-n", TCE_COMPONENT, "-a", f"{TCE_ACTION}.{action}"]
    cmd.extend(extras)
    out = dev.shell(" ".join(cmd)).strip()
    if "START_TCE_SERVICE" in out:
        raise UiError(
            f"发 {action} 被 START_TCE_SERVICE 权限拒绝，adb 没有 root。原始输出：{out[:300]}")
    return out


def _inject_county(dev: Device, r: Runner, target: _dt.date) -> None:
    """灌 5 个内罗毕夜间证据，让 TceService 把常住区判成 KE-30/Nairobi。"""
    r.step("注入内罗毕常住区证据（等价于 设置常住区-0727.bat）")

    dev.shell(f"pm grant {TCE_PKG} android.permission.ACCESS_FINE_LOCATION")
    dev.shell(f"pm grant {TCE_PKG} android.permission.ACCESS_COARSE_LOCATION")
    dev.shell("settings put secure location_mode 3")
    dev.shell("cmd location set-location-enabled true")
    dev.shell("setprop log.tag.TceCountyResidentMgr DEBUG")

    _tce(dev, "SET_COUNTRY_OVERRIDE", "--es", "country", COUNTRY.lower())
    time.sleep(1.5)
    _tce(dev, "RESET_COUNTY", "--es", "scope", "all")
    time.sleep(1.5)
    r.log(f"已清空历史证据，开始注入 {NIGHT_COUNT} 个夜间点位")

    # 目标日之前 1~5 天的 23:00 EAT（已完成的夜晚，不用未来时间）
    injected = 0
    for ago in range(NIGHT_COUNT, 0, -1):
        night = target - _dt.timedelta(days=ago)
        ms = _naive_epoch_ms(night.year, night.month, night.day, NIGHT_HOUR)
        _tce(dev, "INJECT_COUNTY_LOC",
             "--ef", "lat", str(NAIROBI_LAT),
             "--ef", "lng", str(NAIROBI_LNG),
             "--el", "time_ms", str(ms))
        injected += 1
        r.log(f"[{injected}/{NIGHT_COUNT}] {night.isoformat()} 23:00 EAT "
              f"({NAIROBI_LAT}, {NAIROBI_LNG})")
        time.sleep(3)

    r.log("等待地理编码回填（8 秒）…")
    time.sleep(8)

    # DUMP 确认证据条数
    dev.shell("logcat -c")
    _tce(dev, "DUMP_COUNTY")
    time.sleep(3)
    dump_log = dev.shell("logcat -d -s TceCountyResidentMgr")
    m = re.search(r"DUMP: evidence dates=(\d+)", dump_log)
    nights = int(m.group(1)) if m else 0
    r.log(f"证据夜数 evidenceDates={nights}")
    if nights < NIGHT_COUNT:
        r.log(f"提示：只存下 {nights} 夜（期望 {NIGHT_COUNT}），"
              "可能是地理编码限流；继续尝试查询常住区")

    # QUERY 断言常住区。
    # 注意日志格式随系统版本不同：有的打 "QUERY_COUNTY result: TceLocationSemanticResult{...}"，
    # 有的只打 "sendResult: TceLocationSemanticResult{...}"（原子化自己查询时也会打），
    # 所以两种都认，只要拿到一条 KE 的语义结果就算过。
    dev.shell("logcat -c")
    _tce(dev, "QUERY_COUNTY", "--es", "business_id", BUSINESS_ID)
    time.sleep(3)
    query_log = dev.shell("logcat -d -s TceCountyResidentMgr")
    line = ""
    for ln in query_log.splitlines():
        if "TceLocationSemanticResult{" in ln and "countryCode=KE" in ln:
            line = ln
            break
    if not line:
        for ln in query_log.splitlines():
            if "QUERY_COUNTY result" in ln or "TceLocationSemanticResult{" in ln:
                line = ln
                break
    if not line:
        raise UiError(
            "查询常住区没有任何结果，TceService 可能没起来。"
            f"logcat 尾部：{query_log[-400:]!r}")
    r.log(line.strip()[:300])
    if "countryCode=KE" not in line:
        raise UiError(
            "常住区没有变成肯尼亚，停电卡会拿重庆去查 KPLC 公告、永远匹配不到。"
            f"查询结果：{line.strip()[:300]}")
    if "RESIDENT" not in line and "KE-30" not in line:
        raise UiError(
            "常住区还不是 RESIDENT/KE-30，只有 CURRENT 结果不足以出卡。"
            f"查询结果：{line.strip()[:300]}")
    r.ok("常住区 = KE-30 / Nairobi")


def _clear_atomic(dev: Device, r: Runner) -> None:
    """清原子化：重置「当天触发次数」和「今天首次解锁」两个标记。"""
    r.step("清理原子化模拟器（atomiccore + atomicbrain）")
    for pkg in (ATOMIC_CORE_PKG, ATOMIC_PKG):
        out = dev.shell(f"pm clear {pkg}").strip()
        if "Success" not in out:
            raise UiError(f"pm clear {pkg} 失败：{out[:300]}")
        r.log(f"pm clear {pkg} → Success")
    r.ok("两个包都已清空")
    time.sleep(1.5)


def _screen_off_wait(dev: Device, r: Runner, off_seconds: int) -> tuple[str, str]:
    """息屏等待；期间不碰手机，让 11:49 的那一次解锁成为当天首次解锁。"""
    r.step(f"息屏等待 {off_seconds} 秒")
    dev.key(KEY_HOME)
    time.sleep(0.5)
    dev.stayon(False)
    time.sleep(0.3)
    dev.key(223)                          # KEYCODE_SLEEP
    _wait_screen_on(dev, False, timeout=3.0)
    off_at = dev.shell("date '+%H:%M:%S'").strip()
    r.log(f"已息屏，当前 {off_at}")

    left = off_seconds
    while left > 0:
        r.check()
        step = min(5, left)
        r.tick(left)
        time.sleep(step)
        left -= step
    wake_at = dev.shell("date '+%H:%M:%S'").strip()
    r.log(f"等待结束，准备亮屏，当前 {wake_at}")
    return off_at, wake_at


def _wake_and_unlock(dev: Device, r: Runner, unlock_retries: int = 3) -> None:
    """亮屏 + 上滑解锁 —— 这一步就是规则里的「当天 8 点后首次解锁」。"""
    r.step("亮屏并上滑解锁")
    # 清一次日志，后面判断「卡片有没有派发」时才不会被上一次的日志骗到
    dev.shell("logcat -c")
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=4.0)
    time.sleep(1.5)
    _unlock_with_retries(dev, r, unlock_retries)
    dev.stayon(True)
    time.sleep(1.0)
    ensure_home_before_confirm(dev, r)
    r.shot("解锁后桌面")


def _wait_card(dev: Device, r: Runner, wait_sec: int) -> str | None:
    """解锁后等卡片渲染。

    实测中文桌面 25 秒就换卡；英语/阿拉伯语下这张卡的优先级不如
    「早上好」「Premier League」，可能一直不在第一屏 —— 所以除了看
    控件树，还查 logcat 里卡片是否已经派发（那样也算触发成功）。
    """
    r.step("等待停电预警卡片出现")
    start = time.time()
    hit = None
    while time.time() - start < wait_sec:
        r.check()
        elapsed = int(time.time() - start)
        try:
            nodes = dev.dump()
        except UiError:
            time.sleep(2.0)
            continue
        found = _card_visible(nodes)
        if found:
            hit = found
            r.log(f"第 {elapsed} 秒在桌面命中：「{found}」，控件 {len(nodes)} 个")
            break
        if elapsed >= 12:
            dispatched = _card_dispatched(dev)
            if dispatched:
                hit = "已派发到智慧建议轮播（未在第一屏）"
                r.log(f"第 {elapsed} 秒卡片已派发：{dispatched}")
                break
        if elapsed and elapsed % 10 == 0:
            r.log(f"第 {elapsed} 秒还没有停电卡（控件 {len(nodes)} 个）")
        time.sleep(2.0)
    r.shot("停电预警卡片")
    return hit


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
    if not (0 <= hour <= 23 and 8 <= hour <= 23):
        raise UiError("触发小时必须在 8~23 之间（规则 64379 的时间窗是 08:00~23:59）")

    try:
        target = _dt.date(int(year), int(month), int(day))
    except ValueError as exc:
        raise UiError(f"触发日期不合法：{year}-{month}-{day}（{exc}）") from exc

    result = {
        "target_date": target.isoformat(),
        "trigger_at": f"{int(hour):02d}:{int(minute):02d}",
        "off_sec": int(off_sec),
        "wait_sec": int(wait_sec),
        "timezone": TIMEZONE,
        "country": COUNTRY,
    }

    _check_root(dev, r)
    _ensure_network(dev, r)
    _set_timezone(dev, r)

    # 先把自己解锁回桌面，否则 pm clear 后的第一次解锁会被这次用掉
    r.step("先解锁回桌面（把「首次解锁」留给真正的触发）")
    dev.stayon(True)
    dev.key(KEY_WAKEUP)
    time.sleep(1.0)
    if dev.locked():
        _unlock_with_retries(dev, r, unlock_retries)
    dev.key(KEY_HOME)
    time.sleep(1.0)
    r.ok("已在桌面")

    _inject_county(dev, r, target)
    _clear_atomic(dev, r)

    r.step(f"把系统时间调到 {target.isoformat()} {int(hour):02d}:{int(minute):02d}")
    set_system_datetime(dev, r, target, int(hour), int(minute))
    now = dev.shell("date '+%Y-%m-%d %H:%M:%S %Z'").strip()
    r.ok(f"设备时间 {now}")

    off_at, wake_at = _screen_off_wait(dev, r, int(off_sec))
    result["screen_off_at"] = off_at
    result["screen_on_at"] = wake_at

    _wake_and_unlock(dev, r, unlock_retries)
    hit = _wait_card(dev, r, int(wait_sec))
    result["card_text"] = hit

    r.step("确认智慧建议卡片")
    ensure_home_before_confirm(dev, r)
    ok = bool(hit) or r.confirm()
    if not ok:
        raise UiError(
            f"解锁后等了 {int(wait_sec)} 秒，既没在桌面看到停电预警卡片，"
            "日志里也没有派发记录。"
            "常见原因：①常住区没变成 KE-30（看上面 QUERY_COUNTY 的结果）；"
            f"②{target.isoformat()} 次日 KPLC 没有该地区的停电公告；"
            "③当天已经出过这张卡（规则 22 每天最多 1 次，pm clear 才能重置）。")
    r.ok(f"已确认停电预警卡片：{hit or '人工确认'}")

    dev.stayon(False)
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S %Z'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (
        f"完成。时区已切到 {TIMEZONE}、常住区已注入为 KE-30/Nairobi，"
        f"清理原子化后把时间设到 {target.isoformat()} {int(hour):02d}:{int(minute):02d}，"
        f"息屏 {int(off_sec)} 秒再亮屏上滑解锁，桌面出现停电预警卡片。")
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

"""智能路况卡片（Smart Traffic / `AITIPS_Road_conditions`）触发场景。

对应 atomicbrain 规则 **10058**（`assets/rule/SMART_TRAFFIC.json`）：

  2   TimeSlotRangeAbility  `00_00_00~11_59_59`，`time_source=dismiss_latch`
                            （读「早间闹钟被关掉的时刻」，不是当前时间）
  22  DayCountAbility       每天 1 次（key = `YYYY-MM-DD-10058`）
  44  SmartTrafficLatch     智能路况触发锁必须为 true（`active_abilities`）
  45  AbnormalWeatherAbility 记忆里的当日异常天气类型 ∈ 白名单 [7, 10, 12, 15]

白名单语义（`SmartTrafficAbnormalWeatherType`）：
  7 暴雨（HEAVY_RAIN）/ 10 高温（HIGH_TEMPERATURE）/
  12 中雨（MODERATE_RAIN）/ 15 大风（STRONG_WIND）

两种触发方式（用户 m09227 / m09928 指定）：

**mock**（十几秒，纯调试页）
  1. 从网络共享装 `TransAtomicBrain_full_signed(5).apk`
  2. 打开 `com.transsion.atomicbrain/.debug.Test`，滑到最底部的智能路况区
  3. 先点「清理智能路况当日计数」——**顺序不能反**，ability 22 已达上限时
     后面那次评规则必 fail
  4. 点「MOCK 智能路况卡（异常天气+末闹DISMISS+评规则）」
  5. 回桌面，智慧建议出现「智能路况 / 大雨可能影响车费，请保持充足余额。」

**real**（真实链路，用户给的原始步骤）
  1. 装同一个包（没装才装）
  2. 打开「天气」App（`com.rlk.weathers`），让天气快照进记忆
  3. 系统时间调到当天 12 点前
  4. `logcat | grep -Ei 'WeatherMemorySimulator|isAbnormalFromMemory|
     ingest normalized.*weather|SmartTrafficWeatherJudge'` 看注入情况
  5. `am startservice -n .../.debug.DebugService -a brain.intent.action.DISPATCH_EVENT
     --es action_type simulate_weather_memory --es target_date <当天> --ei abnormal_type 7`
     （示例里的 2026-08-04 要换成设备当天）
  6. 设一个「当前时间下一分钟」的闹钟，息屏等它响
  7. 响铃后关掉闹钟（这一步就是 ability 2 读的 dismiss_latch），解锁回桌面

**关于第 5 步的现实情况（实测，别当成 bug）**：
`simulate_weather_memory` 在 17.10.00.101 与 17.11.00.104 里都**不存在** ——
26 个 dex 里 `simulate` 前缀 0 命中，发了只会得到
`TAB.RuleActionHandler: handleTestDataAction: unknown action_type=simulate_weather_memory`。
所以本模块仍然会**照用户给的命令原样发一次**（并记录返回值/日志，用户能看到真实反馈），
然后按下面的顺序自动降级：

  A. `data_type=WeatherTipsEvent` + `{"abnormalWeatherType":7}`（DebugService 唯一接受的事件类型）
  B. 都不行 → 打开调试页点「MOCK 智能路况卡」把异常天气写进记忆（`weather_source`
     记为 `mock_button_fallback`），闹钟这一段仍然走真实链路

每一步之后都用调试页的「查看智能路况前置条件自检」读 `isAbnormalFromMemory`，
这是判断「天气记忆到底有没有写进去」的唯一权威信号。
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import time

from phone_ctl import KEY_HOME, KEY_WAKEUP, Device, UiError

from scenario_atomic_mock import ATOMIC_ACTIVITY, ATOMIC_PACKAGE, ensure_installed
from scenario_birthday import (
    Runner,
    _cli_emit,
    _unlock_with_retries,
    _wait_screen_on,
    device_date,
    ensure_home_before_confirm,
    set_system_datetime,
)
from scenario_power_saving import (
    card_dispatched,
    match_card,
    open_debug_page,
    screen_off_and_unlock,
    wait_card,
)

# ── 调试页（TransAtomicBrain 17.10.00.101 起）智能路况区的控件 ──────────────
RID_MOCK_TRAFFIC = "com.transsion.atomicbrain:id/btn_mock_smart_traffic"
RID_RESET_TRAFFIC = "com.transsion.atomicbrain:id/btn_reset_smart_traffic_day_count"
RID_QUERY_TRAFFIC = "com.transsion.atomicbrain:id/btn_query_smart_traffic_state"
RID_TRAFFIC_RESULT = "com.transsion.atomicbrain:id/text_smart_traffic_mock_result"

# ── 事件投递 ────────────────────────────────────────────────────────────
BRAIN_COMPONENT = f"{ATOMIC_PACKAGE}/.debug.DebugService"
BRAIN_ACTION = "brain.intent.action.DISPATCH_EVENT"

# ── 天气 ────────────────────────────────────────────────────────────────
WEATHER_PKG = "com.rlk.weathers"
WEATHER_LOG_TAGS = (
    "WeatherMemorySimulator",
    "isAbnormalFromMemory",
    "ingest normalized.*weather",
    "SmartTrafficWeatherJudge",
)
WEATHER_LOG_GREP = (
    "WeatherMemorySimulator|isAbnormalFromMemory|"
    "ingest normalized.*weather|SmartTrafficWeatherJudge"
)

# ── 天气 App 首次进入的引导（实测 X6766 / com.rlk.weathers）──────────────
# 1) 首次启动弹「欢迎使用天气」GDPR 协议页：
#      tv_title=欢迎使用天气 / os_auto_aj_left_btn=取消 / os_auto_aj_right_btn=同意
# 2) 点「同意」后弹系统定位精度页（GrantPermissionsActivity）：
#      permission_allow_foreground_only_button（更改为确切位置）
#      permission_allow_one_time_button（仅限这一次）
#      permission_deny_button（继续使用大致位置）
# 3) 之后进主页：tv_name=城市名 / tv_temperature / tv_desc_and_range / 7 天列表
WEATHER_TOUR_RIDS = ("os_auto_aj_right_btn",)          # 协议页「同意」
WEATHER_TOUR_TEXTS = ("同意", "Agree", "Accept", "موافق")
WEATHER_PERM_RIDS = (
    "permission_allow_foreground_only_button",   # 使用应用时允许 / 更改为确切位置
    "permission_allow_button",                   # 允许
    "permission_allow_one_time_button",          # 仅限这一次
    "permission_allow_all_button",
)
WEATHER_PERM_TEXTS = (
    "仅在使用中允许", "使用时允许", "允许", "始终允许", "更改为确切位置",
    "仅限这一次", "同意", "确定", "知道了", "我知道了", "开始使用",
    "While using the app", "Allow", "OK", "Got it", "موافق", "السماح",
)
WEATHER_REFRESH_RID = "layout_refresh"       # SwipeRefresh 容器，下拉即刷新
WEATHER_CITY_RID = "tv_name"                 # 主页城市名，判断是否真的进了主页

# ── 规则常量 ────────────────────────────────────────────────────────────
ABNORMAL_TYPE = 7                      # 7 = 暴雨 HEAVY_RAIN
ABNORMAL_WHITELIST = (7, 10, 12, 15)
RULE_ID = 10058

# ── 真实链路的固定时刻（当天 12 点前，确定性优先）─────────────────────────
REAL_HOUR = 11
REAL_MINUTE = 28
ALARM_LEAD_MIN = 1                     # 闹钟设在「当前时间 + 1 分钟」
ALARM_WAIT_SEC = 150                   # 下午设置后最多等多久闹钟响
OFF_SECONDS = 10
WAIT_CARD_SEC = 90

# ── 卡片文案（三语言）────────────────────────────────────────────────────
TRAFFIC_HINTS_ZH = ("智能路况", "大雨可能影响车费", "暴雨可能影响", "路况")
TRAFFIC_HINTS_EN = ("smart traffic", "traffic conditions", "heavy rain may affect",
                    "rain may affect the fare", "road conditions")
TRAFFIC_HINTS_AR = ("حركة المرور", "الطرق", "الأمطار", "حالة الطريق")


def _ensure_awake(dev: Device, r: Runner) -> None:
    """保证屏幕亮着且已解锁。

    这台 X6766 的灭屏超时很短，滚调试页（十几轮 swipe、每轮一次 dump）走完
    可能就自己黑屏了；一黑屏 `uiautomator dump` 立刻拿不到控件树，
    报「控件树为空（落盘式 dump 也没拿到内容）」（实测）。
    所以每次操作前都先 `stayon(True)` + 唤醒 + 解锁，成本很低。
    """
    dev.stayon(True)
    if not dev.screen_on():
        dev.key(KEY_WAKEUP)
        _wait_screen_on(dev, True, timeout=4.0)
    if dev.locked():
        r.log("屏幕已锁，先解锁")
        _unlock_with_retries(dev, r, 3)
        time.sleep(0.6)


def _ensure_network(dev: Device, r: Runner) -> None:
    """智能路况卡要联网（天气快照来自天气云），但**不要求改时区/国家**。

    规则 10058 的四条 ability（2 时间窗 / 22 每日额度 / 44 路况 latch /
    45 异常天气）里没有任何国家或时区约束，所以这里只保证网络通，
    不动 `persist.sys.timezone` —— 停电卡那套 `Africa/Nairobi + KE` 是它自己的
    需要，跟这张卡无关，硬套会把设备时区搞乱、还会让时间窗错位。
    """
    r.step("确认设备联网（天气快照要走天气云）")
    _ensure_awake(dev, r)
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
        raise UiError(
            "设备没有网络，智能路况卡要先从天气云拿到天气快照才能评价异常天气。"
            "请先把手机的 Wi-Fi 连上（`cmd wifi status` 看是否已连接）。")
    r.ok("联网正常")


# ══════════════════════════════════════════════════════════════════════════
# 调试页操作
# ══════════════════════════════════════════════════════════════════════════
def scroll_to_traffic(dev: Device, r: Runner, max_rounds: int = 14) -> None:
    """滚到调试页底部的智能路况区，直到「清理当日计数」按钮出现在屏内。"""
    r.step("滚到调试页底部的「智能路况」区域")
    w, h = dev.screen_size()
    for i in range(1, max_rounds + 1):
        _ensure_awake(dev, r)          # 灭屏会让 dump 直接失败，每轮先兜一下
        node = dev.find_opt(rid=RID_RESET_TRAFFIC)
        if node is not None and 0 < node.center[1] < h - 40:
            r.ok(f"已滚到智能路况区（第 {i} 次后按钮在 {node.center}）")
            return
        dev.swipe(w // 2, int(h * 0.80), w // 2, int(h * 0.32), 280)
        time.sleep(0.7)
    raise UiError(
        "滑了 %d 次仍没看到「清理智能路况当日计数」按钮。"
        "请确认设备上装的是 TransAtomicBrain_full_signed(5).apk（17.10.00.101），"
        "旧包 17.11.00.104 的调试页里没有智能路况这一块。" % max_rounds)


def tap_traffic_button(dev: Device, r: Runner, rid: str, label: str) -> None:
    """按 resource-id 点智能路况区的按钮（找不到时退回按文案找）。"""
    r.step(f"点击「{label}」")
    _ensure_awake(dev, r)
    try:
        node = dev.wait_node(rid=rid, timeout=10.0)
    except UiError:
        r.log(f"按 resource-id {rid} 没找到，改按文案「{label}」查找")
        node = dev.wait_node(text=label, timeout=6.0)
    dev.tap_node(node, 0.8)
    time.sleep(1.2)
    r.ok(f"已点击，控件在 {node.center}")


def read_traffic_result(dev: Device, timeout: float = 8.0) -> str:
    """读 `text_smart_traffic_mock_result` 里的结果文本（`\\n` 是换行）。"""
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        node = dev.find_opt(rid=RID_TRAFFIC_RESULT)
        text = ((node.text or node.desc or "") if node else "").strip()
        if text:
            return text
        time.sleep(0.6)
    return text


def self_check(dev: Device, r: Runner) -> dict:
    """点「查看智能路况前置条件自检」并解析关键字段。

    返回 {"raw", "abnormal", "type", "day_count", "latch"}，
    `abnormal` 就是 `isAbnormalFromMemory`，判断天气记忆是否写成功的唯一权威信号。
    """
    r.step("点「查看智能路况前置条件自检」，读当前前置条件")
    tap_traffic_button(dev, r, RID_QUERY_TRAFFIC, "查看智能路况前置条件自检")
    raw = read_traffic_result(dev)
    if not raw:
        raise UiError(
            "点了自检按钮但没读到结果文本（text_smart_traffic_mock_result 是空的），"
            "调试页可能已经滚走，请重试。")

    info: dict = {"raw": raw}
    m = re.search(r"abnormalWeatherType=(\w+)", raw)
    info["type"] = m.group(1) if m else "?"
    info["abnormal"] = "isAbnormalFromMemory=true" in raw
    m = re.search(r"count=(\d+)", raw)
    info["day_count"] = int(m.group(1)) if m else -1
    info["latch"] = "未 arm" not in raw
    r.log(f"自检结果：abnormalWeatherType={info['type']} "
          f"isAbnormalFromMemory={info['abnormal']} "
          f"日计数={info['day_count']} 末闹latch={'已arm' if info['latch'] else '未arm'}")
    return info


# ══════════════════════════════════════════════════════════════════════════
# 天气记忆注入
# ══════════════════════════════════════════════════════════════════════════
def _weather_home_ready(nodes: list) -> bool:
    """天气主页是否已经加载出来（城市名 + 下拉刷新容器都在）。"""
    city = any((n.short_id or "") == WEATHER_CITY_RID and (n.text or "").strip()
               for n in nodes)
    refresh = any((n.short_id or "") == WEATHER_REFRESH_RID for n in nodes)
    return city and refresh


def _dismiss_weather_blockers(dev: Device, r: Runner, nodes: list) -> bool:
    """点掉天气 App 的 GDPR 协议页 / 系统权限弹窗，点过返回 True。

    两种都按 rid 优先、文案兜底：文案随系统语言变，rid 是稳定的。
    """
    for rid in WEATHER_TOUR_RIDS + WEATHER_PERM_RIDS:
        for n in nodes:
            if (n.short_id or "") == rid:
                r.log(f"天气 App 有弹窗，按 rid 点「{(n.text or rid).strip()[:20]}」")
                dev.tap_node(n)
                time.sleep(2.0)
                return True
    for n in nodes:
        txt = (n.text or "").strip()
        if txt in WEATHER_TOUR_TEXTS or txt in WEATHER_PERM_TEXTS:
            r.log(f"天气 App 有弹窗，按文案点「{txt[:20]}」")
            dev.tap_node(n)
            time.sleep(2.0)
            return True
    return False


def refresh_weather(dev: Device, r: Runner) -> bool:
    """在天气主页下拉刷新一次，让天气云重新拉数据、写一条新的 WEATHER 记忆。"""
    node = dev.find_opt(rid=WEATHER_REFRESH_RID)
    if node is None:
        r.log("没找到下拉刷新容器，跳过刷新")
        return False
    w, h = dev.screen_size()
    # 从列表上沿往下拉，SwipeRefresh 需要拉够距离才会触发
    x = node.center[0]
    y1 = max(node.bounds[1] + int(h * 0.12), int(h * 0.22))
    y2 = min(y1 + int(h * 0.42), int(h * 0.82))
    r.log(f"下拉刷新天气：({x},{y1}) → ({x},{y2})")
    dev.swipe(x, y1, x, y2, 420)
    time.sleep(1.5)
    # 刷新后等骨架屏/动画结束
    deadline = time.time() + 8.0
    while time.time() < deadline:
        if dev.find_opt(rid=WEATHER_CITY_RID) is not None:
            break
        time.sleep(1.0)
    time.sleep(2.0)
    r.ok("已下拉刷新一次")
    return True


def open_weather_app(dev: Device, r: Runner) -> None:
    """打开系统「天气」App，走完首次引导，再下拉刷新一次。

    实测（X6766 / com.rlk.weathers，清过数据后）首次进入有三道门：
    GDPR 协议页 → 系统定位精度页 → 主页。不点掉就永远停在弹窗上，
    天气云一次都不会请求，WEATHER 记忆也就不会更新。
    """
    r.step("打开「天气」App 并下拉刷新一次")
    # 先把屏幕弄亮、解锁、回桌面：锁屏/通知栏状态下 `monkey` 拉不起来，
    # 焦点会一直停在 NotificationShade（实测），后面所有 dump 都读不到天气主页。
    dev.stayon(True)
    if not dev.screen_on():
        dev.key(KEY_WAKEUP)
        _wait_screen_on(dev, True, timeout=4.0)
    if dev.locked():
        _unlock_with_retries(dev, r, 3)
        time.sleep(0.6)
    if "launcher" not in (dev.focus() or "").lower():
        dev.key(KEY_HOME)
        time.sleep(1.0)
        if dev.locked():                      # 刚才那次 HOME 可能又落回锁屏
            _unlock_with_retries(dev, r, 3)
            dev.key(KEY_HOME)
            time.sleep(0.8)
    r.log(f"启动前焦点：{dev.focus()}")

    out = dev.shell(f"monkey -p {WEATHER_PKG} -c android.intent.category.LAUNCHER 1")
    if "Error" in out or "No activities found" in out:
        raise UiError(
            f"打不开天气 App（{WEATHER_PKG}）：{out.strip()[:200]}。"
            "这台设备可能没装天气 App，只能改用 mock 触发方式。")
    time.sleep(3.0)
    r.log(f"当前窗口：{dev.focus()}")

    # 最多 8 轮：点掉协议页 / 权限页，直到主页真的出来
    for i in range(1, 9):
        nodes = dev.dump()
        if _weather_home_ready(nodes):
            r.ok(f"天气主页已就绪（第 {i} 轮，城市 "
                 f"{next((n.text for n in nodes if (n.short_id or '') == WEATHER_CITY_RID and n.text), '?')}）")
            break
        if not _dismiss_weather_blockers(dev, r, nodes):
            r.log(f"第 {i} 轮：主页还没好也没弹窗，再等一下（focus={dev.focus()}）")
            time.sleep(2.5)
        else:
            time.sleep(1.0)
    else:
        r.log("8 轮之后仍没确认天气主页就绪，继续往下走，不阻塞")

    refresh_weather(dev, r)
    dev.key(KEY_HOME)
    time.sleep(0.8)


def weather_logs(dev: Device) -> list[str]:
    """执行用户给的那条 logcat grep，返回命中的行。"""
    out = dev.shell(f'logcat -d | grep -Ei "{WEATHER_LOG_GREP}"')
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _dispatch(dev: Device, extras: list[str]) -> str:
    cmd = (f"am startservice -n {BRAIN_COMPONENT} -a {BRAIN_ACTION} "
           + " ".join(extras))
    return dev.shell(cmd)


def dispatch_simulate_weather(dev: Device, r: Runner,
                              target: _dt.date) -> tuple[bool, str]:
    """用户给的原命令：`action_type=simulate_weather_memory`（日期换成设备当天）。

    返回 (是否被接受, 原始输出说明)。已知 17.10.00.101 上会返回
    `unknown action_type=simulate_weather_memory`，这里如实记录、不抛错。
    """
    r.step(f"发 simulate_weather_memory（target_date={target.isoformat()} "
           f"abnormal_type={ABNORMAL_TYPE}）")
    dev.shell("logcat -c")
    out = _dispatch(dev, [
        "--es", "action_type", "simulate_weather_memory",
        "--es", "target_date", target.isoformat(),
        "--ei", "abnormal_type", str(ABNORMAL_TYPE),
    ])
    time.sleep(1.5)
    log = dev.shell("logcat -d -s TAB.RuleActionHandler:D TAB.DebugUtils:D")
    if "unknown action_type" in log:
        r.log("这台设备上的 atomicbrain 不认识 simulate_weather_memory"
              "（该 action 在 17.10.00.101 / 17.11.00.104 里都不存在），改走降级方案")
        return False, "unknown action_type=simulate_weather_memory"
    if "Error" in out or "Exception" in out:
        r.log(f"am startservice 返回异常：{out.strip()[:200]}")
        return False, out.strip()[:200]
    r.ok("simulate_weather_memory 已被接受")
    return True, out.strip()[:200]


def dispatch_weather_tips(dev: Device, r: Runner,
                          abnormal_type: int = ABNORMAL_TYPE) -> bool:
    """降级方案 A：`data_type=WeatherTipsEvent`（DebugService 唯一接受的事件类型）。"""
    r.step(f"降级：发 WeatherTipsEvent（abnormalWeatherType={abnormal_type}）")
    payload = json.dumps({"abnormalWeatherType": abnormal_type,
                          "weatherId": abnormal_type}, ensure_ascii=False)
    dev.shell("logcat -c")
    out = _dispatch(dev, [
        "--es", "data_type", "WeatherTipsEvent",
        "--es", "action_type", "listener",
        "--es", "json_data", f"'{payload}'",
    ])
    time.sleep(1.5)
    log = dev.shell("logcat -d -s TAB.DebugUtils:D TAB.RuleActionHandler:D")
    if "unkown type" in log or "unknown type" in log:
        r.log(f"WeatherTipsEvent 没被接受：{log.strip()[:200]}")
        return False
    if "handleListenerData: send event for WeatherTipsEvent" in log:
        r.log("WeatherTipsEvent 已投递")
        return True
    r.log(f"投递结果不明：{out.strip()[:160]}")
    return False


def write_weather_via_mock_button(dev: Device, r: Runner) -> None:
    """降级方案 B：点调试页的「MOCK 智能路况卡」把异常天气写进记忆。

    注意这个按钮**顺带会把 dismiss_latch arm 成当天 08:30 并立刻评一次规则**，
    所以卡片可能在闹钟响之前就出来了 —— 调用点要在结果里标明
    `weather_source="mock_button_fallback"`，不要假装走的是纯真实链路。
    """
    r.step("降级：点「MOCK 智能路况卡」把异常天气写入记忆")
    tap_traffic_button(dev, r, RID_RESET_TRAFFIC,
                       "清理智能路况当日计数（ABILITY 22 上限 1）")
    tap_traffic_button(dev, r, RID_MOCK_TRAFFIC,
                       "MOCK 智能路况卡（异常天气+末闹DISMISS+评规则）")
    raw = read_traffic_result(dev)
    if raw:
        r.log(f"mock 按钮返回：{raw.replace(chr(10), ' / ')[:400]}")
    if "isAbnormalFromMemory=true" in raw or "回读判定=true" in raw:
        r.ok("异常天气已写入记忆")
    else:
        r.log("mock 按钮没有明确回报异常天气写入成功，继续往下走")


# ══════════════════════════════════════════════════════════════════════════
# 闹钟：设 → 等响 → 关掉（关掉那一刻就是 ability 2 读的 dismiss_latch）
# ══════════════════════════════════════════════════════════════════════════
def device_clock(dev: Device) -> tuple[int, int]:
    """读设备当前时分（`date +%H:%M` 永远是 ASCII，不受阿拉伯语数字影响）。"""
    raw = dev.shell("date '+%H:%M'").strip()
    m = re.search(r"(\d{1,2}):(\d{2})", raw)
    if not m:
        raise UiError(f"读不到设备当前时间（date 返回 {raw!r}）")
    return int(m.group(1)), int(m.group(2))


def set_one_shot_alarm(dev: Device, r: Runner, hour: int, minute: int) -> str:
    """设一个「只响一次」的闹钟（不传 DAYS，就不会变成每日闹钟）。"""
    r.step(f"设置一次性闹钟 {hour:02d}:{minute:02d}")
    cmd = (
        "am start -a android.intent.action.SET_ALARM"
        f" --ei android.intent.extra.alarm.HOUR {hour}"
        f" --ei android.intent.extra.alarm.MINUTES {minute}"
        " --ez android.intent.extra.alarm.SKIP_UI true"
        " -p com.transsion.deskclock"
    )
    dev.shell("logcat -c")
    out = dev.shell(cmd)
    if "Error" in out or "Exception" in out:
        raise UiError(f"创建闹钟失败：{out.strip()[:300]}")

    pat = re.compile(
        r"addAlarm:\s*status=(\d+).*?enabled=(\w+).*?"
        r"hour=(\d+),\s*minutes=(\d+)", re.S)
    deadline = time.time() + 12.0
    while time.time() < deadline:
        time.sleep(1.0)
        log = dev.shell("logcat -d -s TAG_GeminiFuncHelper")
        for m in pat.finditer(log):
            if (int(m.group(3)), int(m.group(4))) == (hour, minute) \
                    and m.group(2).lower() == "true":
                r.ok(f"闹钟已创建 {hour:02d}:{minute:02d}")
                return f"{hour:02d}:{minute:02d}"
    raise UiError(
        f"闹钟设置后时钟 App 没有确认创建 {hour:02d}:{minute:02d}"
        "（logcat 里没有 addAlarm status=1）")


_ALARM_FOCUS_HINTS = ("deskclock", "alarm", "AlertActivity",
                      "com.transsion.deskclock")
_ALARM_DISMISS_TEXT = (
    "停止", "关闭", "结束", "关掉", "停止闹钟",
    "Dismiss", "Stop", "Stop alarm", "Turn off",
    "إيقاف", "إيقاف المنبه", "إغلاق", "إلغاء",
)
_ALARM_DISMISS_RIDS = (
    "alarm_dismiss", "alarm_alert_dismiss", "btn_dismiss",
    "alarm_stop", "btn_stop", "stop", "dismiss",
)


def wait_alarm_ring(dev: Device, r: Runner, max_wait: int = ALARM_WAIT_SEC) -> bool:
    """息屏等闹钟响：屏幕自己亮起来且焦点落到时钟 App 就算响了。"""
    r.step(f"息屏等闹钟响（最多 {max_wait} 秒）")
    dev.stayon(False)
    dev.key(223)                                    # KEYCODE_SLEEP
    _wait_screen_on(dev, False, timeout=4.0)
    r.log("屏幕已灭，等闹钟")

    start = time.time()
    while time.time() - start < max_wait:
        r.check()
        left = int(max_wait - (time.time() - start))
        if int(time.time() - start) % 5 == 0:
            r.tick(left)
        time.sleep(1.0)
        if not dev.screen_on():
            continue
        focus = dev.focus()
        if any(h.lower() in focus.lower() for h in _ALARM_FOCUS_HINTS):
            r.ok(f"闹钟响了，当前窗口 {focus}")
            return True
        r.log(f"屏幕亮了但焦点在 {focus}，继续等")

    r.log(f"{max_wait} 秒内没等到闹钟响")
    dev.stayon(True)
    return False


def dismiss_alarm(dev: Device, r: Runner) -> None:
    """关掉正在响的闹钟 —— 这一刻就是 ability 2 读的 dismiss_latch。"""
    r.step("关闭闹钟（写入 dismiss_latch）")
    nodes = []
    try:
        nodes = dev.dump()
    except UiError:
        pass

    # 1) 按文案找停止/关闭按钮
    for text in _ALARM_DISMISS_TEXT:
        for n in nodes:
            value = (n.text or n.desc or "").strip()
            if value == text:
                dev.tap_node(n, 0.8)
                time.sleep(1.2)
                r.ok(f"已按文案「{value}」关掉闹钟")
                return
    # 2) 按 resource-id 找
    for rid_tail in _ALARM_DISMISS_RIDS:
        for n in nodes:
            if (n.rid or "").lower().endswith(rid_tail):
                dev.tap_node(n, 0.8)
                time.sleep(1.2)
                r.ok(f"已按 resource-id ...{rid_tail} 关掉闹钟")
                return
    # 3) 兜底：返回键（AOSP 时钟响铃页按返回即静音关闭）
    r.log("没找到停止按钮，按返回键关闭闹钟")
    dev.key(4)
    time.sleep(1.2)
    dev.key(4)
    time.sleep(1.0)
    r.ok("已按返回键关闭闹钟")


# ══════════════════════════════════════════════════════════════════════════
# 回桌面 + 出卡
# ══════════════════════════════════════════════════════════════════════════
def back_to_desktop(dev: Device, r: Runner, unlock_retries: int = 3) -> None:
    """唤醒 + 上滑解锁 + HOME。"""
    r.step("唤醒解锁并回到桌面")
    dev.stayon(True)
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=4.0)
    time.sleep(0.6)
    if dev.locked():
        _unlock_with_retries(dev, r, unlock_retries)
    dev.key(KEY_HOME)
    time.sleep(0.9)
    focus = dev.focus()
    if "launcher" not in focus.lower():
        r.log(f"按 HOME 后焦点仍在 {focus}，再按一次")
        dev.key(KEY_HOME)
        time.sleep(0.9)
        focus = dev.focus()
    if "launcher" not in focus.lower():
        raise UiError(f"按 HOME 后没回到桌面，当前窗口 {focus!r}")
    r.ok(focus)


# ══════════════════════════════════════════════════════════════════════════
# 两条路径
# ══════════════════════════════════════════════════════════════════════════
def run_mock(dev: Device, r: Runner, wait_sec: int = WAIT_CARD_SEC) -> dict:
    """mock 路径：清当日计数 → mock 智能路况卡 → 回桌面 → 等卡。"""
    ensure_installed(dev, r)
    _ensure_network(dev, r)
    open_debug_page(dev, r)
    scroll_to_traffic(dev, r)

    # 顺序不能反：ability 22 一天只给 1 次，不先清计数后面的评规则必 fail
    tap_traffic_button(dev, r, RID_RESET_TRAFFIC,
                       "清理智能路况当日计数（ABILITY 22 上限 1）")
    r.log(f"清理结果：{read_traffic_result(dev).replace(chr(10), ' / ')[:200]}")

    tap_traffic_button(dev, r, RID_MOCK_TRAFFIC,
                       "MOCK 智能路况卡（异常天气+末闹DISMISS+评规则）")
    raw = read_traffic_result(dev)
    if raw:
        r.log(f"mock 返回：{raw.replace(chr(10), ' / ')[:500]}")

    back_to_desktop(dev, r)
    hit = wait_card(dev, r, int(wait_sec),
                    TRAFFIC_HINTS_ZH, TRAFFIC_HINTS_EN, TRAFFIC_HINTS_AR,
                    "智能路况卡片")
    return {
        "method": "mock",
        "mock_result": (raw or "")[:600],
        "card_text": hit,
        "wait_sec": int(wait_sec),
    }


def memory_verdict(dev: Device) -> tuple[bool, str]:
    """只从 logcat 判断「异常天气是否已经进记忆」。

    用户要求 real 路径不许打开 test brain 软件，所以不能用调试页的
    「查看智能路况前置条件自检」按钮，只能读判定器自己打的日志：
        TAB.SmartTrafficWeatherJudge: isAbnormalFromMemory: today=... abnormalWeatherType=7 match=true
    """
    raw = dev.shell(
        "logcat -d -s SmartTrafficWeatherJudge:D TAB.SmartTrafficWeatherJudge:D "
        "TAB.WeatherIntent:D WeatherMemorySimulator:D | "
        "grep -Ei 'isAbnormalFromMemory|abnormalWeatherType' | tail -20"
    ) or ""
    hit = re.search(r"abnormalWeatherType=(-?\d+|null)", raw)
    ok = bool(re.search(r"isAbnormalFromMemory:\s*.*match=true", raw)) and (
        hit is not None and hit.group(1) not in ("null", "-1")
    )
    return ok, raw.strip()


def run_real(dev: Device, r: Runner, *,
             abnormal_type: int = ABNORMAL_TYPE,
             wait_sec: int = WAIT_CARD_SEC,
             alarm_wait: int = ALARM_WAIT_SEC,
             hour: int = REAL_HOUR, minute: int = REAL_MINUTE) -> dict:
    """real（真实）路径，全程不打开 test brain 软件：

    1) 检查/安装 TransAtomicBrain_full_signed(5).apk
    2) 打开天气 App（GDPR 授权 + 定位授权 + 下拉刷新）
    3) 系统时间调到当天 12 点前
    4) logcat 查天气记忆注入情况
    5) 发 simulate_weather_memory（target_date = 设备当天）
    6) 设「当前时间 + 1 分钟」闹钟 → 息屏等响 → 关闹钟 → 解锁回桌面 → 出卡
    """
    ensure_installed(dev, r)
    _ensure_network(dev, r)

    target = device_date(dev)

    # 1) 打开天气 App，让它 ingest 一次真实天气快照
    open_weather_app(dev, r)

    # 2) 时间调到当天 12 点前（默认固定 11:28，确定性优先）
    r.step(f"把系统时间调到 {target.isoformat()} "
           f"{int(hour):02d}:{int(minute):02d}（当天 12 点前）")
    set_system_datetime(dev, r, target, int(hour), int(minute))
    r.ok(f"设备时间 {dev.shell('date').strip()}")

    # 3) 用户给的 logcat 查询，看天气记忆注入情况
    r.step("查 logcat 看天气记忆注入情况")
    dumps = weather_logs(dev)
    if dumps:
        r.log(f"命中 {len(dumps)} 行，前 3 行：")
        for line in dumps[:3]:
            r.log(f"  {line[:180]}")
    else:
        r.log("还没命中任何天气记忆日志（打开天气 App 后可能要多等一会儿）")
        time.sleep(5.0)
        dumps = weather_logs(dev)
        r.log(f"再查一次命中 {len(dumps)} 行")

    # 4) 用户给的原命令（日期换成设备当天）
    accepted, detail = dispatch_simulate_weather(dev, r, target)
    weather_source = "simulate_weather_memory" if accepted else "none"
    if not accepted:
        r.log("这条 action 当前版本不认（不是脚本的问题，是包里没有这个分支），"
              "继续按真实链路走：天气 App 写入的记忆 + 闹钟 dismiss")

    # 5) 只读 logcat 判断异常天气有没有进记忆（不打开调试页）
    r.step("从 logcat 判断异常天气是否已进记忆")
    mem_ok, mem_raw = memory_verdict(dev)
    if mem_ok:
        r.ok("logcat 显示 isAbnormalFromMemory 已为 true")
    else:
        r.log("logcat 里暂时没有 isAbnormalFromMemory=true；"
              "真实天气接口不下发 abnormalWeatherType，这次可能出不了卡，先把流程走完")
    if mem_raw:
        for line in mem_raw.splitlines()[-3:]:
            r.log(f"  {line[:180]}")

    # 6) 设一个「当前时间 + 1 分钟」的闹钟
    #    这里必须读**设备此刻**的时间，不能拿开始时设的 hour:minute 去加 ——
    #    中间开了天气 App、调了系统时间，早就过了好几分钟，
    #    按旧值算会落回过去，时钟会把它排到明天，这次就白等了。
    now_h, now_m = device_clock(dev)
    alarm_h, alarm_m = now_h, now_m + ALARM_LEAD_MIN
    if alarm_m >= 60:
        alarm_h, alarm_m = alarm_h + 1, alarm_m - 60
    if alarm_h > 11:
        r.log(f"警告：设备时间已经走到 {now_h:02d}:{now_m:02d}，"
              f"闹钟会落在 {alarm_h:02d}:{alarm_m:02d}，"
              "超过规则 2 的 00:00~11:59 时间窗，这次大概率出不了卡")
    alarm_at = set_one_shot_alarm(dev, r, alarm_h, alarm_m)
    r.log(f"设备当前 {now_h:02d}:{now_m:02d}，闹钟设在 {alarm_at}")

    # 7) 息屏等它响
    dev.key(KEY_HOME)
    time.sleep(0.8)
    rang = wait_alarm_ring(dev, r, alarm_wait)
    if rang:
        dismiss_alarm(dev, r)
    else:
        r.log("没等到闹钟响，dismiss_latch 可能不会被写入，先继续看卡片")

    # 8) 解锁回桌面等卡
    back_to_desktop(dev, r)
    hit = wait_card(dev, r, int(wait_sec),
                    TRAFFIC_HINTS_ZH, TRAFFIC_HINTS_EN, TRAFFIC_HINTS_AR,
                    "智能路况卡片")

    return {
        "method": "real",
        "target_date": target.isoformat(),
        "weather_source": weather_source,
        "simulate_accepted": accepted,
        "simulate_detail": detail,
        "weather_log_lines": len(dumps),
        "memory_abnormal": mem_ok,
        "alarm_at": alarm_at,
        "alarm_rang": rang,
        "card_text": hit,
        "wait_sec": int(wait_sec),
    }


def run(dev: Device | None = None, emit=None, *,
        method: str = "mock",
        abnormal_type: int = ABNORMAL_TYPE,
        off_sec: int = OFF_SECONDS,
        wait_sec: int = WAIT_CARD_SEC,
        alarm_wait: int = ALARM_WAIT_SEC,
        hour: int = REAL_HOUR, minute: int = REAL_MINUTE,
        unlock_retries: int = 3,
        control: dict | None = None, confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    if method not in ("mock", "real"):
        raise UiError(f"未知触发方式 {method!r}，只能是 mock / real")
    if not (20 <= wait_sec <= 240):
        raise UiError("wait_sec（解锁后等卡片）必须在 20~240 秒之间")
    if not (10 <= alarm_wait <= 300):
        raise UiError("alarm_wait（等闹钟响）必须在 10~300 秒之间")
    # 前端 select 下发的是字符串（"7"），这里统一转成整数再比白名单
    try:
        abnormal_type = int(abnormal_type)
    except (TypeError, ValueError):
        raise UiError(
            f"abnormal_type={abnormal_type!r} 不是数字（可选 "
            f"{ABNORMAL_WHITELIST}：7 暴雨 / 10 高温 / 12 中雨 / 15 大风）")
    if abnormal_type not in ABNORMAL_WHITELIST:
        raise UiError(
            f"abnormal_type={abnormal_type} 不在白名单 {ABNORMAL_WHITELIST} 里"
            "（7 暴雨 / 10 高温 / 12 中雨 / 15 大风）")
    # 规则 2 的时间窗是 00:00~11:59，12 点之后设的 dismiss_latch 一定不满足
    try:
        hour, minute = int(hour), int(minute)
    except (TypeError, ValueError):
        raise UiError(f"系统时间 {hour!r}:{minute!r} 不是合法时分")
    if method == "real" and not (0 <= hour <= 11):
        raise UiError(
            f"真实链路的系统时间必须在当天 12 点前（规则 2 的时间窗是 "
            f"00:00~11:59），收到 {hour:02d}:{minute:02d}")

    try:
        if method == "mock":
            out = run_mock(dev, r, wait_sec)
        else:
            out = run_real(dev, r, abnormal_type=abnormal_type,
                           wait_sec=wait_sec, alarm_wait=alarm_wait,
                           hour=int(hour), minute=int(minute))
    finally:
        # 跑挂了也把屏幕恢复成常亮，别让设备停在「息屏/等闹钟」的半路状态
        try:
            dev.stayon(True)
        except Exception:
            pass

    r.step("确认智慧建议卡片")
    hit = out.get("card_text")
    ok = bool(hit) or r.confirm()
    if not ok:
        hint = (
            "常见原因：①天气记忆里的 abnormalWeatherType 不在白名单 "
            f"{ABNORMAL_WHITELIST}（自检按钮可查）；②当天额度已用掉"
            f"（ability 22 每天 1 次，先点「清理当日计数」）；"
            "③末闹 dismiss_latch 落在 12:00 之后（规则 2 的时间窗是 00:00~11:59）"
            if method == "mock" else
            "常见原因：①这个版本的 atomicbrain 不认识 simulate_weather_memory，"
            "天气接口也不下发 abnormalWeatherType，记忆里进不了白名单值；"
            "②闹钟没响或没被关掉，dismiss_latch 没写入；"
            "③当天额度已用掉（ability 22 每天 1 次）")
        raise UiError(
            f"解锁后等了 {int(wait_sec)} 秒，既没在桌面看到智能路况卡片，"
            f"日志里也没有 tvTitle 含「智能路况」的渲染记录。{hint}")
    r.ok(f"已确认智能路况卡片：{hit or '人工确认'}")

    dev.stayon(False)
    out["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S %Z'").strip()
    out["steps"] = r._no
    out["ok"] = True
    out["triggered"] = bool(hit)
    out["rule_id"] = RULE_ID
    if method == "mock":
        out["summary"] = (
            "完成。已通过 TransAtomicBrain 调试页触发智能路况卡片："
            "先清理 rule 10058 的当日计数，再点「MOCK 智能路况卡」"
            "（写入异常天气记忆 + arm 末闹 latch + 评规则），回桌面后"
            "智慧建议出现「智能路况」。")
    else:
        seen = "智慧建议出现「智能路况」" if hit else "但桌面上没有等到卡片"
        out["summary"] = (
            f"完成真实链路（全程没打开 test brain）：打开天气 App → 系统时间调到当天 "
            f"{int(hour):02d}:{int(minute):02d}（12 点前）→ 发 simulate_weather_memory"
            f"（{'被接受' if out.get('simulate_accepted') else '该版本不认识这个 action'}）→ "
            f"设 {out.get('alarm_at')} 的闹钟 → "
            f"息屏等响（{'已响并关闭' if out.get('alarm_rang') else '未响'}）→ "
            f"解锁回桌面 → {seen}。")
    return out


if __name__ == "__main__":
    import sys

    meth = sys.argv[1] if len(sys.argv) > 1 else "mock"
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else WAIT_CARD_SEC
    try:
        out = run(emit=_cli_emit, method=meth, wait_sec=wait)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

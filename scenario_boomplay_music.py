"""BoomPlay 卡片：最近音乐卡片。

触发方式（用户提供）：
  1. 进入 Boomplay，随机播放一首海外音乐歌曲（播放 10 秒左右）
  2. mock 触发最近播放音乐卡片：

        adb shell
        am start-foreground-service --user 0 \\
          -a "core.intent.action.DISPATCH_EVENT" \\
          --es "data_type" "AppSuggestEvent" \\
          --es "action_type" "listener" \\
          --es "json_data" '{"app_list":["com.afmobi.boomplayer"]}'

  3. 打开手机系统蓝牙开关，再用 mock 连接蓝牙耳机（没有耳机也照发）：

        adb shell
        am start-foreground-service --user 0 \\
          -a "core.intent.action.DISPATCH_EVENT" \\
          --es "data_type" "HEADSET_PLUG" \\
          --es "action_type" "listener" \\
          --es "json_data" '{"state":1,"type":1}'

  4. 卡片就能出来

再次触发：
  1. 设置调整系统时间 两个小时以后 或者 隔天
  2. 进入 Boomplay
  3. mock 触发
  4. 打开手机蓝牙开关，连接蓝牙耳机
  5. 显示卡片

频率控制：
  · 每天最多出现 2 次卡片
  · 卡片触发后，2 小时后才可再次触发

这里的「频率控制」是**设备侧**的出卡规则（智慧建议引擎自己限流），
自动化必须配合它才看得到卡片：所以「再次触发」第一步就是把系统时间
往前拨（两小时后或隔天），既满足 2 小时冷却，也让「每天 2 次」重新计数。
本模块另外在本地记一份触发历史（boomplay_music_state.json），好在你忘了
拨时间时直接拦下来，而不是白跑一轮等不到卡片。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from datetime import timedelta
from pathlib import Path

import fast_clock
from phone_ctl import KEY_HOME, Device, UiError

from scenario_birthday import (
    Runner,
    _cli_emit,
    _prepare,
    device_date,
    ensure_home_before_confirm,
    set_system_datetime,
)

BOOM_PACKAGE = "com.afmobi.boomplayer"
BOOM_LABEL = "Boomplay"

# ── 频率控制（设备侧出卡规则，自动化按它来配合） ─────────────────
DAILY_LIMIT = 2                 # 每天最多出现 2 次卡片
COOLDOWN_SEC = 2 * 3600         # 卡片触发后 2 小时才可再次触发
_FREQ_FILE = Path(__file__).with_name("boomplay_music_state.json")

# 连蓝牙耳机的 mock 载荷（没有耳机也照发，系统照样出卡）
HEADSET_PLUG_JSON = '{"state":1,"type":1}'


# ═══════════════════════════════════════════════════════════════════
#   DISPATCH_EVENT 通用投递
# ═══════════════════════════════════════════════════════════════════

# ── DISPATCH_EVENT 的两条通道 ────────────────────────────────────
# 通道 1（用户给的原命令）：core.intent.action.DISPATCH_EVENT
#   → 要 com.example.tpk.client/.RuleMockService，只在刷了 TPK 测试包的机器上有。
# 通道 2（实测可用）：brain.intent.action.DISPATCH_EVENT
#   → com.transsion.atomicbrain/.debug.DebugService，logcat 可见
#     TAB.DebugService: onAction:ACTION_DISPATCH_EVENT。
CORE_ACTION = "core.intent.action.DISPATCH_EVENT"
BRAIN_ACTION = "brain.intent.action.DISPATCH_EVENT"
BRAIN_COMPONENT = "com.transsion.atomicbrain/.debug.DebugService"


def _dispatch_event(dev: Device, data_type: str, payload: dict) -> str:
    """把一条 mock 事件发给 DISPATCH_EVENT，返回 shell 的原始输出。

    通道 2 **只能用 am start-service**：DebugService 不调 Service.startForeground()，
    用 am start-foreground-service 会在 5 秒后抛
    `ForegroundServiceDidNotStartInTimeException: Context.startForegroundService()
    did not then call Service.startForeground()` 并弹「Application Error」
    对话框把桌面焦点抢走（实测已复现）。
    """
    data = json.dumps(payload, separators=(",", ":"))
    tail = (
        f'--es "data_type" "{data_type}" '
        '--es "action_type" "listener" '
        f'--es "json_data" \'{data}\''
    )

    # 通道 1：用户给的原命令（隐式启动，有 TPK 测试包的机器才收得到）
    out = dev.shell(
        f'am start-foreground-service --user 0 -a "{CORE_ACTION}" {tail}')
    if _dispatch_ok(out):
        dev.log(f"mock 投递 {data_type} {data}（通道 core.intent.action，原命令）")
        return out

    # 通道 2：TransAtomicBrain 的 DebugService（显式组件 + start-service）
    out2 = dev.shell(
        f'am start-service --user 0 -n {BRAIN_COMPONENT} '
        f'-a "{BRAIN_ACTION}" {tail}')
    dev.log(
        f"mock 投递 {data_type} {data}\n"
        f"  通道 core.intent.action 没人接收（{out.strip()[:90]}）\n"
        f"  改走 TransAtomicBrain DebugService（brain.intent.action + "
        f"am start-service）：{out2.strip()[:90]}")
    return out2


def _dispatch_ok(out: str) -> bool:
    """这条 mock 投递有没有真的送达。

    注意：没装 com.example.tpk.client 的机器上 query-services 返回
    "No services found"，回退隐式启动必然报 "Not found; no service started."，
    这种情况**不算失败**——卡片由 App 自身触发，mock 只是加速器。
    """
    bad = ("Not found" in out or "no service started" in out
           or "Exception" in out)
    return not bad


def dispatch_boomplay(dev: Device, package: str = BOOM_PACKAGE) -> str:
    """mock：最近播放音乐卡片（AppSuggestEvent）"""
    return _dispatch_event(dev, "AppSuggestEvent",
                           {"app_list": [package]})


def dispatch_headset_plug(dev: Device) -> str:
    """mock：连接蓝牙耳机（HEADSET_PLUG，state=1 表示插入/连接）"""
    return _dispatch_event(dev, "HEADSET_PLUG",
                           {"state": 1, "type": 1})


def _grant_preflight(dev: Device, r: Runner, package: str) -> None:
    """把出卡规则要的权限先配好，免得规则卡在最后一条 ability 上。

    实测（X6765，规则 10022 = atomic_switch_item_boomplayer_recent）：
      ability  9 AppSuggestAbility      values=[com.afmobi.boomplayer], app_rank=2
      ability 13 AppInstallCheckAbility 要求该包已装
      ability 21 MinTimeIntervalAbility 2 小时（HOUR）冷却
      ability 22 DayCountAbility        每天最多 2 次
      ability 25 PermissionCheckAbility com.transsion.atomicbrain.action.BLUETOOTH
    Boomplay 的 POST_NOTIFICATIONS 默认是 granted=false / appops=ignore，
    这里一并放开。
    """
    dev.shell(f"pm grant {package} android.permission.POST_NOTIFICATIONS")
    dev.shell(f"appops set {package} POST_NOTIFICATION allow")
    dev.shell("svc bluetooth enable")
    r.log(f"已放开 {package} 通知权限，并打开蓝牙开关")


# ═══════════════════════════════════════════════════════════════════
#   频率控制
# ═══════════════════════════════════════════════════════════════════

def _freq_load() -> dict:
    try:
        return json.loads(_FREQ_FILE.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001  第一次跑 / 文件被删，当空记录
        return {}


def _freq_save(st: dict) -> None:
    try:
        _FREQ_FILE.write_text(
            json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise UiError(f"写不了频率记录 {_FREQ_FILE.name}：{exc}")


def _device_epoch(dev: Device) -> int:
    raw = dev.shell("date +%s").strip()
    m = re.search(r"\d+", raw)
    return int(m.group()) if m else 0


def _freq_guard(dev: Device, r: Runner, gap: str) -> dict:
    """按频率控制校验一次触发是否允许。

    只有「不改时间」这一档才可能被拦：其它两档会把系统时间往前拨，
    冷却和每日额度都被时间跳跃满足了，这正是它们存在的意义。
    """
    st = _freq_load()
    today = device_date(dev).isoformat()
    if st.get("date") != today:
        st = {"date": today, "count": 0, "last_epoch": 0}

    count = int(st.get("count") or 0)
    last = int(st.get("last_epoch") or 0)
    now = _device_epoch(dev)
    elapsed = max(0, now - last) if last else COOLDOWN_SEC

    r.log(f"频率控制：今天已触发 {count}/{DAILY_LIMIT} 次，"
          f"距上次 {elapsed // 60} 分钟（冷却 {COOLDOWN_SEC // 60} 分钟）")

    if gap == "skip":
        if count >= DAILY_LIMIT:
            raise UiError(
                f"今天已经触发 {count} 次，达到「每天最多 {DAILY_LIMIT} 次」的"
                f"频率控制上限。把间隔改成「两小时后」或「隔天」就能继续。")
        if elapsed < COOLDOWN_SEC:
            raise UiError(
                f"距上次触发才 {elapsed // 60} 分钟，不到 "
                f"{COOLDOWN_SEC // 60} 分钟冷却（卡片触发后 2 小时才可再次触发）。"
                f"把间隔改成「两小时后」或「隔天」就能继续。")
    return st


def _freq_record(dev: Device) -> None:
    st = _freq_load()
    today = device_date(dev).isoformat()
    if st.get("date") != today:
        st = {"date": today, "count": 0, "last_epoch": 0}
    st["count"] = int(st.get("count") or 0) + 1
    st["last_epoch"] = _device_epoch(dev)
    _freq_save(st)


# ═══════════════════════════════════════════════════════════════════
#   时间跳跃（满足频率控制）
# ═══════════════════════════════════════════════════════════════════

def _jump_time(dev: Device, r: Runner, gap: str) -> str:
    """把系统时间往前拨，满足「2 小时冷却」或「每天 2 次」。

    gap="2h"       → 拨到 2 小时后（过冷却）
    gap="next_day" → 拨到隔天（重置每日额度，也顺带过了冷却）
    gap="skip"     → 不拨（首次触发用）
    返回拨完之后的设备时间描述。
    """
    if gap == "skip":
        r.log("不调整系统时间（首次触发，直接跑）")
        return device_date(dev).isoformat()

    tz = fast_clock.device_timezone(dev)
    now = dt.datetime.fromtimestamp(_device_epoch(dev), tz)

    if gap == "next_day":
        target_dt = now + timedelta(days=1)
        why = "隔天"
    else:
        target_dt = now + timedelta(seconds=COOLDOWN_SEC)
        why = "2 小时后"

    set_system_datetime(dev, r, target_dt.date(), target_dt.hour, target_dt.minute)
    return f"{target_dt.date()} {target_dt.hour:02d}:{target_dt.minute:02d}（{why}）"


# ═══════════════════════════════════════════════════════════════════
#   Boomplay 操作
# ═══════════════════════════════════════════════════════════════════

_PLAY_HINTS = ("播放", "随机播放", "play", "shuffle", "播 放")
# bottom_play_button 是迷你播放条上的播放/暂停键，Boomplay 各版本里最稳的一个
_PLAY_RIDS = ("bottom_play_button", "btn_play", "iv_play", "play_btn",
              "btn_shuffle", "iv_shuffle", "btn_play_all", "fab_play",
              "iv_play_ctrl", "play_ctrl")

# 首启门槛候选：EULA 勾选 + 同意 → 全屏广告关闭键 → 权限/更新弹窗
_GATE_RIDS = ("iv_check", "bt_ok", "ad_self_btn_close_id", "iv_close",
              "btn_close", "btn_ok", "btn_agree", "btn_allow")
_GATE_TEXTS = ("立即享受音乐", "关闭广告并继续打开应用", "关闭广告", "同意并继续",
               "我知道了", "开始体验", "稍后再说", "允许", "始终允许",
               "Allow", "Allow all")
_GATE_DESCS = ("Close", "close-button", "关闭")


def _focus_blob(dev: Device) -> str:
    """mCurrentFocus + mFocusedApp 两行一起看。

    下拉通知栏盖住 Activity 时 mCurrentFocus 只剩 NotificationShade，
    但 mFocusedApp 仍是真正前台的 Activity —— 只看前者会误判成「没进来」。
    """
    return dev.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'") or ""


def _wait_focus_any(dev: Device, needle: str, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    last = ""
    while True:
        last = _focus_blob(dev)
        if needle in last:
            return last
        if time.time() >= deadline:
            raise UiError(f"等待窗口 {needle!r} 超时（{timeout:.0f} 秒），当前 {last[:160]!r}")
        time.sleep(0.4)


def _tap_any_gate(dev: Device) -> str | None:
    """点掉一个「挡路」弹窗：EULA 勾选/同意、全屏广告关闭键、权限与更新弹窗。"""
    nodes = dev.dump()
    for rid in _GATE_RIDS:
        hit = dev.find_opt(nodes=nodes, rid=rid)
        if hit:
            dev.tap_node(hit)
            return f"rid={rid}"
    for label in _GATE_TEXTS:
        hit = dev.find_opt(nodes=nodes, text=label)
        if hit:
            dev.tap_node(hit)
            return f"text={label}"
    for label in _GATE_DESCS:
        hit = dev.find_opt(nodes=nodes, desc=label)
        if hit:
            dev.tap_node(hit)
            return f"desc={label}"
    return None


def _dismiss_gates(dev: Device, r: Runner, rounds: int = 6) -> None:
    """把 Boomplay 首启门槛清干净：EULA → 全屏广告 → 权限/更新弹窗 → 主界面。"""
    for _ in range(rounds):
        blob = _focus_blob(dev)
        if "MainActivity" in blob:
            return
        hit = _tap_any_gate(dev)
        if hit:
            r.log(f"关掉启动弹窗（{hit}）")
            time.sleep(1.6)
            continue
        if "AdActivity" in blob:
            # 全屏广告的 uiautomator dump 几乎为空（WebView 只给 android:id/content），
            # 找不到关闭键就先点右上角常见关闭位，再不行退一步。
            w, h = dev.screen_size()
            dev.tap(int(w * 0.92), int(h * 0.055))
            time.sleep(1.2)
            if "AdActivity" in _focus_blob(dev):
                dev.key(4)
            r.log("全屏广告页：点了右上角关闭位，必要时退一步")
            time.sleep(1.6)
            continue
        r.log(f"启动门槛检查结束（当前窗口：{blob[:120]!r}）")
        return


def _open_boomplay(dev: Device, r: Runner, package: str = BOOM_PACKAGE) -> None:
    # 先唤醒 + 收起下拉通知栏，否则 monkey 注入成功了焦点仍停在 NotificationShade
    dev.shell("input keyevent 224")   # KEYCODE_WAKEUP
    dev.shell("cmd statusbar collapse")
    dev.key(KEY_HOME)
    time.sleep(0.6)
    dev.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
    try:
        _wait_focus_any(dev, package, timeout=20.0)
    except UiError:
        # 通知栏可能又弹下来了，收一次再等一轮
        dev.shell("cmd statusbar collapse")
        time.sleep(0.8)
        _wait_focus_any(dev, package, timeout=20.0)
    time.sleep(1.0)  # 等页面动画落定再找播放入口
    _dismiss_gates(dev, r)
    # 首页可能停在「无网络连接」错误页，有个「刷新」按钮
    n = dev.find_opt(rid="refresh")
    if n:
        dev.tap_node(n)
        r.log("Boomplay 首页是错误页，点了「刷新」")
        time.sleep(3.0)
    r.ok(f"已进入 {BOOM_LABEL}")


def _playing(dev: Device) -> bool:
    """media_session 里 Boomplay 是不是真的在播。"""
    out = dev.shell("dumpsys media_session") or ""
    return BOOM_PACKAGE in out and "state=PLAYING" in out


def _play_a_track(dev: Device, r: Runner, seconds: int) -> bool:
    """随机播放一首歌，播几秒。返回是否确认真的开始播了。

    Boomplay 各版本控件名不一样，这里按 resource-id → 文字/描述 → 屏幕中央
    三级兜底；点完再看 media_session 有没有变 PLAYING，没变就补点一次
    播放条上的播放键。没播起来只是「进 App 没播歌」，不影响后续 mock 触发，
    所以只提示不报错。
    """
    nodes = dev.dump()
    tapped = ""
    for rid in _PLAY_RIDS:
        hit = dev.find_opt(nodes=nodes, rid=rid)
        if hit:
            dev.tap_node(hit)
            tapped = f"rid={rid}"
            break
    if not tapped:
        for n in nodes:
            blob = f"{n.text or ''} {n.desc or ''}".lower()
            if any(h in blob for h in _PLAY_HINTS):
                dev.tap_node(n)
                tapped = f"text={n.text or n.desc}"
                break
    if tapped:
        r.ok(f"点了播放入口（{tapped}）")
    else:
        w, h = dev.screen_size()
        dev.tap(w // 2, h // 2)
        tapped = "屏幕中央"
        r.log("没认出播放按钮，点了屏幕中央碰运气")

    for _ in range(3):
        time.sleep(1.0)
        if _playing(dev):
            r.ok("Boomplay 已确认开始播放")
            return True

    # 没播起来：迷你播放条上的播放键再点一次
    n = dev.find_opt(rid="bottom_play_button")
    if n and tapped != "rid=bottom_play_button":
        dev.tap_node(n)
        time.sleep(2.0)
        if _playing(dev):
            r.ok("Boomplay 已确认开始播放（补点播放键）")
            return True

    r.log(f"提示：media_session 里没看到 PLAYING（已点 {tapped}），"
          f"按设计继续放着等 {seconds} 秒；无网络或没有可用音源时会这样")
    return False


def _bluetooth_on(dev: Device, r: Runner) -> None:
    """打开手机系统蓝牙开关，并核对确实打开了。"""
    before = dev.shell("settings get global bluetooth_on").strip()
    if before == "1":
        r.ok("蓝牙已经开着")
        return

    dev.shell("svc bluetooth enable")
    time.sleep(1.2)
    if dev.shell("settings get global bluetooth_on").strip() != "1":
        # 某些系统 svc 不生效，换 bluetooth_manager
        dev.shell("cmd bluetooth_manager enable")
        time.sleep(1.5)

    after = dev.shell("settings get global bluetooth_on").strip()
    if after == "1":
        r.ok("蓝牙已打开")
    else:
        # 开不起来也照发 HEADSET_PLUG：mock 本身就是「没有耳机」时的替代手段
        r.log(f"提示：蓝牙开关没变成 1（当前 {after!r}），"
              "继续发 HEADSET_PLUG mock（设计上没有耳机也照发）")


# ═══════════════════════════════════════════════════════════════════
#   主流程
# ═══════════════════════════════════════════════════════════════════

def run(dev: Device | None = None, emit=None, *, gap: str = "2h",
        wait_sec: int = 30, play_sec: int = 10,
        app_package: str = BOOM_PACKAGE,
        control: dict | None = None,
        confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    if gap not in ("2h", "next_day", "skip"):
        raise UiError(f"间隔 gap 只能是 2h / next_day / skip，收到 {gap!r}")
    if not (5 <= int(wait_sec) <= 300):
        raise UiError("wait_sec 必须在 5~300 秒之间")
    if not (3 <= int(play_sec) <= 120):
        raise UiError("play_sec 必须在 3~120 秒之间")
    wait_sec, play_sec = int(wait_sec), int(play_sec)

    result = {"package": app_package, "gap": gap,
              "wait_sec": wait_sec, "play_sec": play_sec}

    # ── 1. 频率控制校验 ────────────────────────────────────────────
    r.step("按频率控制校验触发资格")
    _freq_guard(dev, r, gap)
    r.ok(f"允许触发（每天最多 {DAILY_LIMIT} 次，冷却 {COOLDOWN_SEC // 60} 分钟）")

    # ── 2. 时间跳跃（再次触发的第一步） ────────────────────────────
    if gap != "skip":
        r.step("调整系统时间到可再次触发的时刻")
        result["time_jumped_to"] = _jump_time(dev, r, gap)
        r.ok(f"系统时间已拨到 {result['time_jumped_to']}")

    # ── 3. 进 Boomplay 随机播放 ────────────────────────────────────
    r.step(f"进入 {BOOM_LABEL} 并随机播放一首海外音乐")
    _open_boomplay(dev, r, app_package)
    _play_a_track(dev, r, play_sec)
    for remain in range(play_sec, 0, -1):
        r.check()
        r.tick(remain)
        time.sleep(1)

    # ── 4. mock 触发最近播放音乐卡片 ──────────────────────────────
    r.step("回桌面并保持亮屏")
    _prepare(dev, r)
    dev.key(KEY_HOME)
    time.sleep(0.6)
    dev.stayon(True)

    r.step("mock 触发最近播放音乐卡片（AppSuggestEvent）")
    out = dispatch_boomplay(dev, app_package)
    if _dispatch_ok(out):
        r.ok(out.strip()[:200])
    else:
        r.log("提示：AppSuggestEvent 投递未成功（"
              f"{out.strip()[:160]}），这台机器没有 DISPATCH_EVENT mock 服务；"
              "卡片由 App 自身触发，继续往下走")

    # ── 5. 配权限 + 打开蓝牙 + mock 连接蓝牙耳机 ─────────────────
    r.step("打开手机系统蓝牙开关")
    _grant_preflight(dev, r, app_package)
    _bluetooth_on(dev, r)

    r.step("mock 连接蓝牙耳机（HEADSET_PLUG）")
    out = dispatch_headset_plug(dev)
    if _dispatch_ok(out):
        r.ok(out.strip()[:200])
    else:
        r.log("提示：HEADSET_PLUG 投递未成功（"
              f"{out.strip()[:160]}），继续等待出卡")

    # ── 6. 等卡片 ─────────────────────────────────────────────────
    r.step(f"等待 {wait_sec} 秒检查最近音乐卡片")
    for remain in range(wait_sec, 0, -1):
        r.check()
        r.tick(remain)
        time.sleep(1)
    time.sleep(1.0)
    ensure_home_before_confirm(dev, r)
    r.shot("最近音乐卡片")

    r.step("确认最近音乐卡片是否出现")
    if not r.confirm():
        r.log("桌面未确认，展开通知栏再检查")
        dev.shell("cmd statusbar expand-notifications")
        time.sleep(1.0)
        r.shot("通知栏")
        ok = r.confirm()
        dev.shell("cmd statusbar collapse")
        time.sleep(0.4)
        if not ok:
            raise UiError("桌面和通知栏都没有确认到最近音乐卡片")
    ensure_home_before_confirm(dev, r)
    r.ok("已确认最近音乐卡片")

    # ── 7. 记账（频率控制） ────────────────────────────────────────
    _freq_record(dev)
    st = _freq_load()
    result["triggered_today"] = f"{st.get('count')}/{DAILY_LIMIT}"

    dev.stayon(False)
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (
        f"完成。已通过 mock 触发「最近音乐卡片」：{BOOM_LABEL} 播放 "
        f"{play_sec} 秒 → AppSuggestEvent → 开蓝牙 → HEADSET_PLUG，"
        f"桌面已确认卡片。今天第 {st.get('count')}/{DAILY_LIMIT} 次，"
        f"{COOLDOWN_SEC // 60} 分钟后可再次触发。")
    return result


if __name__ == "__main__":
    import sys

    g = sys.argv[1] if len(sys.argv) > 1 else "2h"
    try:
        out = run(emit=_cli_emit, gap=g)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

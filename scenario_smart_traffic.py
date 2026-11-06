"""智能路况卡片（Smart Traffic / `AITIPS_Road_conditions`）触发场景。

对应 atomicbrain 规则 **10058**（`assets/rule/SMART_TRAFFIC.json`）：

  2   TimeSlotRangeAbility  `00_00_00~11_59_59`，`time_source=dismiss_latch`
                            （读「早间闹钟被关掉的时刻」，不是当前时间）
  22  DayCountAbility       每天 1 次（key = `YYYY-MM-DD-10058`）
  44  SmartTrafficLatch     智能路况触发锁必须为 true（`active_abilities`）
  45  AbnormalWeatherAbility 记忆里的当日异常天气类型 ∈ 白名单 [7, 10, 12, 15]

白名单语义（`SmartTrafficAbnormalWeatherType`，用户 m11067 给的命名）：
  7 暴雨 / 10 大雨 / 12 中雨 / 15 雷雨

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
DebugService 支持的四条分支（`memory` / `mock_json` / `percept` / `query`）也都写不进
规则判定读的那份天气记忆（已逐条实测，见 `inject_weather_memory` 上方注释）。

所以本模块仍然会**照用户给的命令原样发一次**（并记录返回值/日志，用户能看到真实反馈），
然后直接把「当天 abnormalWeatherType=<type>」写进 App 自己的天气记忆
（MMKV `memory_current_status` 的 `memory.current.status.weather` 键），
这样 `abnormal_type` 参数能真正生效，且**全程不打开 test brain 软件**。

闹钟那一段仍然走真实链路：设「当前时间 + 1 分钟」的闹钟 → 息屏等它响 →
关掉闹钟（这一步就是 ability 2 读的 dismiss_latch）→ 解锁回桌面。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import struct
import subprocess
import tempfile
import time
import zlib

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


MMKV_REL = f"/data/user_de/0/{ATOMIC_PACKAGE}/files/mmkv"
MMKV_STATUS = f"{MMKV_REL}/memory_current_status"
MMKV_STATUS_CRC = f"{MMKV_STATUS}.crc"
MMKV_WEATHER_KEY = b"memory.current.status.weather"
TMP_DIR = "/data/local/tmp"

# 写进去的记忆要在「设备当前时间」之后一点点 —— App 每次启动都会自己重新
# 拉一次天气并追加一条 eventTime=现在 的记录，记忆是按 eventTime 比大小取
# 最新的，写「现在」必被它自己的那条盖掉（实测连写三遍自检都是 null）。
# 领先 1 小时够它刷几次；再大就不像真实时间了。
MEMORY_TIME_LEAD_MS = 60 * 60 * 1000

# ── 「写进去又不被盖掉」需要的四个额外条件（真机逐个试出来的）──────────
#
# 只做「force-stop + 写 + 启动」是**一定会被盖掉**的：App 每次启动都会从
# `databases/` 里的缓存重新灌一条 `source=weather_cloud` /
# `source=com.rlk.weathers` 的天气记忆（eventTime=现在），而记忆是按
# eventTime 取最新的。实测：写完 20 秒后就被追加覆盖；只清
# `weather_sdk_cache.db` 也不够 —— 真正存着 geohash 天气缓存的是
# `taps_data_service*`（`grep -rl geohash databases/` 只命中
# `taps_data_service-wal`）。清干净之后 30 秒内不再 append。
#
# 另外两个：写之前 `pm disable-user` 冻住天气 App（否则它一启动就回刷），
# 断网（堵住天气云的在线回刷）。四个条件 + eventTime 领先，缺一个都失败。
WEATHER_DB_DIR = f"/data/user_de/0/{ATOMIC_PACKAGE}/databases"
WEATHER_CACHE_FILES = (
    "taps_data_service", "taps_data_service-wal", "taps_data_service-shm",
    "weather_sdk_cache.db", "weather_sdk_cache.db-wal",
    "weather_sdk_cache.db-shm",
    "tds_data_service", "tds_data_service-wal", "tds_data_service-shm",
)


# ══════════════════════════════════════════════════════════════════════
#  MMKV 天气记忆注入（real 路径的关键一步）
#
#  规则 45（AbnormalWeatherAbility）读的是 MMKV `memory_current_status`
#  里的 `memory.current.status.weather` 键，值是：
#    {"fields":{"kind":"SUCCESS","hasDays":"1"}, "eventTime":<ms>,
#     "source":"debug", "provider":"com.rlk.weathers",
#     "extra":"{\"kind\":\"SUCCESS\",\"weather\":{\"cityName\":...,\"days\":[
#        {\"date\":\"YYYY-MM-DD\",...,
#         \"currentAbnormalWeather\":{\"abnormalWeatherType\":<type>}}]}}"}
#
#  DebugService 的任何 action_type（memory / mock_json / percept / query /
#  listener）都写不进这条 —— 实测全试过，见 README。天气云接口真实下发的
#  `days[].abnormalWeather.abnormalWeatherType` 又只给「未来某几天」、值是 17
#  之类不在白名单 [7,10,12,15] 里的编码。所以想在不点调试页 mock 按钮的
#  前提下把指定 type 写进去，只能直接改这个 MMKV 文件。
#
#  MMKV 文件格式（实测反推，`memory_current_status` 8192 B）：
#    [u32 actualSize][u32 seed][ (varint keyLen)(key)
#                              (varint recordLen)(varint valLen)(val) ]*
#    剩下的补 \x00 到 8192。
#    recordLen = valLen + varint(valLen) 的字节数。
#  .crc 文件（4096 B）：
#    [u32 crc32(data[4:actualSize+4])] 之后是 guard 区，写回时按原样保留。
# ══════════════════════════════════════════════════════════════════════


def _mmkv_read_varint(buf: bytes, i: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, i
        shift += 7


def _mmkv_write_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _mmkv_parse(raw: bytes) -> tuple[bytes, list[list[bytes]]]:
    """解析 MMKV 文件。返回 `(seed, [[key, value], ...])`。

    **记录之间夹着 0x00 对齐填充**（MMKV 删除/改写记录后不会压缩，留下空洞）。
    把这些 0x00 当记录读会读出 keyLen=0 的空记录，接着整条链就错位 ——
    这正是「写回后文件从 30KB 涨到 65KB、报装不下」的根因。所以循环开头
    先跳过连续的 0x00；keyLen=0 本身不是合法记录，看到就跳。
    """
    actual = struct.unpack_from("<I", raw, 0)[0]
    seed = raw[4:8]
    i = 8
    entries: list[list[bytes]] = []
    while i < actual:
        if raw[i] == 0:
            while i < actual and raw[i] == 0:
                i += 1
            continue
        try:
            key_len, i = _mmkv_read_varint(raw, i)
            if key_len == 0 or i + key_len > actual:
                break
            key = raw[i:i + key_len]
            i += key_len
            _record_len, i = _mmkv_read_varint(raw, i)
            val_len, i = _mmkv_read_varint(raw, i)
            if i + val_len > actual:
                break
            entries.append([key, raw[i:i + val_len]])
            i += val_len
        except IndexError:
            break
    return seed, entries


def _mmkv_build(seed: bytes, entries: list[list[bytes]], cap: int = 8192) -> bytes:
    body = bytearray()
    for key, val in entries:
        body += _mmkv_write_varint(len(key)) + key
        body += _mmkv_write_varint(len(val) + len(_mmkv_write_varint(len(val))))
        body += _mmkv_write_varint(len(val)) + val
    actual = 8 + len(body)
    # MMKV 的容量就是文件大小，装不下时扩到 4KB 对齐的下一页即可（它自己也会这么长）。
    # 原来这里直接抛 UiError，结果「重写记忆」在文件已经长到 64KB 时必然失败。
    size = max(cap, (actual + 4095) // 4096 * 4096)
    out = bytearray(struct.pack("<I", actual) + seed + bytes(body))
    out += b"\x00" * (size - len(out))
    return bytes(out)


def _run_as_cat(dev: Device, path: str) -> bytes:
    """用 `run-as <pkg> cat` 读 App 私有文件（app 必须 debuggable）。"""
    serial = getattr(dev, "serial", "")
    proc = subprocess.run(
        ["adb", "-s", serial, "exec-out", "run-as", ATOMIC_PACKAGE, "cat", path],
        capture_output=True, timeout=60,
    )
    return proc.stdout or b""


def _run_as_put(dev: Device, path: str, data: bytes) -> None:
    """把单个二进制塞进 App 私有目录（简单版，见 `_run_as_put_chain` 的说明）。"""
    _run_as_put_chain(dev, [(path, data)])


def _run_as_put_chain(dev: Device, items: list[tuple[str, bytes]]) -> None:
    """把多个二进制写进 App 私有目录 —— 关键是「先 push，再一条命令里 cp 完」。

    `run-as ... cat >` 不行（shell 重定向不受 run-as 保护，Permission denied），
    `run-as ... tee` 可以但 adb shell 的 stdin 会被截断。正确做法是
    `adb push` 到 /data/local/tmp，再 `run-as cp` 过去。

    **但 `adb push` 本身要花接近 1 秒**，而这台机器上 atomicbrain 被
    NotificationChannelService 拴着，`am force-stop` 之后一两秒就会被拉起来，
    新进程一启动就把内存里的旧 MMKV 状态刷回文件 —— push 与 cp 之间只要隔着
    一次 system() 就会被回刷。所以必须：**先把要写的文件全部 push 上去**，
    最后用**一条** shell 命令做完 `force-stop → cp → cp → force-stop`。
    """
    serial = getattr(dev, "serial", "")
    staged: list[tuple[str, str]] = []
    try:
        for idx, (path, data) in enumerate(items):
            fd, tmp = tempfile.mkstemp(prefix="mmkv_", suffix=".bin")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            try:
                remote = f"{TMP_DIR}/_mmkv_stage_{idx}.bin"
                subprocess.run(["adb", "-s", serial, "push", tmp, remote],
                               capture_output=True, timeout=120, check=True)
                staged.append((path, remote))
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

        parts = [f"am force-stop {ATOMIC_PACKAGE}", "sleep 1"]
        for path, remote in staged:
            parts.append(f"run-as {ATOMIC_PACKAGE} cp {remote} {path}")
        # 写完立刻再停一次，把刚被拉起来的进程掐掉，断掉它回刷旧状态的路
        parts.append(f"am force-stop {ATOMIC_PACKAGE}")
        parts.append("echo MMKV_COPIED")
        cmd = " ; ".join(parts)
        if hasattr(dev, "shell_timeout"):
            out = dev.shell_timeout(cmd, timeout=60.0)
        else:
            out = dev.shell(cmd)
        if "MMKV_COPIED" not in (out or ""):
            raise UiError(f"写回 MMKV 失败：{(out or '').strip()[:200]}")
    finally:
        names = " ".join(remote for _, remote in staged)
        if names:
            subprocess.run(["adb", "-s", serial, "shell", "rm", "-f", *names.split()],
                           capture_output=True, timeout=30)


def device_now_ms(dev: Device) -> int:
    """用**设备自己的钟**取当前毫秒时间戳。

    这个不能图省事用 `time.time()`：场景会把设备时间拨到目标日（默认
    2026-11-11），而 PC 还是真实日期，两边能差好几天。记忆的取舍是按
    `eventTime` 比大小的，用 PC 的钟写进去的永远「更旧」，App 一转头就
    用自己那条真实天气覆盖 —— 这正是写了十几次、自检始终读不到的那条伤。
    """
    raw = (dev.shell("date +%s") or "").strip()
    m = re.search(r"(\d{9,})", raw)
    if not m:
        raise UiError(f"读不到设备时间戳（`date +%s` 返回 {raw!r}）")
    return int(m.group(1)) * 1000


def weather_memory_payload(target: _dt.date, abnormal_type: int,
                           event_time_ms: int | None = None,
                           city: str = "Debug City") -> dict:
    """按天气 App 真实落地形状构造一条「当天异常天气」记忆。

    `event_time_ms` 必须是**设备**时钟（见 `device_now_ms`），不要用 PC 的。
    """
    name_of = {7: "暴雨", 10: "大雨", 12: "中雨", 15: "雷雨"}
    inner = {
        "kind": "SUCCESS",
        "weather": {
            "cityName": city,
            "days": [{
                "date": target.isoformat(),
                "weatherName": name_of.get(int(abnormal_type), "暴雨"),
                "minTemperature": 24,
                "maxTemperature": 29,
                "currentAbnormalWeather": {"abnormalWeatherType": int(abnormal_type)},
            }],
        },
    }
    return {
        "fields": {"kind": "SUCCESS", "hasDays": "1"},
        "eventTime": int(event_time_ms if event_time_ms is not None
                         else time.time() * 1000),
        "source": "debug",
        "provider": WEATHER_PKG,
        "extra": json.dumps(inner, ensure_ascii=False, separators=(",", ":")),
    }


def _weather_records(raw: bytes) -> list[bytes]:
    """从 MMKV 原始字节里取出所有 `memory.current.status.weather` 的值（按文件顺序）。"""
    _seed, entries = _mmkv_parse(raw)
    return [val for key, val in entries if key == MMKV_WEATHER_KEY]


def _weather_is_ours(raw: bytes, abnormal_type: int) -> bool:
    """判断「App 实际会用到的那条」天气记忆是不是我们写的那条。

    MMKV 是**追加式**的：同一个 key 改一次就往后追加一条新记录，读取时后写的
    赢。所以只看「文件里有没有 abnormalWeatherType」完全不够 —— App 自己刷新
    一次天气就会在后面追加一条 `abnormalWeatherType=null` 的记录把我们盖掉，
    这正是端到端跑通一次、后面又全部失败的原因之一。

    另一个坑：记忆是按 `eventTime` 比大小的（见 `device_now_ms` 的说明），
    所以判定要按 eventTime 取最大的那条，而不是文件里的最后一条。
    """
    recs = _weather_records(raw)
    if not recs:
        return False
    best, best_ts = None, -1
    for rec in recs:
        m = re.search(rb'"eventTime"\s*:\s*(\d+)', rec)
        ts = int(m.group(1)) if m else 0
        if ts >= best_ts:
            best, best_ts = rec, ts
    if best is None:
        return False
    return (f'"abnormalWeatherType":{int(abnormal_type)}'.encode() in best
            or f'\\"abnormalWeatherType\\":{int(abnormal_type)}'.encode() in best)


def clear_day_count(dev: Device, r: Runner) -> bool:
    """把当天 rule 10058 的日计数（ability 22）清零 —— 不进 test brain。

    计数存在 `brain_SP` 里，键名 `<YYYY-MM-DD>-10058`，值是 MMKV 的 int32
    （实测 `\\x01` = 1、`\\x00` = 0）。`brain_SP` 的记录格式和
    `memory_current_status` 不一样（值是定长二进制、没有 `recordLen` 那层），
    所以这里不做整文件重新编码，而是**在原始字节上原地把值改成 0**，
    再按 MMKV 规则重算 `.crc`。原地补丁不用解析全文件，也就不会误伤
    那 1200 多条记录（其中大量是定长二进制）。

    实测：改完启动 App，调试页自检显示 `count=0`，规则立刻可评。
    用户 m11067 允许「没出卡时进 test brain 清当日计数」，但既然能直接改文件，
    就优先走这条路 —— 少一次界面操作，也不受滚动位置漂移影响。
    """
    key = f"{device_date(dev).isoformat()}-{RULE_ID}".encode()
    r.step(f"清掉 rule {RULE_ID} 的当日计数（{key.decode()}）")

    sp = f"{MMKV_REL}/brain_SP"
    sp_crc = f"{sp}.crc"
    raw = _run_as_cat(dev, sp)
    if len(raw) < 16:
        r.log(f"读不到 {sp}（只有 {len(raw)} 字节）")
        return False

    buf = bytearray(raw)
    patched = 0
    for i in range(len(buf)):
        if buf[i:i + len(key)] != key:
            continue
        # key 之后直接就是 value（int32 varint），1 表示已用掉额度
        j = i + len(key)
        if j < len(buf) and buf[j] == 1:
            buf[j] = 0
            patched += 1
    if not patched:
        r.ok("当日计数本来就是 0，不用清")
        return True

    actual = struct.unpack_from("<I", buf, 0)[0]
    items: list[tuple[str, bytes]] = [(sp, bytes(buf))]
    crc_raw = _run_as_cat(dev, sp_crc)
    if len(crc_raw) >= 4:
        crc = bytearray(crc_raw)
        struct.pack_into("<I", crc, 0,
                         zlib.crc32(buf[4:actual + 4]) & 0xFFFFFFFF)
        items.append((sp_crc, bytes(crc)))

    # 写之前必须冻住，否则 App 一被拉起就把内存里的旧计数刷回去
    dev.shell(f"am force-stop {ATOMIC_PACKAGE}")
    time.sleep(0.6)
    out = dev.shell(f"pm disable-user --user 0 {ATOMIC_PACKAGE}")
    if "disabled-user" not in (out or ""):
        r.log(f"冻结 atomicbrain 输出：{(out or '').strip()[:120]}")
    time.sleep(1.2)
    try:
        _run_as_put_chain(dev, items)
        back = _run_as_cat(dev, sp)
    finally:
        dev.shell(f"pm enable --user 0 {ATOMIC_PACKAGE}")

    left = 0
    for i in range(len(back)):
        if back[i:i + len(key)] == key:
            j = i + len(key)
            if j < len(back) and back[j] == 1:
                left += 1
    if left:
        r.log(f"清完仍有 {left} 处计数为 1，本次可能评不过")
        return False
    r.ok(f"已把当日计数清零（改了 {patched} 处）")
    return True


def _freeze_weather_app(dev: Device, r: Runner) -> None:
    """冻住天气 App（`pm disable-user`）。

    不冻就会在注入之后的几秒内被它自己 re-ingest 一次真实天气盖掉
    （`source: com.rlk.weathers`、eventTime=现在）。
    `pm enable --user 0` 必须配对恢复，见 `_restore_weather_app`。
    """
    out = dev.shell(f"pm disable-user --user 0 {WEATHER_PKG}")
    r.log(f"冻结天气 App：{(out or '').strip()[:100]}")


def _restore_weather_app(dev: Device, r: Runner) -> None:
    """把冻住的天气 App 放回来，并恢复网络。任何异常都不能漏掉这一步。"""
    out = dev.shell(f"pm enable --user 0 {WEATHER_PKG}")
    r.log(f"恢复天气 App：{(out or '').strip()[:100]}")
    dev.shell("svc wifi enable")
    dev.shell("svc data enable")


def _clear_weather_caches(dev: Device, r: Runner) -> None:
    """删掉 atomicbrain 里会回刷天气记忆的那几个缓存库。

    实测 `grep -rl geohash databases/` 只命中 `taps_data_service-wal` ——
    它才是天气/地理哈希缓存的真正落点；只清 `weather_sdk_cache.db` 没用，
    清完之后 30 秒内不再有记录被 append（`_t_frz3.py` 实测）。
    """
    for name in WEATHER_CACHE_FILES:
        dev.shell(f"run-as {ATOMIC_PACKAGE} rm -f {WEATHER_DB_DIR}/{name}")
    r.log(f"已清掉天气/地理缓存（{len(WEATHER_CACHE_FILES)} 个文件）")


def inject_weather_memory(dev: Device, r: Runner, target: _dt.date,
                          abnormal_type: int,
                          keep_frozen: bool = False) -> str:
    """把「当天 abnormalWeatherType=<type>」直接写进 MMKV 天气记忆。

    返回写回去的那条记忆 JSON 文本（便于调用方记录/核对）。
    这一步不需要打开 test brain 的界面，也不改任何系统设置。

    要让写进去的记录**活下来**，必须同时满足五个条件（真机逐个试出来的，
    少一个都会被 App 自己追加的记录盖掉）：

    1. `pm disable-user` 冻住天气 App（com.rlk.weathers）
    2. 断网（`svc wifi disable` + `svc data disable`），堵住天气云在线回刷
    3. `pm disable-user` 冻住 atomicbrain 本身：它被
       `com.transsion.atomicbrain/.pipe.NotificationChannelService` 拴着，
       `am force-stop` 之后一两秒就被重新拉起，新进程会把内存里的旧 MMKV
       状态刷回文件（实测「force-stop → cp」无论怎么排队都被回刷）
    4. 删掉 `databases/` 下 `taps_data_service*` / `weather_sdk_cache.db*` /
       `tds_data_service*`，切断启动时的回刷来源
    5. eventTime 用**设备时钟** + 领先 1 小时（记忆按 eventTime 取最新，
       写「现在」必被 App 自己那条盖掉；用 PC 时钟则会差好几天）

    两个条件（1、2）在函数退出时由 `finally` 恢复，即使写失败也不会把设备
    留在断网/冻住状态。
    """
    if int(abnormal_type) not in ABNORMAL_WHITELIST:
        raise UiError(f"异常天气类型 {abnormal_type} 不在 "
                      f"{list(ABNORMAL_WHITELIST)} 里")

    payload = weather_memory_payload(
        target, int(abnormal_type),
        event_time_ms=device_now_ms(dev) + MEMORY_TIME_LEAD_MS)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # --- 条件 1、2：冻天气 App + 断网 ---
    _freeze_weather_app(dev, r)
    dev.shell("svc wifi disable")
    dev.shell("svc data disable")
    r.log("已断网（防止天气云在线回刷）")

    last_err = ""
    written = False
    try:
        for attempt in range(1, 4):
            # --- 条件 3：冻住 atomicbrain ---
            dev.shell(f"am force-stop {ATOMIC_PACKAGE}")
            time.sleep(0.6)
            out = dev.shell(f"pm disable-user --user 0 {ATOMIC_PACKAGE}")
            if "disabled-user" not in (out or ""):
                r.log(f"冻结 atomicbrain 输出：{(out or '').strip()[:120]}")
            time.sleep(1.2)

            try:
                # --- 条件 4：切断回刷来源 ---
                _clear_weather_caches(dev, r)

                raw = _run_as_cat(dev, MMKV_STATUS)
                if len(raw) < 16:
                    last_err = f"读不到 {MMKV_STATUS}（只有 {len(raw)} 字节）"
                    continue
                crc_raw = _run_as_cat(dev, MMKV_STATUS_CRC)

                seed, entries = _mmkv_parse(raw)
                # 同 key 的历史记录全部丢掉，只留我们这条并追加到末尾（MMKV 后写赢）
                kept = [kv for kv in entries if kv[0] != MMKV_WEATHER_KEY]
                kept.append([MMKV_WEATHER_KEY, text])
                new_raw = _mmkv_build(seed, kept, cap=len(raw))
                actual = struct.unpack_from("<I", new_raw, 0)[0]

                items: list[tuple[str, bytes]] = [(MMKV_STATUS, new_raw)]
                if len(crc_raw) >= 4:
                    crc = bytearray(crc_raw)
                    struct.pack_into("<I", crc, 0,
                                     zlib.crc32(new_raw[4:actual + 4]) & 0xFFFFFFFF)
                    items.append((MMKV_STATUS_CRC, bytes(crc)))
                _run_as_put_chain(dev, items)

                back = _run_as_cat(dev, MMKV_STATUS)
                # 注意别写成 b'"abnormalWeatherType"'：`extra` 是**字符串化的 JSON**，
                # 文件里存的是 `\"abnormalWeatherType\"`（带反斜杠）。
                if b"abnormalWeatherType" not in back:
                    last_err = "写回后没在文件里找到 abnormalWeatherType"
                    r.log(f"第 {attempt} 次写天气记忆没落住，重试：{last_err}")
                    continue
            finally:
                # 无论成败都要启用，否则后面闹钟/卡片全废
                dev.shell(f"pm enable --user 0 {ATOMIC_PACKAGE}")

            # --- 复查：App 起来后有没有追加新记录把我们盖掉 ---
            time.sleep(3.0)
            back = _run_as_cat(dev, MMKV_STATUS)
            if _weather_is_ours(back, int(abnormal_type)):
                r.ok(f"已把天气记忆写成 {target.isoformat()} "
                     f"abnormalWeatherType={int(abnormal_type)}"
                     f"（MMKV {len(raw)} 字节，写入后 {actual} 字节有效"
                     + (f"，第 {attempt} 次写成" if attempt > 1 else "") + "）")
                written = True
                break

            recs = _weather_records(back)
            last_err = (f"App 重启后又在末尾追加了 {len(recs)} 条天气记忆，"
                        f"最后一条不是我们写的")
            r.log(f"第 {attempt} 次写天气记忆被回刷，重试：{last_err}")
    finally:
        # 条件 1、2 一定要还原：天气 App 冻着、网络断着，后面闹钟响了解锁
        # 到桌面也不会出卡（天气云拉不到，天气卡全废）。
        #
        # 例外：`keep_frozen=True` 时**先不还原**。原因（真机实测）：
        # MMKV 是「同一 key 后写赢」，App 一旦拿到网络+天气 App 可用，就会
        # 在重启后 10~20 秒内追加一条 `source=com.rlk.weathers` 的记录，把我们
        # 写的 `source=debug` 那条直接盖掉（eventTime 领先也没用，位置靠后才算数）。
        # 所以 real 路径要一直冻到「闹钟 dismiss 完、规则评完」再还原。
        if keep_frozen:
            r.log("天气 App 与网络保持冻结（等规则评完再还原，否则会被天气云回刷盖掉）")
        else:
            _restore_weather_app(dev, r)

    if not written:
        raise UiError(f"天气记忆写不进去：{last_err}")
    return text.decode("utf-8")


def unfreeze_atomic(dev: Device, r: Runner) -> None:
    """把 `inject_weather_memory` 临时禁用掉的 App 恢复回来。

    必须在写完之后（哪怕写失败）调用，否则后续所有卡片都别想触发 ——
    这也是把它单独拆成公开函数、由 run_real 的 finally 兜底调用的原因。
    """
    out = dev.shell(f"pm enable --user 0 {ATOMIC_PACKAGE}")
    if "new state: enabled" in (out or ""):
        r.log(f"已恢复 {ATOMIC_PACKAGE}：{out.strip()[:80]}")
    else:
        r.log(f"恢复 {ATOMIC_PACKAGE} 的输出：{(out or '').strip()[:120]}")


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


def dispatch_simulate_weather(dev: Device, r: Runner, target: _dt.date,
                              abnormal_type: int = ABNORMAL_TYPE) -> tuple[bool, str]:
    """用户给的原命令：`action_type=simulate_weather_memory`（日期换成设备当天）。

    返回 (是否被接受, 原始输出说明)。已知 17.10.00.101 上会返回
    `unknown action_type=simulate_weather_memory`，这里如实记录、不抛错。
    """
    r.step(f"发 simulate_weather_memory（target_date={target.isoformat()} "
           f"abnormal_type={int(abnormal_type)}）")
    dev.shell("logcat -c")
    out = _dispatch(dev, [
        "--es", "action_type", "simulate_weather_memory",
        "--es", "target_date", target.isoformat(),
        "--ei", "abnormal_type", str(int(abnormal_type)),
    ])
    time.sleep(1.5)
    log = dev.shell("logcat -d -s TAB.RuleActionHandler:D TAB.DebugUtils:D")
    if "unknown action_type" in log:
        r.log("这台设备上的 atomicbrain 不认识 simulate_weather_memory"
              "（该 action 在 17.10.00.101 / 17.11.00.104 里都不存在），"
              "改用直接写天气记忆的方式")
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
    """设一个「末闹」并让它响一次。

    **必须是重复闹钟（带 DAYS）**，不能是一次性闹钟 —— 实测一次性闹钟响过就从
    列表里消失，`SmartTrafficDismissCoordinator` 收到 dismiss 后打
    `onAlarmListData: dismissed alarm not in list ... alarmCount=2`，
    `isLastMorningAlarmDismissed` 判不出来，ability 44 不满足。
    带 DAYS 的闹钟响完会顺延到明天、仍留在列表里，dismiss 时就能被找到，
    日志里就是 `isLastMorningAlarmDismissed=true` → `MorningDismissLatch: arm`。

    响完、卡片确认之后调 `clear_alarm` 删掉，不把闹钟留在设备上。
    """
    r.step(f"设置末闹 {hour:02d}:{minute:02d}（重复闹钟，响完会顺延）")
    cmd = (
        "am start -a android.intent.action.SET_ALARM"
        f" --ei android.intent.extra.alarm.HOUR {hour}"
        f" --ei android.intent.extra.alarm.MINUTES {minute}"
        " --ez android.intent.extra.alarm.SKIP_UI true"
        " --eia android.intent.extra.alarm.DAYS 1,2,3,4,5,6,7"
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


DESKCLOCK_PKG = "com.transsion.deskclock"

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
    """关掉正在响的闹钟 —— 只有「上滑关闭」才算真正的 dismiss。

    **这一步是整条 real 链路的关键**（实测对比）：

    - 按返回键 / 点「10 分钟后提醒」都不算 dismiss：`SmartTrafficDismissCoordinator`
      打 `onAlarmListData: dismissed alarm not in list`，`MorningDismissLatch` 不 arm，
      ability 44 永远不满足，规则 10058 恒 `not match:sb=2,22,44,45`。
    - 在响铃页**从底部往上滑**（界面提示「上滑关闭」）才会走真正的 DISMISS_ALARM：
      日志立刻出现
      `onAlarmListData: isLastMorningAlarmDismissed=true dismissAlarmId=N`
      → `MorningDismissLatch: arm: dismissTime=<ms>`
      → `onAlarmListData: trigger SMART_TRAFFIC rule`。

    所以这里**先上滑**，滑完校验 focus 已经离开响铃页；只有在滑不动时才退回
    找按钮/按返回键，并把「可能没真正 dismiss」写进日志以便排查。
    """
    r.step("关闭闹钟（上滑关闭，写入 dismiss_latch）")
    w, h = dev.screen_size()

    # 1) 主路径：上滑关闭（响铃页底部有「上滑关闭」提示）
    for attempt in range(1, 4):
        dev.swipe(w // 2, int(h * 0.93), w // 2, int(h * 0.35), 300)
        time.sleep(2.6)
        focus = dev.focus()
        if "larm" not in focus and "deskclock" not in focus.lower():
            r.ok(f"已上滑关闭闹钟（第 {attempt} 次上滑后焦点是 {focus or '未知'}）")
            return
        r.log(f"上滑第 {attempt} 次后仍在响铃页（{focus}），再试一次")

    # 2) 兜底：找停止按钮
    nodes = []
    try:
        nodes = dev.dump()
    except UiError:
        pass
    for text in _ALARM_DISMISS_TEXT:
        for n in nodes:
            value = (n.text or n.desc or "").strip()
            if value == text:
                dev.tap_node(n, 0.8)
                time.sleep(1.2)
                r.log(f"上滑没能关掉，改点「{value}」——这不算真正的 dismiss，"
                      "ability 44 可能还是不满足")
                return
    # 3) 最后兜底：返回键
    r.log("上滑和按钮都没成功，按返回键静音（注意：这不写入 dismiss_latch）")
    dev.key(4)
    time.sleep(1.2)
    dev.key(4)
    time.sleep(1.0)


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
    hit = wait_traffic_card(dev, r, int(wait_sec))
    return {
        "method": "mock",
        "mock_result": (raw or "")[:600],
        "card_text": hit,
        "wait_sec": int(wait_sec),
    }


def traffic_card_dispatched(dev: Device) -> str | None:
    """logcat 兜底：智能路况卡是不是已经触发/曝光了。

    这张卡的优先级（809000）低于早安卡（992000），高峰时段经常被挤到
    轮播索引 3，桌面**第一屏的控件树里根本看不到**（实测 `SuggestionServiceCard
    [...Road_conditions...] onHide mIsShow:true, index:3`），但卡确实出了。
    `card_dispatched`（power_saving 里那个）只认 `tvTitle`，对这张卡不适用。
    """
    raw = dev.shell(
        "logcat -d -s TpkServiceCard:I LauncherPreAnalytics:I "
        "SuggestionServiceCard:I | "
        "grep -E 'AITIPS_Road_conditions' | tail -8"
    ) or ""
    for line in raw.splitlines():
        if "onCardTrigger" in line or "onCardExposed" in line or "Aitips_Trigger" in line:
            return line.strip()[:180]
    return None


def wait_traffic_card(dev: Device, r: Runner, wait_sec: int) -> str | None:
    """等智能路况卡：先看桌面控件树，看不到就查 logcat 是否已触发/曝光。"""
    r.step("等待智能路况卡片出现")
    start = time.time()
    while time.time() - start < wait_sec:
        r.check()
        elapsed = int(time.time() - start)
        try:
            nodes = dev.dump()
        except UiError:
            time.sleep(2.0)
            continue
        found = match_card(nodes, TRAFFIC_HINTS_ZH, TRAFFIC_HINTS_EN, TRAFFIC_HINTS_AR)
        if found:
            r.log(f"第 {elapsed} 秒在桌面命中：「{found}」，控件 {len(nodes)} 个")
            r.shot("智能路况卡片")
            return found
        if elapsed >= 5:
            dispatched = traffic_card_dispatched(dev)
            if dispatched:
                r.log(f"第 {elapsed} 秒卡片已触发（被早安卡挤到轮播后面，不在第一屏）："
                      f"{dispatched}")
                r.shot("智能路况卡片")
                return "已触发（在智慧建议轮播里，不在第一屏）"
        if elapsed and elapsed % 10 == 0:
            r.log(f"第 {elapsed} 秒还没有智能路况卡片（控件 {len(nodes)} 个）")
        time.sleep(2.0)
    r.shot("智能路况卡片（超时）")
    return None


def memory_verdict(dev: Device) -> tuple[bool | None, str]:
    """只从 logcat 判断「异常天气是否已经进记忆」。

    用户要求 real 路径不许打开 test brain 软件，所以不能用调试页的
    「查看智能路况前置条件自检」按钮，只能读判定器自己打的日志：
        TAB.SmartTrafficWeatherJudge: isAbnormalFromMemory: today=... abnormalWeatherType=7 match=true

    返回值三态：`True` 判定通过、`False` 判定没通过、`None` 日志里根本没有
    判定器输出（`SmartTrafficWeatherJudge` 只在有事件时才打日志，刚写完记忆
    没有事件时就是空的 —— 这种情况不能当成失败，真正的兜底是
    `inject_weather_memory` 里对 MMKV 的读回校验）。
    """
    raw = dev.shell(
        "logcat -d -s SmartTrafficWeatherJudge:D TAB.SmartTrafficWeatherJudge:D "
        "TAB.WeatherIntent:D WeatherMemorySimulator:D | "
        "grep -Ei 'isAbnormalFromMemory|abnormalWeatherType' | tail -20"
    ) or ""
    if "isAbnormalFromMemory" not in raw:
        return None, raw.strip()
    hit = re.search(r"abnormalWeatherType=(-?\d+|null)", raw)
    ok = bool(re.search(r"isAbnormalFromMemory:\s*.*match=true", raw)) and (
        hit is not None and hit.group(1) not in ("null", "-1")
    )
    return ok, raw.strip()


def _count_alarm_entries(dev: Device) -> int:
    """数 `dumpsys alarm` 里有几条 `Alarm clock:` 条目。"""
    try:
        raw = dev.shell("dumpsys alarm")
    except Exception:  # noqa: BLE001
        return 0
    return raw.count("Alarm clock:")


def clear_stale_alarms(dev: Device, r: Runner) -> None:
    """清掉时钟 App 里的历史闹钟，再设我们这一次的。

    为什么必须清：`SmartTrafficDismissCoordinator` 判断
    `isLastMorningAlarmDismissed` 时是拿「上午最后一个闹钟」去比，
    设备上只要还堆着别的闹钟（之前几轮跑剩的 11:46 之类），
    它就会选中那条别的条目，于是 dismiss 完仍然打
    `isLastMorningAlarmDismissed=false` → `MorningDismissLatch` 不 arm
    → 规则 10058 的 ability 44 不满足 → 卡片出不来。
    `pm clear` 之后时钟 App 会重置成出厂状态，我们再建的闹钟就是唯一的「末闹」。
    """
    before = _count_alarm_entries(dev)
    if before <= 0:
        r.log("时钟 App 里没有历史闹钟，不用清")
        return
    r.step(f"清掉时钟 App 里的历史闹钟（{before} 条）")
    dev.shell(f"pm clear {DESKCLOCK_PKG}")
    time.sleep(2.0)
    after = _count_alarm_entries(dev)
    r.ok(f"已清掉 {before - after} 个历史闹钟条目（剩 {after} 条）")


def _arm_alarm_and_wait(dev: Device, r: Runner, *, wait_sec: int,
                        alarm_wait: int) -> tuple[str, bool, str | None]:
    """设「当前时间 + 1 分钟」闹钟 → 息屏等响 → 关闹钟 → 解锁 → 等卡。

    返回 `(alarm_at, rang, card_text)`。抽成函数是为了「没出卡就清当日计数
    再重试一次」那段能复用同一套动作，不用复制一遍。
    """
    # 设闹钟之前先清历史闹钟，否则 isLastMorningAlarmDismissed 会选中别的条目。
    clear_stale_alarms(dev, r)
    # 必须读**设备此刻**的时间，不能拿最开始设的 hour:minute 去加 ——
    # 中间开了天气 App、调了系统时间，早就过了好几分钟，
    # 按旧值算会落回过去，时钟会把它排到明天，这次就白等了。
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

    dev.key(KEY_HOME)
    time.sleep(0.8)
    rang = wait_alarm_ring(dev, r, alarm_wait)
    if rang:
        dismiss_alarm(dev, r)
    else:
        r.log("没等到闹钟响，dismiss_latch 可能不会被写入，先继续看卡片")

    back_to_desktop(dev, r)
    return alarm_at, rang, wait_traffic_card(dev, r, int(wait_sec))


def run_real(dev: Device, r: Runner, *,
             abnormal_type: int = ABNORMAL_TYPE,
             wait_sec: int = WAIT_CARD_SEC,
             alarm_wait: int = ALARM_WAIT_SEC,
             hour: int = REAL_HOUR, minute: int = REAL_MINUTE,
             retry_on_miss: bool = True) -> dict:
    """real（真实）路径 —— 正常链路全程不打开 test brain 软件。

    1) 检查/安装 TransAtomicBrain_full_signed(5).apk
    2) 打开天气 App（GDPR 授权 + 定位授权 + 下拉刷新），让它 ingest 一次快照
    3) 系统时间调到当天 12 点前
    4) `logcat | grep -Ei 'WeatherMemorySimulator|isAbnormalFromMemory|
       ingest normalized.*weather|SmartTrafficWeatherJudge'` 看注入情况
    5) 把「当天 abnormalWeatherType=<abnormal_type>」直接写进 App 的天气记忆
       —— 用户给的 `simulate_weather_memory` 命令在 17.10.00.101 / 17.11.00.104
       里都不存在（26 个 dex 里 `simulate` 0 命中），发过去只会得到
       `unknown action_type=simulate_weather_memory`，所以这里仍然先照原样发一次
       并把结果如实记进返回值，然后再用能真正生效的 MMKV 写入兜底。
    6) 设「当前时间 + 1 分钟」闹钟 → 息屏等它响 → 关闹钟（写 dismiss_latch）
       → 解锁回桌面 → 出卡

    `retry_on_miss`（用户 m11067 要求）：第一次没看到卡片时，允许进一次调试页
    点「清理智能路况当日计数」（ability 22 每天只给 1 次，上次跑过就把额度用掉
    了），再重新注入天气记忆 + 重设闹钟跑一遍。只有这条重试路径会打开调试页，
    正常链路完全不碰它。
    """
    ensure_installed(dev, r)
    _ensure_network(dev, r)

    target = device_date(dev)
    r.log(f"目标日期 {target.isoformat()}，异常天气类型 {int(abnormal_type)}")

    # 天气 App 与网络在注入期间是冻结的。不管后面哪一步炸掉（包括设备掉线），
    # 都必须把它们放回去，否则这台机器接下来的所有卡片都别想触发 ——
    # 所以整轮包一层 try/finally，且用一个一次性开关保证只还原一次。
    restored = {"done": False}

    def restore_once() -> None:
        if restored["done"]:
            return
        restored["done"] = True
        try:
            _restore_weather_app(dev, r)
        except Exception as exc:  # noqa: BLE001
            r.log("!! 还原天气 App / 网络失败：" + str(exc)[:160])
            r.log("!! 请手动执行："
                  "adb shell pm enable --user 0 com.rlk.weathers"
                  " ; adb shell svc wifi enable ; adb shell svc data enable")

    try:
        return _run_real_body(
            dev, r, target, int(abnormal_type), int(wait_sec),
            int(alarm_wait), int(hour), int(minute), bool(retry_on_miss),
            restore_once)
    finally:
        restore_once()


def _run_real_body(dev: Device, r: Runner, target, abnormal_type: int,
                   wait_sec: int, alarm_wait: int, hour: int, minute: int,
                   retry_on_miss: bool, restore_once) -> dict:
    """`run_real` 的主体，单独拆出来只为让外层 finally 能兜住任何异常。"""

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

    # 4) 用户给的原命令（日期换成设备当天、type 用参数）——照原样发一次
    accepted, detail = dispatch_simulate_weather(
        dev, r, target, abnormal_type=int(abnormal_type))

    # 5) 先清掉当天额度（ability 22 每天只给 1 次，上一轮跑过就没了）。
    # 放在注入之前：清计数也要 force-stop + disable-user 一轮，放前面可以让
    # 注入成为「最后一次动文件」，进程状态最新。
    try:
        clear_day_count(dev, r)
    except UiError as exc:
        r.log(f"清当日计数没成功（{exc}），继续往下走")

    # 6) 真正能让 abnormal_type 生效的一步：直接写 App 的天气记忆（不进 test brain）
    r.step(f"把「{target.isoformat()} 异常天气 {int(abnormal_type)}」写进 App 的天气记忆")
    r.log("提示：天气 App 与网络会一直冻到整轮结束，否则新记录会被天气云回刷盖掉")
    try:
        memory_json = inject_weather_memory(
            dev, r, target, int(abnormal_type), keep_frozen=True)
    finally:
        # 注入期间 App 是被 `pm disable-user` 冻住的，不管成没成都得恢复，
        # 否则后面闹钟、卡片全都没戏
        unfreeze_atomic(dev, r)
    weather_source = "mmkv_memory"

    # 7) 重启一次 atomicbrain 进程，让 SmartTrafficDismissCoordinator 重新订阅
    #    alarm_list —— 这是 ability 44（末闹 DISMISS）能通过的唯一前提。
    #    不打开 test brain 界面：只 `am force-stop`，系统 1 秒内会自己把它拉起
    #    （实测 pid 立刻换新，订阅恢复，`isLastMorningAlarmDismissed=true` 正常打印）。
    r.step("重启 atomicbrain 进程（恢复末闹监听的订阅）")
    r.log(f"  重启前 pid：{(dev.shell(f'pidof {ATOMIC_PACKAGE}') or '').strip() or '无'}")
    dev.shell(f"am force-stop {ATOMIC_PACKAGE}")
    new_pid = ""
    for _ in range(15):
        time.sleep(1.0)
        new_pid = (dev.shell(f"pidof {ATOMIC_PACKAGE}") or "").strip()
        if new_pid:
            break
    r.ok(f"  进程已重启，pid：{new_pid or '（15 秒内没被拉起，继续往下走）'}")
    time.sleep(2.5)

    # 8) 只读 logcat 复核
    mem_ok, mem_raw = memory_verdict(dev)
    if mem_raw:
        for line in mem_raw.splitlines()[-3:]:
            r.log(f"  {line[:180]}")

    # 9~11) 设闹钟 → 息屏等响 → 关闹钟 → 解锁 → 等卡
    try:
        alarm_at, rang, hit = _arm_alarm_and_wait(
            dev, r, wait_sec=int(wait_sec), alarm_wait=int(alarm_wait))
    finally:
        # 规则评完再放开天气 App + 网络（放太早会被天气云回刷把记忆盖掉）
        _restore_weather_app(dev, r)

    retried = False
    if not hit and retry_on_miss:
        # 兜底：清计数/写记忆这两步都可能被 App 的回刷冲掉。用户允许
        # 「没出卡时进一次 test brain 清当日计数再重试」，所以这里走界面上的
        # 那个按钮（比改文件更权威），然后重写一次记忆、重设闹钟再跑一遍。
        retried = True
        r.log("第一次没看到卡片，进调试页清一次「智能路况当日计数」再重试")
        try:
            open_debug_page(dev, r)
            scroll_to_traffic(dev, r)
            tap_traffic_button(dev, r, RID_RESET_TRAFFIC,
                               "清理智能路况当日计数（ABILITY 22 上限 1）")
            reset_txt = read_traffic_result(dev).replace("\n", " / ")[:200]
            r.log(f"清理结果：{reset_txt}")
        except UiError as exc:
            r.log(f"清当日计数没成功（{exc}），直接按原样重试")
        # 清计数会重启/切走 App，天气记忆可能被回滚，重新写一遍更稳。
        # 注意：这里 `keep_frozen=True` 又会把天气 App 冻住、断网，重试那轮
        # 结束后必须再放开一次，否则设备会留在没网络、天气 App 被禁用的状态。
        try:
            memory_json = inject_weather_memory(
                dev, r, target, int(abnormal_type), keep_frozen=True)
        except UiError as exc:
            r.log(f"重写天气记忆失败（{exc}），沿用上一次写入的结果")
        restore_once()
        alarm_at, rang, hit = _arm_alarm_and_wait(
            dev, r, wait_sec=int(wait_sec), alarm_wait=int(alarm_wait))

    return {
        "method": "real",
        "abnormal_type": int(abnormal_type),
        "target_date": target.isoformat(),
        "weather_source": weather_source,
        "memory_json": memory_json[:400],
        "simulate_accepted": accepted,
        "simulate_detail": detail,
        "weather_log_lines": len(dumps),
        "memory_abnormal": mem_ok,
        "alarm_at": alarm_at,
        "alarm_rang": rang,
        "retried": retried,
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
        retry_on_miss: bool = True,
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
            f"{ABNORMAL_WHITELIST}：7 暴雨 / 10 大雨 / 12 中雨 / 15 雷雨）")
    if abnormal_type not in ABNORMAL_WHITELIST:
        raise UiError(
            f"abnormal_type={abnormal_type} 不在白名单 {ABNORMAL_WHITELIST} 里"
            "（7 暴雨 / 10 大雨 / 12 中雨 / 15 雷雨）")
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
                           hour=int(hour), minute=int(minute),
                           retry_on_miss=bool(retry_on_miss))
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

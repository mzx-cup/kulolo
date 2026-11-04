"""提前打开提示卡片（时间管理）。

按测试说明：
  1. 设置每天 04:05 闹钟，然后关闭每日闹钟（保持闹钟在列表里、但处于关闭状态）。
  2. 系统时间调到周日 19:09。
  3. 回桌面保持亮屏等待 1 分钟；19:10 桌面「智慧建议」应出现：
     「明天是工作日 / 要开启明天的闹钟吗？」
  4. 截图 → 前端确认。

闹钟关闭通过时钟 App 的闹钟列表开关完成（先 SET_ALARM 创建，再点击开关），
不依赖私有 provider。
"""
from __future__ import annotations

import datetime as _dt
import io
import re
import time

from PIL import Image

import locale_kit

from phone_ctl import KEY_HOME, KEY_WAKEUP, Device, UiError

from scenario_alarm import DESKCLOCK_PKG, _set_daily_alarm
from scenario_birthday import (
    Runner,
    _cli_emit,
    _unlock_with_retries,
    _wait_screen_on,
    device_date,
    disconnect_network,
    ensure_home_before_confirm,
    restore_network,
    set_system_datetime,
)

ALARM_HOUR = 4
ALARM_MINUTE = 5
TEST_HOUR = 19
TEST_MINUTE = 9
_SUNDAY = 6  # date.weekday(): Monday=0


def _next_sunday(today: _dt.date) -> _dt.date:
    """今天就是周日就用今天，否则取最近的周日。"""
    delta = (_SUNDAY - today.weekday()) % 7
    return today + _dt.timedelta(days=delta)


def _orange_switch(png: bytes) -> tuple[int, int] | None:
    """在时钟 App 闹钟列表截图里找橙色开启开关的中心点。

    左右两侧都扫：RTL 语言（阿拉伯语）下开关整体镜像到屏幕左侧，
    只扫右侧会一个都找不到（实测踩过）。
    """
    im = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = im.size
    px = im.load()
    pts: list[tuple[int, int]] = []
    for y in range(int(h * 0.12), int(h * 0.55)):
        for x in list(range(int(w * 0.02), int(w * 0.28))) + \
                 list(range(int(w * 0.72), int(w * 0.995))):
            r, g, b = px[x, y]
            if r >= 210 and 80 <= g <= 200 and b <= 110 and r >= g + 45:
                pts.append((x, y))
    if not pts:
        return None
    return (sum(p[0] for p in pts) // len(pts),
            sum(p[1] for p in pts) // len(pts))


def _has_alarm(raw: str) -> bool:
    """是否还有任意启用的闹钟（Alarm clock）。

    不再按具体分钟比对：本机每天 04:05 的闹钟即使被关掉，AlarmManager 里
    仍会留下前一分钟的条目（其他场景/系统闹钟），按分钟匹配会误判成没关掉。
    """
    return re.search(r"Alarm clock:\s*\n\s*triggerTime=", raw) is not None


def _clear_stale_alarms(dev: Device, r: Runner) -> None:
    """动手前先清空时钟 App 的全部闹钟。

    本场景的判据是「还有没有任意启用的闹钟」，而别的场景（wake_alarm_delay）
    会留下 04:01 这种常驻闹钟，不清掉的话关掉 04:05 之后照样能匹配到，
    被误判成「没关掉」直接抛错（实测踩过）。pm clear 是唯一能一次清干净的
    办法：它同时清掉 ClockProvider 里的记录和 AlarmManager 里的条目。
    """
    r.step("清空时钟 App 里的历史闹钟")
    before = re.findall(r"Alarm clock:", dev.shell("dumpsys alarm"))
    dev.shell(f"pm clear {DESKCLOCK_PKG}")
    time.sleep(2.0)
    after = re.findall(r"Alarm clock:", dev.shell("dumpsys alarm"))
    if after:
        r.log(f"警告：pm clear 之后仍有 {len(after)} 个闹钟条目，继续执行")
    else:
        r.log(f"已清掉 {len(before)} 个历史闹钟条目，AlarmManager 里没有闹钟了")
    r.ok("时钟 App 已重置")


def _open_alarm_list(dev: Device, r: Runner) -> None:
    """先亮屏解锁，再打开时钟 App 的闹钟列表。

    之前直接 am start：设备息屏/上锁时，启动被锁屏挡住，界面停在
    NotificationShade，截图里一个橙色开关都找不到，_disable_daily_alarm
    的循环第一轮就 break，闹钟根本没关掉（报「闹钟没有成功关闭」）。
    """
    dev.stayon(True)
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    time.sleep(0.6)
    if dev.keyguard_showing():
        _unlock_with_retries(dev, r)
    for attempt in range(3):
        dev.shell(f"am start -a android.intent.action.SHOW_ALARMS -p {DESKCLOCK_PKG}")
        for _ in range(10):
            time.sleep(0.4)
            if "deskclock" in dev.focus().lower():
                time.sleep(0.8)          # 等列表动画结束，避免 dump 报 idle
                return
        r.log(f"闹钟列表没起来（第 {attempt + 1} 次），当前窗口 {dev.focus()}，重试")
    raise UiError(f"打不开时钟 App 的闹钟列表，当前窗口是 {dev.focus()}")


def _alarm_rows(nodes: list[Node]) -> list[tuple[str, Node]]:
    """把闹钟列表解析成 [(时钟文本, 该行的开关节点)]。

    时钟 App 的列表每行是 cl_alarm_home，行内有 digital_clock（文本形如
    "04:05"）和 onoff（Switch，带 checked 属性）。不能靠截图找橙色像素：
    RTL 语言（阿拉伯语）下开关跑到屏幕左侧 x=44~264，原来的右侧扫描一个都
    找不到，于是兜底去点最后一个开关，永远关不掉目标闹钟。
    """
    rows = [n for n in nodes if n.short_id == "cl_alarm_home"]
    out: list[tuple[str, Node]] = []
    for row in rows:
        y1, y2 = row.bounds[1], row.bounds[3]
        clock = next((n for n in nodes
                      if n.short_id == "digital_clock" and y1 <= n.center[1] <= y2), None)
        sw = next((n for n in nodes
                   if n.short_id == "onoff" and y1 <= n.center[1] <= y2), None)
        if clock is not None and sw is not None:
            out.append((locale_kit.to_ascii_digits(clock.text or "").strip(), sw))
    return out


def _find_alarm_switch(nodes: list[Node], hour: int, minute: int) -> Node | None:
    """按时间文本找目标闹钟那一行的开关（支持 04:05 / ٠٤:٠٥ 两种数字写法）。"""
    want = f"{hour:02d}:{minute:02d}"
    for text, sw in _alarm_rows(nodes):
        if want in text:
            return sw
    return None


def _disable_daily_alarm(dev: Device, r: Runner) -> None:
    r.step(f"关闭每日闹钟 {ALARM_HOUR:02d}:{ALARM_MINUTE:02d}")
    _open_alarm_list(dev, r)

    # 主路径：控件树里按时间文本定位那一行的 onoff 开关，点掉。
    for attempt in range(3):
        nodes = dev.dump()
        sw = _find_alarm_switch(nodes, ALARM_HOUR, ALARM_MINUTE)
        if sw is None:
            r.log(f"闹钟列表里没找到 {ALARM_HOUR:02d}:{ALARM_MINUTE:02d} 那一行"
                  f"（第 {attempt + 1} 次），当前窗口 {dev.focus()}")
            _open_alarm_list(dev, r)
            continue
        if sw.attrs.get("checked") != "true":
            r.log(f"{ALARM_HOUR:02d}:{ALARM_MINUTE:02d} 的开关已经是关闭状态")
            break
        r.log(f"点击 {ALARM_HOUR:02d}:{ALARM_MINUTE:02d} 的开关 @ {sw.center}")
        dev.tap(sw.center[0], sw.center[1])
        time.sleep(1.2)
        if not _has_alarm(dev.shell("dumpsys alarm")):
            break

    if _has_alarm(dev.shell("dumpsys alarm")):
        # 兜底一：截图找橙色开关（LTR 下在右侧，RTL 下在左侧，两半都扫）。
        for _ in range(3):
            center = _orange_switch(dev.screenshot_png())
            if center is None:
                break
            r.log(f"兜底：点击橙色开关 ({center[0]}, {center[1]})")
            dev.tap(center[0], center[1])
            time.sleep(1.0)
    if _has_alarm(dev.shell("dumpsys alarm")):
        # 兜底二：把列表里所有 checked 的开关都点一遍。
        nodes = dev.dump()
        on = [sw for _, sw in _alarm_rows(nodes) if sw.attrs.get("checked") == "true"]
        for n in on:
            r.log(f"兜底：关闭还开着的开关 @ {n.center}")
            dev.tap(n.center[0], n.center[1])
            time.sleep(0.8)
    if _has_alarm(dev.shell("dumpsys alarm")):
        raise UiError(f"{ALARM_HOUR:02d}:{ALARM_MINUTE:02d} 每日闹钟没有成功关闭"
                      f"（当前窗口 {dev.focus()}）")
    r.ok("每日闹钟已关闭（保留在闹钟列表里）")


def _wait_card(dev: Device, r: Runner, day: _dt.date, wait_sec: int) -> bool:
    r.step(f"系统时间调到周日 {TEST_HOUR:02d}:{TEST_MINUTE:02d}，"
           f"息屏 {wait_sec} 秒再亮屏 {wait_sec} 秒")
    set_system_datetime(dev, r, day, TEST_HOUR, TEST_MINUTE)

    # 第一步：灭屏等待
    dev.key(KEY_HOME)
    time.sleep(0.5)
    dev.stayon(False)
    time.sleep(0.3)
    dev.key(223)                      # KEYCODE_SLEEP
    if not _wait_screen_on(dev, False, timeout=1.2):
        r.log("警告：灭屏后屏幕仍为亮起状态")
    r.log(f"屏幕已灭，等待 {wait_sec} 秒")
    for elapsed in range(wait_sec):
        r.check()
        remain = wait_sec - elapsed
        if elapsed % 5 == 0 or remain == 1:
            r.tick(remain)
        time.sleep(1)

    # 第二步：亮屏并解锁，保持亮屏等待
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    time.sleep(0.8)
    dev.stayon(True)
    _unlock_with_retries(dev, r, 3)
    dev.key(KEY_HOME)
    time.sleep(0.5)
    r.log(f"已亮屏解锁，保持亮屏等待 {wait_sec} 秒")
    for elapsed in range(wait_sec):
        r.check()
        remain = wait_sec - elapsed
        if elapsed % 5 == 0 or remain == 1:
            r.tick(remain)
        time.sleep(1)

    time.sleep(0.3)
    now = dev.shell("date '+%H:%M:%S'").strip()
    ensure_home_before_confirm(dev, r)
    r.shot("桌面 19:11 提前打开提示")

    r.step("确认提前打开提示卡片是否出现")
    # 同「提前关闭提示」：卡片只在桌面「智慧建议」出现，通知栏里没有，
    # 所以不展开通知栏，直接一次确认。
    if not r.confirm():
        r.shot("桌面 未出现提前打开提示")
        r.log("桌面没有「提前打开提示」卡片，本次结束（可点重试重新触发）")
        return False
    r.ok(f"设备时间 {now}，19:10 桌面已检查")
    return True


def run(dev: Device | None = None, emit=None, *, wait_sec: int = 60,
        method: str = "real", control: dict | None = None,
        confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    # 时间管理三张卡片：第一步就断网（卡片只靠本地时间 + 本地闹钟判定）。
    disconnect_network(dev, r)
    try:
        return _run_trigger(dev, r, wait_sec=wait_sec, method=method)
    finally:
        restore_network(dev, r)


def _run_trigger(dev: Device, r: Runner, *, wait_sec: int, method: str) -> dict:
    # Mock 触发：装 TransAtomicBrain → 点「MOCK 工作日开闹卡」→ 回桌面出卡。
    if method == "mock":
        from scenario_atomic_mock import run_mock
        return run_mock(dev, r, "open", wait_sec)
    if method != "real":
        raise UiError(f"未知触发方式 {method!r}，只能是 real / mock")

    if not (5 <= wait_sec <= 300):
        raise UiError("wait_sec 必须在 5~300 秒之间")

    today = device_date(dev)
    day = _next_sunday(today)
    result = {
        "device_today": today.isoformat(),
        "test_date": day.isoformat(),
        "alarm": f"{ALARM_HOUR:02d}:{ALARM_MINUTE:02d}",
        "wait_sec": wait_sec,
    }
    r.log(f"目标：周日 {day} {TEST_HOUR:02d}:{TEST_MINUTE:02d}，"
          f"每日闹钟 {ALARM_HOUR:02d}:{ALARM_MINUTE:02d} 关闭")

    _clear_stale_alarms(dev, r)
    _set_daily_alarm(dev, r, ALARM_HOUR, ALARM_MINUTE)
    _disable_daily_alarm(dev, r)
    shown = _wait_card(dev, r, day, wait_sec)

    dev.stayon(False)
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    result["steps"] = r._no
    result["ok"] = shown
    result["triggered"] = shown
    if shown:
        result["summary"] = (
            f"完成。每天 {ALARM_HOUR:02d}:{ALARM_MINUTE:02d} 闹钟已关闭；"
            f"系统时间已到周日 {day} {TEST_HOUR:02d}:{TEST_MINUTE:02d}，"
            f"亮屏等待 {wait_sec}s 到 19:10，桌面智慧建议应出现「要开启明天的闹钟吗？」。")
    else:
        result["summary"] = (
            f"未触发。已把时间调到周日 {day} {TEST_HOUR:02d}:{TEST_MINUTE:02d} 并亮屏等待 "
            f"{wait_sec}s，桌面没有看到「提前打开提示」卡片。")
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

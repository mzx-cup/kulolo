"""时间管理三张卡片的 Mock 触发方式（Transsion 内部 atomicbrain debug App）。

真实触发要先建/关闹钟、把系统时间拨到特定星期几、再息屏等待，一步不对就不出卡；
Mock 触发只是让 atomicbrain 直接注入一条事件，等价于系统自己判定出了场景：

  1. 从网络共享装 `com.transsion.atomicbrain`（TransAtomicBrain_full_signed.apk）
  2. `am start -n com.transsion.atomicbrain/.debug.Test` 打开调试页
  3. 按 resource-id 点对应 mock 按钮（睡眠晚 / 工作日开闹 / 休息日关闹）
  4. 唤醒 + 上滑解锁 → 按 HOME 回桌面 → 等 N 秒 → 截图 → 前端确认

不修改系统时间、不创建闹钟、不息屏等待，所以跑一次只要十几秒。
"""
from __future__ import annotations

import re
import time

from phone_ctl import KEY_HOME, KEY_WAKEUP, Device, UiError

from scenario_app_suggest import _adb, _app_installed, _zip_broken
from scenario_birthday import Runner, _unlock_with_retries, _wait_screen_on, ensure_home_before_confirm

ATOMIC_PACKAGE = "com.transsion.atomicbrain"
ATOMIC_ACTIVITY = "com.transsion.atomicbrain/.debug.Test"
ATOMIC_APK = (r"\\10.205.4.20\Odc_Temp_File\archermind\zixin.mei\apk"
              r"\TransAtomicBrain_full_signed(5).apk")
# 2026-11-05 实测：53395133 字节，普通 APK，`adb install -r -t -d` → Success，
# 装完版本 17.10.00.101（versionCode 171000101）。
# 用这个包而不是旧的 `TransAtomicBrain_full_signed.apk`（53800373 字节 /
# 17.11.00.104）：旧包的调试页里**没有**「智能路况」那一整块按钮
# （`btn_mock_smart_traffic` / `btn_reset_smart_traffic_day_count` /
# `btn_query_smart_traffic_state`），也没法跑智能路况卡的触发。
ATOMIC_OK_SIZES = (53395133,)
# 只有带智能路况调试区的版本才够用；装成别的版本（比如 17.11.00.104）
# 会「看起来装了但按钮全无」，所以要对版本做一次校验。
ATOMIC_MIN_VERSION_CODE = 171000000
ATOMIC_SMART_TRAFFIC_RID = "com.transsion.atomicbrain:id/btn_mock_smart_traffic"

# kind -> (mock 按钮 resource-id, 按钮文案, 卡片名)
MOCK_BUTTONS = {
    "delay": ("btn_mock_early_wakeup_alarm_delay", "MOCK 睡得有点晚卡", "起床闹钟延迟卡片"),
    "open": ("btn_mock_early_alarm_open", "MOCK 工作日开闹卡", "提前打开提示卡片"),
    "close": ("btn_mock_early_alarm_dismissal", "MOCK 休息日关闹卡", "提前关闭提示卡片"),
}

OPEN_TIMEOUT = 20.0


def _version_code(dev: Device, package: str) -> int:
    """读已装包的 versionCode，读不到返回 0。"""
    out = dev.shell(f"dumpsys package {package} | grep -m1 versionCode")
    m = re.search(r"versionCode=(\d+)", out)
    return int(m.group(1)) if m else 0


def _install(dev: Device, r: Runner, problem: str | None) -> None:
    rc, out = _adb(dev, "install", "-r", "-t", "-d", ATOMIC_APK)
    if rc != 0 or not _app_installed(dev, ATOMIC_PACKAGE):
        hint = f"根因：{problem}。" if problem else ""
        raise UiError(
            f"从网络共享安装 {ATOMIC_PACKAGE} 失败，{hint}"
            f"adb 输出：{out.strip()[:300]}。共享路径：{ATOMIC_APK}")
    ver = dev.shell(f"dumpsys package {ATOMIC_PACKAGE} | grep -m1 versionName").strip()
    r.ok(f"安装成功 {ver.split('=')[-1] if '=' in ver else ''}".strip())


def ensure_installed(dev: Device, r: Runner) -> None:
    """确认装的是**带智能路况调试区**的那个版本，不够就覆盖安装。

    只看「包在不在」是不够的：旧包 17.11.00.104 也装着，但它的调试页里
    没有 `btn_mock_smart_traffic` 这些按钮，跑到一半才会报
    「滑了 N 次仍没看到按钮」，很难看出是版本问题。所以这里直接比 versionCode。
    """
    r.step(f"检查 Mock 测试 App 是否已安装且在可用版本：{ATOMIC_PACKAGE}")
    installed = _app_installed(dev, ATOMIC_PACKAGE)
    code = _version_code(dev, ATOMIC_PACKAGE) if installed else 0
    if installed and code >= ATOMIC_MIN_VERSION_CODE:
        r.ok(f"已安装 versionCode={code}")
        return

    if installed:
        r.log(f"已装版本 versionCode={code} 低于所需的 "
              f"{ATOMIC_MIN_VERSION_CODE}（旧包调试页没有智能路况按钮），覆盖安装")

    r.log(f"从网络共享安装：{ATOMIC_APK}")
    problem = _zip_broken(ATOMIC_APK, ATOMIC_OK_SIZES)
    if problem:
        r.log(f"预检提示：{problem}")
    _install(dev, r, problem)


def open_mock_page(dev: Device, r: Runner) -> None:
    """拉起 debug 调试页，等到 mock 按钮那一屏渲染出来。"""
    r.step("打开 TransAtomicBrain 调试页")
    if dev.keyguard_showing():
        _unlock_with_retries(dev, r, unlock_retries=3, wake=True)
    out = dev.shell(f"am start -n {ATOMIC_ACTIVITY}")
    if "Error" in out or "Exception" in out:
        raise UiError(f"启动 {ATOMIC_ACTIVITY} 失败：{out.strip()[:300]}")
    dev.wait_focus("atomicbrain", timeout=OPEN_TIMEOUT)
    time.sleep(0.6)
    r.ok(dev.focus())


def tap_mock(dev: Device, r: Runner, kind: str) -> tuple[str, str, str]:
    """按 resource-id 点 mock 按钮（找不到时退回按文案精确匹配）。"""
    if kind not in MOCK_BUTTONS:
        raise UiError(f"未知 mock 类型 {kind!r}，只能是 {sorted(MOCK_BUTTONS)}")
    rid, label, card = MOCK_BUTTONS[kind]
    r.step(f"点击 mock 按钮：{label}")
    try:
        node = dev.wait_node(timeout=12.0, rid=rid)
    except UiError:
        r.log(f"按 resource-id {rid} 没找到，改按文案查找")
        node = dev.wait_node(timeout=6.0, text=label)
    dev.tap_node(node, 0.8)
    time.sleep(1.0)
    r.ok(f"已点击「{node.text or label}」{node.center}")
    return rid, label, card


def back_to_desktop(dev: Device, r: Runner) -> None:
    """唤醒 + 上滑解锁 + HOME。

    点完 mock 按钮时 debug App 仍在前台，且屏幕常常已经灭掉/上锁；
    直接按 HOME 只会落到 NotificationShade 的锁屏面，必须先解锁。
    """
    r.step("唤醒解锁并回到桌面")
    dev.stayon(True)
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    time.sleep(0.4)
    _unlock_with_retries(dev, r, unlock_retries=3)
    dev.key(KEY_HOME)
    time.sleep(0.8)
    focus = dev.focus()
    if "launcher" not in focus.lower():
        r.log(f"按 HOME 后焦点仍在 {focus}，再按一次")
        dev.key(KEY_HOME)
        time.sleep(0.8)
        focus = dev.focus()
    if "launcher" not in focus.lower():
        raise UiError(f"按 HOME 后没回到桌面，当前窗口 {focus!r}")
    dev.stayon(True)
    r.ok(focus)


def wait_and_confirm(dev: Device, r: Runner, wait_sec: int, card_title: str) -> str:
    """回桌面后等 wait_sec 秒让系统刷新智慧建议，再截图交前端确认。"""
    r.step(f"等待 {wait_sec} 秒检查{card_title}")
    for remain in range(wait_sec, 0, -1):
        r.check()
        r.tick(remain)
        time.sleep(1)
    time.sleep(1.0)
    ensure_home_before_confirm(dev, r)
    r.shot(f"Mock · {card_title}")

    r.step(f"确认{card_title}是否出现")
    if r.confirm():
        r.ok("桌面已确认卡片")
        return "桌面"

    r.log("桌面未确认，展开通知栏再检查")
    dev.shell("cmd statusbar expand-notifications")
    time.sleep(1.0)
    r.shot("通知栏")
    ok = r.confirm()
    dev.shell("cmd statusbar collapse")
    time.sleep(0.4)
    if not ok:
        raise UiError(f"Mock 触发后，桌面和通知栏都没有确认到「{card_title}」")
    ensure_home_before_confirm(dev, r)
    r.ok("通知栏已确认卡片")
    return "通知栏"


def run_mock(dev: Device, r: Runner, kind: str, wait_sec: int) -> dict:
    """完整 Mock 流程，返回可直接作为场景结果的 dict。

    wait_sec 在本路径下表示「回桌面后等待秒数」，上限压到 30 秒：
    mock 注入是即时的，再等下去只是让用户多等。
    """
    wait = max(5, min(int(wait_sec), 30))
    if wait != int(wait_sec):
        r.log(f"Mock 路径等待时间压到 {wait} 秒（mock 注入是即时的，不必久等）")
    _rid, label, card = MOCK_BUTTONS[kind]
    r.log(f"触发方式：Mock（{label}），不改系统时间、不建闹钟、不息屏等待")

    ensure_installed(dev, r)
    open_mock_page(dev, r)
    tap_mock(dev, r, kind)
    back_to_desktop(dev, r)
    where = wait_and_confirm(dev, r, wait, card)

    dev.stayon(False)
    return {
        "method": "mock",
        "mock_kind": kind,
        "mock_button": label,
        "wait_sec": wait,
        "confirmed_on": where,
        "device_time_after": dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip(),
        "steps": r._no,
        "ok": True,
        "triggered": True,
        "summary": (
            f"完成。已通过 Mock 触发「{card_title_of(kind)}」："
            f"在 TransAtomicBrain 里点「{label}」后回桌面，{where}已确认卡片。"),
    }


def card_title_of(kind: str) -> str:
    return MOCK_BUTTONS[kind][2]


if __name__ == "__main__":
    import sys

    from scenario_birthday import _cli_emit

    where = sys.argv[1] if len(sys.argv) > 1 else "delay"
    d = Device()
    rr = Runner(d, _cli_emit)
    d.log = rr.log
    try:
        print("\n完成：", run_mock(d, rr, where, 15))
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

"""切换手机系统语言（中文 / 英语 / 阿拉伯语）。

为什么要这么麻烦：这台机器是 `ro.build.type=user`，没有 root。

    adb root                       -> adbd cannot run as root in production builds
    setprop persist.sys.locale     -> Failed to set property
    am broadcast SET_LOCALE        -> 无人接收，没反应
    stop / start                   -> Must be root

唯一可行的是写 `settings put system system_locales` 后**整机重启**——Android
在启动时读这个设置决定 locale。实测从写入到桌面就绪约 65 秒。

重启期间 adb 会掉线，所以：
- 切换前记下当前 locale，已经是要切的那个就直接跳过（省一次两分钟的重启）；
- 重启后要等 `sys.boot_completed=1` 且设备重新出现在 adb 列表里；
- 解锁屏幕（重启后是锁屏态），否则后续 uiautomator dump 拿到的是锁屏控件树。
"""
from __future__ import annotations

import time

import locale_kit as lk
from phone_ctl import Device, UiError

#: 重启后等设备回来的最长时间。实测 65 秒左右就绪，留足余量。
BOOT_TIMEOUT = 180.0
#: reboot 之后 adb 掉线需要一个窗口期，期间 shell 必然失败，别当故障。
REBOOT_SETTLE = 8.0


def read_locale(dev: Device) -> str:
    """读设备当前 locale，归一化成 BCP-47（'ar-SA' 这种）。"""
    try:
        raw = dev.shell("settings get system system_locales").strip()
    except Exception:
        raw = ""
    if not raw or raw == "null":
        try:
            raw = dev.shell("getprop persist.sys.locale").strip()
        except Exception:
            raw = ""
    return lk.normalize_locale(raw) or ""


def _boot_completed(dev: Device) -> bool:
    try:
        return dev.shell("getprop sys.boot_completed").strip() == "1"
    except Exception:
        return False


def wait_boot(dev: Device, r=None, timeout: float = BOOT_TIMEOUT) -> None:
    """等设备从重启里回来：sys.boot_completed=1 且能正常执行 shell。"""
    deadline = time.time() + timeout
    time.sleep(REBOOT_SETTLE)
    last = ""
    while time.time() < deadline:
        try:
            if _boot_completed(dev):
                # boot_completed 之后系统还要再花几秒把锁屏/桌面拉起来
                time.sleep(3.0)
                return
        except Exception as exc:      # adb 还在掉线，正常现象
            last = str(exc)
        time.sleep(2.0)
    raise UiError(
        f"重启后等了 {timeout:.0f} 秒设备还没回来。请确认 USB 线没松、"
        f"手机停在锁屏界面。最后一次错误：{last or '超时'}")


def switch_locale(dev: Device, target: str, r=None, *,
                  timeout: float = BOOT_TIMEOUT,
                  force: bool = False) -> str:
    """把设备语言切成 target（zh-Hans-CN / en-US / ar-SA），返回切换后的 locale。

    target 已经等于当前 locale 时直接返回，不重启。force=True 时强制重启一次
    （排障用：有时语言没真正生效，重启一次能纠正）。
    """
    want = lk.normalize_locale(target)
    if want not in {code for code, _ in lk.TRIGGER_LOCALES}:
        raise UiError(
            f"不支持的语言 {target!r}，只能是："
            + "、".join(f"{code}({name})" for code, name in lk.TRIGGER_LOCALES))
    cur = read_locale(dev)
    if cur and lk.same_locale(cur, want) and not force:
        if r:
            r.log(f"手机系统语言已经是{lk.label_for_locale(want)}（{cur}），不用切")
        return cur

    name = lk.label_for_locale(want)
    if r:
        r.step(f"把手机系统语言切换成{name}（{want}）")
        if cur:
            r.log(f"切换前是 {cur}")
        r.log("写入 system_locales 后需要整机重启才生效，约 1~2 分钟")

    # 关掉常亮的临时开关，避免重启后屏幕一直亮着耗电
    try:
        dev.stayon(False)
    except Exception:
        pass
    dev.shell(f"settings put system system_locales {want}")
    got = dev.shell("settings get system system_locales").strip()
    if got != want:
        raise UiError(f"写入 system_locales 失败：想要 {want}，实际读到 {got!r}")

    if r:
        r.log("重启手机…")
    try:
        dev.shell("reboot")
    except Exception:
        pass          # reboot 会掐断连接，报错是正常的
    time.sleep(REBOOT_SETTLE)

    if r:
        r.log("等待系统启动完成…")
    wait_boot(dev, r, timeout)

    # 重启后一定是锁屏态，先解锁再交回去，否则后面 dump 到的是锁屏控件树
    _wake_and_unlock(dev, r)

    after = read_locale(dev)
    if r:
        if lk.same_locale(after, want):
            r.ok(f"系统语言已是{name}")
        else:
            r.log(f"警告：重启后读到 {after!r}，与期望的 {want!r} 不一致")
    return after


def _wake_and_unlock(dev: Device, r=None) -> None:
    """重启/息屏后唤醒并上滑解锁。失败只记日志，不打断流程。"""
    try:
        dev.stayon(True)
        dev.key(224)                        # KEYCODE_WAKEUP
        time.sleep(1.0)
        if not dev.locked():
            return
        # 复用生日场景里那套「贴底边快甩 + 多种变体」的解锁逻辑，
        # 单独实现一份会跟主流程的状态机不一致。
        from scenario_birthday import _unlock_with_retries
        _unlock_with_retries(dev, _NullRunner(r), 3, wake=True)
    except Exception as exc:
        if r:
            r.log(f"重启后自动解锁没成功（{exc}），可能需要手动解锁一次")


class _NullRunner:
    """把 None 包成有 log/ok/step 的空实现，供只想借解锁逻辑的调用方用。"""

    def __init__(self, r=None):
        self._r = r

    def log(self, msg: str) -> None:
        if self._r:
            self._r.log(msg)

    def ok(self, msg: str) -> None:
        if self._r:
            self._r.ok(msg)

    def step(self, msg: str) -> None:
        if self._r:
            self._r.step(msg)

    def shot(self, name: str) -> None:
        pass

    def confirm(self) -> bool:
        return True


def ensure_locale(dev: Device, target: str, r=None, *,
                  timeout: float = BOOT_TIMEOUT) -> bool:
    """触发前把语言对齐到目标值。返回 True 表示做过重启。

    场景本身不关心语言，只有「前端选了某种语言」时才需要。切换失败不致命
    ——宁可用当前语言继续跑，也不要把整轮触发废掉，所以这里吞掉异常并返回
    False，由调用方决定要不要在日志里提醒。
    """
    try:
        before = read_locale(dev)
        if before and lk.same_locale(before, target):
            return False
        switch_locale(dev, target, r, timeout=timeout)
        return True
    except Exception as exc:
        if r:
            r.log(f"提示：切换系统语言没成功（{exc}），按当前语言继续触发")
        return False


if __name__ == "__main__":
    import sys

    from phone_ctl import Device

    target = sys.argv[1] if len(sys.argv) > 1 else lk.LOCALE_AR
    d = Device()
    print("before:", read_locale(d))
    print("after :", switch_locale(d, target))

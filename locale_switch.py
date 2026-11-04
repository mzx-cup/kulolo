"""切换手机系统语言（中文 / 英语 / 阿拉伯语）——**不需要重启**。

怎么做到的
--------------------------------------------------
这台机器是 `ro.build.type=user`，没有 root：

    adb root                       -> adbd cannot run as root in production builds
    setprop persist.sys.locale     -> Failed to set property
    am broadcast SET_LOCALE        -> 无人接收，没反应
    stop / start                   -> Must be root

写 `settings put system system_locales` 只有在**下次开机**时才被读，所以
旧实现必须整机重启（约 1~2 分钟）。但那不是唯一的路：

    adb shell cmd locale set-device-locale <tag>

这是 Android 13+ 的 shell 命令，走 LocaleManager 的服务端接口，**当场生效**
（桌面、系统 UI、各 App 的资源配置会立刻换语言），不需要重启。

实测（X6766 / Android 17）：`ar-EG` / `en-US` / `zh-Hans-CN` 三者来回切
都是 2~3 秒内界面就换了。

两个必须注意的点
--------------------------------------------------
1. **设备支持哪些语言是枚举出来的**，不能凭空写。X6766 支持 `ar-EG`，
   **不支持 `ar-SA`**（`Error: Invalid locale tag: ar-SA`）。所以切之前先
   `cmd locale list-device-locales` 探一遍，挑出可用 tag 列表里匹配的那个。
   顺带一提它还有 `ar-EG-u-nu-latn`（阿拉伯语 + 拉丁数字），真要数字也用
   拉丁写法可以选它。

2. `set-device-locale` 会把 `system_locales` 这个**语言列表**覆盖成单个值。
   用户原本可能配了 `zh-Hans-CN,ar-EG,en-GB,en-US` 四个语言。所以切完要
   把原列表补回去，只把目标语言挪到第一位：
       cmd locale set-device-locale <tag>      # 先让界面当场换过来
       settings put system system_locales <tag>,<其余原语言...>   # 再还原列表
   这样即时生效 + 下次开机首选项都对，用户的其它语言也不丢。

重启兜底
--------------------------------------------------
极少数机型没有 `cmd locale` 这个命令（Android < 13），此时退回旧方案：
写 `system_locales` + 整机重启。`switch_locale` 会自动判断走哪条路。
"""
from __future__ import annotations

import time

import locale_kit as lk
from phone_ctl import Device, UiError

#: 重启兜底路径等设备回来的最长时间。实测 65 秒左右就绪，留足余量。
BOOT_TIMEOUT = 240.0
#: reboot 之后 adb 掉线需要一个窗口期，期间 shell 必然失败，别当故障。
REBOOT_SETTLE = 8.0
#: `cmd locale set-device-locale` 之后界面重排的稳定时间。实测 1 秒内就换完了，
#: 留 2 秒给转场动画，避免紧接着 dump 拿到切换中途的半截控件树。
APPLY_SETTLE = 2.0


# ═══════════════════════════════════════════════════════════════════
#   读状态
# ═══════════════════════════════════════════════════════════════════

def read_locale(dev: Device) -> str:
    """读设备当前**生效**的 locale，归一化成 BCP-47（'ar-EG' 这种）。

    优先用 `cmd locale get-device-locale`（这是真正生效的值），
    读不到再退回 `system_locales` 的第一项。
    """
    for cmd in ("cmd locale get-device-locale", "settings get system system_locales"):
        try:
            raw = dev.shell(cmd).strip()
        except Exception:
            continue
        if raw and raw != "null":
            got = lk.normalize_locale(raw)
            if got:
                return got
    try:
        return lk.normalize_locale(dev.shell("getprop persist.sys.locale").strip()) or ""
    except Exception:
        return ""


def read_locale_list(dev: Device) -> list[str]:
    """读 `system_locales` 里的完整语言列表（用户可能配了好几个）。"""
    try:
        raw = dev.shell("settings get system system_locales").strip()
    except Exception:
        return []
    if not raw or raw == "null":
        return []
    out: list[str] = []
    for part in raw.split(","):
        norm = lk.normalize_locale(part)
        if norm and norm not in out:
            out.append(norm)
    return out


def supported_locales(dev: Device) -> list[str]:
    """设备支持的语言 tag 列表。空列表表示这条命令不可用（老系统）。"""
    try:
        raw = dev.shell("cmd locale list-device-locales")
    except Exception:
        return []
    out: list[str] = []
    for line in raw.splitlines():
        tag = line.strip()
        if not tag or " " in tag or "Error" in tag or "Unknown" in tag:
            continue
        out.append(tag)
    return out


def can_switch_live(dev: Device) -> bool:
    """这台设备支不支持不重启切语言。"""
    try:
        return bool(dev.shell("cmd locale get-device-locale").strip())
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
#   选一个设备真正支持的 tag
# ═══════════════════════════════════════════════════════════════════

#: 同一个语言的候选 tag。设备支持列表里挑第一个命中的。
#: 注意 ar：X6766 只有 ar-EG，没有 ar-SA —— 直接把 ar-SA 传进去会报
#: `Error: Invalid locale tag: ar-SA`，所以必须从支持列表里挑。
_LOCALE_ALTS: dict[str, tuple[str, ...]] = {
    "ar": ("ar-SA", "ar-EG", "ar-AE", "ar-EG-u-nu-latn", "ar"),
    "en": ("en-US", "en-GB", "en-AU", "en-IN", "en"),
    "zh": ("zh-Hans-CN", "zh-CN", "zh-Hans", "zh-Hant-TW", "zh-Hant", "zh"),
}


def resolve_tag(dev: Device, want: str, r=None) -> str:
    """把 want（ar-SA / en-US / zh-Hans-CN）落到这台设备真正支持的 tag 上。

    设备支持列表里没有同语言候选时返回 want 本身（让系统自己报错，
    总比静默切错要好）。
    """
    want = lk.normalize_locale(want)
    avail = supported_locales(dev)
    if not avail:
        return want

    avail_set = {a.lower(): a for a in avail}
    # 1) 完全一致
    if want.lower() in avail_set:
        return avail_set[want.lower()]

    # 2) 同语言的候选里挑一个
    fam = lk.locale_family(want)
    alts = _LOCALE_ALTS.get(fam, ())
    for alt in alts:
        if alt.lower() in avail_set:
            if r and alt.lower() != want.lower():
                r.log(f"这台设备没有 {want}，改用同语言的 {alt}")
            return avail_set[alt.lower()]

    # 3) 同语言前缀的任意一个
    for a in avail:
        if lk.locale_family(a) == fam:
            if r:
                r.log(f"这台设备没有 {want}，改用同语言的 {a}")
            return a
    return want


# ═══════════════════════════════════════════════════════════════════
#   切换
# ═══════════════════════════════════════════════════════════════════

def _restore_locale_list(dev: Device, tag: str, original: list[str], r=None) -> None:
    """把 system_locales 还原成「tag + 原有其它语言」。

    `set-device-locale` 会把这个列表覆盖成单值，用户原本配的多语言会丢。
    即时生效靠的是 LocaleManager 的服务端状态，跟这个设置项无关，所以
    事后补回去不会把界面弹回原语言（实测确认）。

    `original` 必须由调用方在**切换之前**读好：切换动作本身就会把列表
    砸成单值，那时再读已经晚了。
    """
    merged = [tag] + [x for x in original if not lk.same_locale(x, tag)]
    value = ",".join(merged)
    try:
        dev.shell(f"settings put system system_locales {value}")
        got = dev.shell("settings get system system_locales").strip()
        if r and got != value:
            r.log(f"提示：语言列表没写回去（想要 {value}，读到 {got}）")
    except Exception as exc:
        if r:
            r.log(f"提示：还原语言列表失败（{exc}），不影响本次触发")


def switch_locale(dev: Device, target: str, r=None, *,
                  timeout: float = BOOT_TIMEOUT,
                  force: bool = False) -> str:
    """把设备语言切成 target，返回切换后的实际 locale。**默认不重启。**

    路径优先级：
      1. `cmd locale set-device-locale`（Android 13+，当场生效，2~3 秒）
      2. 写 `system_locales` + 整机重启（老系统兜底，约 1~2 分钟）
    """
    want = lk.normalize_locale(target)
    allowed = {code for code, _ in lk.TRIGGER_LOCALES}
    if want not in allowed:
        # 允许用户直接传 ar-EG 这类同语言变体
        if lk.locale_family(want) not in {lk.locale_family(c) for c in allowed}:
            raise UiError(
                f"不支持的语言 {target!r}，只能是："
                + "、".join(f"{code}({name})" for code, name in lk.TRIGGER_LOCALES))

    cur = read_locale(dev)
    if cur and lk.same_locale(cur, want) and not force:
        if r:
            r.log(f"手机系统语言已经是{lk.label_for_locale(want)}（{cur}），不用切")
        return cur

    tag = resolve_tag(dev, want, r)
    name = lk.label_for_locale(want)

    if can_switch_live(dev):
        # 必须在切换动作之前把语言列表读下来：`set-device-locale` 会把
        # system_locales 砸成单值，事后读只剩目标语言，原来的多语言就丢了。
        original_list = read_locale_list(dev)
        if r:
            r.step(f"把手机系统语言切换成{name}（{tag}，不用重启）")
            if cur:
                r.log(f"切换前是 {cur}")
        out = dev.shell(f"cmd locale set-device-locale {tag}").strip()
        if "Invalid locale tag" in out or "Error" in out:
            raise UiError(
                f"系统拒绝了语言 tag {tag}：{out}。"
                f"这台设备支持的语言里有：{', '.join(supported_locales(dev)[:12])}…")
        time.sleep(APPLY_SETTLE)
        _restore_locale_list(dev, tag, original_list, r)
        after = read_locale(dev)
        if r:
            # 比较基准是 tag（设备真正支持的那个），不是 want：
            # 用户选了 ar-SA 而设备只有 ar-EG 时，ar-EG 就是正确结果。
            if lk.same_locale(after, tag):
                if lk.same_locale(tag, want):
                    r.ok(f"系统语言已切成{name}（{after}），没有重启")
                else:
                    r.ok(f"系统语言已切成{name}（{after}，这台设备没有 {want}），没有重启")
            else:
                r.log(f"警告：切换后读到 {after!r}，与期望的 {tag!r} 不一致")
        return after

    # ── 兜底：老系统只能写设置项 + 重启 ──────────────────────────
    if r:
        r.step(f"把手机系统语言切换成{name}（{tag}）")
        if cur:
            r.log(f"切换前是 {cur}")
        r.log("这台设备没有 cmd locale 命令，只能写 system_locales 后重启，约 1~2 分钟")
    try:
        dev.stayon(False)
    except Exception:
        pass
    dev.shell(f"settings put system system_locales {tag}")
    got = dev.shell("settings get system system_locales").strip()
    if got != tag:
        raise UiError(f"写入 system_locales 失败：想要 {tag}，实际读到 {got!r}")

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
    _wake_and_unlock(dev, r)

    after = read_locale(dev)
    if r:
        if lk.same_locale(after, want):
            r.ok(f"系统语言已是{name}")
        else:
            r.log(f"警告：重启后读到 {after!r}，与期望的 {want!r} 不一致")
    return after


# ═══════════════════════════════════════════════════════════════════
#   兜底路径专用：等开机 + 解锁
# ═══════════════════════════════════════════════════════════════════

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
            r.log(f"自动解锁没成功（{exc}），可能需要手动解锁一次")


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
    """触发前把语言对齐到目标值。返回 True 表示真的切了。

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
    print("list  :", read_locale_list(d))
    print("can_switch_live:", can_switch_live(d))
    print("tag   :", resolve_tag(d, target))
    print("after :", switch_locale(d, target))

"""生活服务卡片：一键打车 / 一键点餐。

触发方式（用户提供）：
    am start-foreground-service --user 0 \
      -a "core.intent.action.DISPATCH_EVENT" \
      --es "data_type" "AppSuggestEvent" \
      --es "action_type" "listener" \
      --es "json_data" '{"app_list":["<包名>"]}'

一键打车：Yango，任何时间。
一键点餐：foodpanda，仅午餐 10:45~13:00、晚餐 17:00~19:00。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

import card_probe
from phone_ctl import KEY_HOME, Device, UiError

from scenario_alarm import DESKCLOCK_PKG  # noqa: F401  (仅保持同目录导入习惯)
from scenario_birthday import (
    Runner,
    _cli_emit,
    _prepare,
    device_date,
    ensure_home_before_confirm,
    set_system_datetime,
)

TAXI_PACKAGE = "com.yandex.yango"
FOOD_PACKAGE = "com.global.foodpanda.android"

# 网络共享路径，直接从服务器拉取 APK
TAXI_APK = r"\\10.205.4.20\Odc_Temp_File\archermind\zixin.mei\apk\yango_full.apk"
FOOD_APK = r"\\10.205.4.20\Odc_Temp_File\archermind\zixin.mei\apk\foodpanda.apk"

# 在其他设备上「adb install 成功过」的完整版本大小（字节），用于识别没传完的文件。
# yango_full.apk 2026-10-30 实测 329467629 字节，`adb install -r -t -d` 直接 Success；
# foodpanda.apk 129913559 字节，其实是 XAPK（manifest.json + base + 19 个 config 分包），
# 走 `adb install` 一定报 INSTALL_PARSE_FAILED_UNEXPECTED_EXCEPTION: AndroidManifest.xml，
# 必须解包后用 install-multiple 一次装进同一个 session。
TAXI_OK_SIZES = (329467629,)
FOOD_OK_SIZES = (129913559,)

# 点餐卡片允许的时段（分钟数）
LUNCH = (10 * 60 + 45, 13 * 60)
DINNER = (17 * 60, 19 * 60)

# 桌面「智慧建议」里认卡片用的文案。main.py 的场景注册表直接引用这里
# （SCENARIOS[*].card_keywords），保证「场景引擎的自动确认」和「本模块
# 重试前先看一眼」认的是同一批关键词，不会一处改了另一处忘掉。
#
# 同一张卡在三种系统语言下文案完全不同（真机 uiautomator dump 实测）：
#   打车：出行时间 / 差不多该出发了（zh）
#         Ride Hailing / Time to get a ride（en）
#         طلب سيارة أجرة / حان وقت الحصول على رحلة（ar-EG）
#   点餐：点餐时间 / 挑份喜欢的，准时开饭（zh）
#         Food Ordering / Time to grab a bite（en）
#         طلب الطعام / حان وقت تناول لقمة（ar-EG）
# 所有语言都要认，否则「卡片明明在桌面上却被判成没出卡」，白白清缓存重试。
#
# 阿拉伯语注意两点：
#   * 两张卡的阿语标题都以 «طلب»（请求）开头，**不能用裸 «طلب»** 当关键词，
#     否则打车会把点餐卡也认成命中。这里用完整短语 + 各自独有的词根。
#   * 阿语是从右往左排的，dump 出来的字符串里可能夹着方向控制符，所以除了
#     整句之外再补几个「本身就是唯一」的短词（سيارة / لقمة），容错更高。
TAXI_KEYWORDS = ("Ride Hailing", "Time to get a ride",
                 "出行时间", "差不多该出发了",
                 "طلب سيارة أجرة", "سيارة أجرة", "سيارة",
                 "حان وقت الحصول على رحلة",
                 "打车", "Yango", "yango", "ride", "taxi")
FOOD_KEYWORDS = ("Food Ordering", "Time to grab a bite",
                 "点餐", "挑份喜欢的",
                 "طلب الطعام", "الطعام", "حان وقت تناول لقمة", "لقمة",
                 "foodpanda", "Foodpanda", "外卖", "food", "delivery")
CARD_KEYWORDS: dict[str, tuple[str, ...]] = {
    TAXI_PACKAGE: TAXI_KEYWORDS,
    FOOD_PACKAGE: FOOD_KEYWORDS,
}

# 发完机之后回桌面小部件实时盯多久（秒）：窗口内一出现就立刻收工，
# 窗口结束还没出现就清缓存按原步骤重试一次。
CHECK_WINDOW_SEC = 10


def _app_installed(dev: Device, package: str) -> bool:
    out = dev.shell(f"pm path {package}")
    return "package:" in out


def _adb(dev: Device, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["adb", "-s", dev.serial, *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=900)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def _zip_broken(path: str, ok_sizes: tuple[int, ...]) -> str | None:
    """本地预检：共享上的文件可能是没传完的 APK，或其实是被改名的 XAPK。

    返回问题描述（None 表示可以交给 adb install）。
    注意：XAPK 不算「坏文件」——它只是不能走 adb install，_install_local 会改用
    install-multiple 拆包装，所以这里只在真正装不下去（截断/无清单）时返回。
    """
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return f"读不到共享文件：{exc}"
    if ok_sizes and size not in ok_sizes:
        return f"共享上的文件大小是 {size} 字节，与其他设备上能装成功的版本大小不一致，疑似没传完"

    def _issue(issue: str) -> str | None:
        return f"{issue}（文件大小 {size} 字节）"

    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                return _issue(f"压缩包内部条目 {bad} 已损坏")
            names = set(zf.namelist())
            if "AndroidManifest.xml" not in names and "manifest.json" not in names:
                return _issue("压缩包里既没有 AndroidManifest.xml 也没有 manifest.json，不像正常的 APK/XAPK")
    except zipfile.BadZipFile:
        return _issue("不是完整的 zip 包（缺少中央目录/EOCD，典型是上传过程中被截断）")
    except Exception as exc:  # noqa: BLE001  预检本身出错就当未知问题放行，让 adb 给出真实报错
        return f"预检失败：{type(exc).__name__}: {exc}"
    return None


def _xapk_modules(path: str) -> list[str]:
    """如果 path 是 XAPK（zip 里有 manifest.json），返回里面待安装的 .apk 条目名，否则返回 []。

    安装顺序按 manifest.json 的 split_apks：
      1. base 包（id=base）必须排第一，adb install-multiple 会把它当主包；
      2. 再按 ABI（arm64_v8a / armeabi 等）→ 屏幕密度（xxhdpi 等）→ 语言 → 其它。
    adb 走 streamed install 时会把所有分包塞进同一个 session，顺序错了系统会
    直接报 INSTALL_FAILED_INVALID_APK，所以这里不依赖 zip 里的物理顺序。
    """

    def _rank(item: dict) -> int:
        sid = str(item.get("id") or "").lower()
        if sid == "base":
            return 0
        if "arm" in sid or "x86" in sid or "mips" in sid:
            return 1
        if "dpi" in sid:          # hdpi/xhdpi/xxhdpi/...
            return 2
        return 3

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                return []
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            entries = [e for e in (manifest.get("split_apks") or [])
                       if isinstance(e, dict) and e.get("file") in names
                       and e["file"].endswith(".apk")]
            order = {e["file"]: (i, _rank(e)) for i, e in enumerate(entries)}
            # 分包列表里没列、但 zip 里有的 .apk 也一起装，排在最后
            mods = [e["file"] for e in entries]
            mods += [n for n in names if n.endswith(".apk") and n not in order]
            mods.sort(key=lambda n: order.get(n, (len(entries), 9)))
            return mods
    except Exception:  # noqa: BLE001
        return []


def _install_xapk(dev: Device, r: Runner, path: str, package: str,
                  label: str) -> bool:
    """XAPK 拆包安装：解到临时目录后 `adb install-multiple -r -t -d base + splits`。"""
    mods = _xapk_modules(path)
    if not mods:
        return False
    r.log(f"{label} 是 XAPK 安装包（{len(mods)} 个分包），改用 install-multiple 拆包安装")
    tmp = tempfile.mkdtemp(prefix=f"xapk_{package.split('.')[-1]}_")
    try:
        with zipfile.ZipFile(path) as zf:
            for name in mods:
                zf.extract(name, tmp)
        files = [os.path.join(tmp, name) for name in mods]
        missing = [f for f in files if not os.path.exists(f)]
        if missing:
            r.log(f"解包后缺少文件：{missing[:3]}")
            return False
        r.log("安装分包：" + ", ".join(os.path.basename(f) for f in files[:4])
              + (f" … 共 {len(files)} 个" if len(files) > 4 else ""))
        rc, out = _adb(dev, "install-multiple", "-r", "-t", "-d", *files)
        if rc != 0:
            r.log(f"install-multiple 失败：{out.strip()[:400]}")
            return False
        if not _app_installed(dev, package):
            r.log("install-multiple 返回成功但 pm path 仍找不到包")
            return False
        r.ok(f"XAPK 拆包安装成功（{len(files)} 个分包）")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _install_local(dev: Device, r: Runner, package: str) -> bool:
    if package == TAXI_PACKAGE:
        path, ok_sizes, label = TAXI_APK, TAXI_OK_SIZES, "Yango"
    elif package == FOOD_PACKAGE:
        path, ok_sizes, label = FOOD_APK, FOOD_OK_SIZES, "foodpanda"
    else:
        return False

    r.log(f"从网络共享安装 {label}：{path}")
    problem = _zip_broken(path, ok_sizes)
    if problem:
        r.log(f"预检不通过：{problem}")
        r.log("先按原命令试装一次，报错原样回传")

    # XAPK（带 manifest.json）不能用 adb install，先拆包走 install-multiple
    if _xapk_modules(path):
        if _install_xapk(dev, r, path, package, label):
            return True
        r.log("XAPK 拆包安装失败，退回单文件 adb install 再试一次")

    rc, out = _adb(dev, "install", "-r", "-t", "-d", path)
    if rc != 0:
        r.log(f"网络共享安装失败：{out.strip()[:400]}")
        if problem:
            r.log(f"安装失败的根因：{problem}")
        return False
    if not _app_installed(dev, package):
        r.log("adb install 返回成功但 pm path 仍找不到包")
        return False
    r.ok("网络共享 APK 安装成功")
    return True


def _ensure_app(dev: Device, r: Runner, package: str) -> None:
    """触发卡片前的检查：已安装直接继续；没装直接从网络共享路径 adb install。"""
    r.step(f"检查应用是否已安装：{package}")
    if _app_installed(dev, package):
        r.ok("已安装")
        return

    r.step(f"未检测到 {package}，直接从网络共享路径安装")
    if _install_local(dev, r, package):
        return

    path = TAXI_APK if package == TAXI_PACKAGE else FOOD_APK
    sizes = TAXI_OK_SIZES if package == TAXI_PACKAGE else FOOD_OK_SIZES
    problem = _zip_broken(path, sizes)
    hint = f"根因：{problem}" if problem else "共享路径可能不可访问"
    raise UiError(f"从网络共享路径安装 {package} 失败，{hint}。共享路径：{path}")


def _in_food_window(hour: int, minute: int) -> bool:
    m = hour * 60 + minute
    return LUNCH[0] <= m <= LUNCH[1] or DINNER[0] <= m <= DINNER[1]


def _service_component(dev: Device) -> str | None:
    """查哪个服务注册了 core.intent.action.DISPATCH_EVENT。

    某些系统上 am 对隐式 service intent 会报 "Not found"，必须用
    cmd package query-services 找到组件名再用 -n 显式启动。

    输出格式两种都认：
      · 一行一个：com.example.tpk.client/.RuleMockService
      · 分块格式（XOS 17）：Service #0: / priority=... / com.xxx/.Yyy
    之前只认第一种，第二种设备上会静默退化成隐式启动，然后报 "Not found"。
    """
    out = dev.shell(
        'cmd package query-services --brief '
        '-a core.intent.action.DISPATCH_EVENT')
    for line in out.splitlines():
        line = line.strip()
        if re.fullmatch(r"[A-Za-z0-9_.]+/[\w.$]+", line):
            return line
    m = re.search(r"^\s*([A-Za-z0-9_.]+/[\w.$]+)\s*$", out, re.MULTILINE)
    return m.group(1) if m else None


def dispatch_app_suggest(dev: Device, app_package: str) -> str:
    """发送 AppSuggestEvent，让系统展示该包名的生活服务卡片。"""
    data = json.dumps({"app_list": [app_package]}, separators=(",", ":"))
    comp = _service_component(dev)
    target = f"-n {comp} " if comp else ""
    cmd = (
        "am start-foreground-service --user 0 "
        f"{target}"
        '-a "core.intent.action.DISPATCH_EVENT" '
        '--es "data_type" "AppSuggestEvent" '
        '--es "action_type" "listener" '
        f'--es "json_data" \'{data}\''
    )
    if comp:
        dev.log(f"AppSuggest 服务组件：{comp}")
    else:
        dev.log("没有找到 DISPATCH_EVENT 服务，回退隐式启动")
    return dev.shell(cmd)


def _card_visible(dev: Device, app_package: str, r):
    """只「看一眼」桌面智慧建议里有没有目标卡片，不发事件、不清缓存。

    用 `card_probe.find_card_fast`（只看当前屏，约 2.5s）而不是
    `find_card_anywhere`（会翻满轮播，6.7~10.5s）：这里是在实时盯卡，
    刚生成的卡片一定在第一屏，翻轮播纯属白花 4.5s —— 而窗口只有 10 秒，
    慢一档就变成「一次都查不完」。

    find_card_fast 内部会先回首页、收起灵动岛，然后 dump 控件树读文案 ——
    全是只读操作，不会把 App 拉起来，也不会破坏当前场景。
    这里刻意不复用 r.confirm()：main.py 的 _confirm_fn 自带「90 秒 +
    每轮 pm clear」的循环，那个循环跑在本函数里会叠成好几分钟。

    返回 `CardHit`（命中）或 None。**返回整个 hit 而不是 bool**，是为了让
    调用方命中后直接拿它截图入库，不必再走一遍 _confirm_fn 的重扫。
    """
    keywords = CARD_KEYWORDS.get(app_package) or (app_package,)
    hit = card_probe.find_card_fast(dev, keywords, log=r.log)
    if hit:
        r.log(f"桌面已出现卡片：「{hit.text}」（关键词 {hit.keyword}）")
    return hit


def _watch_card(dev: Device, r, app_package: str,
                window_sec: int = CHECK_WINDOW_SEC):
    """在桌面上**实时盯**智慧建议小部件，window_sec 秒内出卡就立刻返回 hit。

    和老的「先干等 N 秒、时间到了才检查一次」不同：发完事件立刻回桌面，
    每轮 dump 一次控件树，一出现就收工 —— 卡片通常 2~4 秒就出来了，不必
    白等满整个窗口。窗口到点还没出才返回 None，由调用方决定清缓存重试。

    节流说明：`find_card_fast` 自己就要 ~2.5s（dump 控件树是 adb 的硬开销），
    所以两轮之间不再固定 sleep 1 秒 —— 那样会白白把节奏拖到 3.5s 一轮。
    只有窗口还剩很多时才补一点点间隔，避免空转刷屏。
    """
    deadline = time.monotonic() + window_sec
    while True:
        r.check()                       # 暂停 / 结束在这里生效
        hit = _card_visible(dev, app_package, r)
        if hit:
            return hit
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        r.tick(max(1, int(round(left))))   # 状态栏显示剩余秒数
        # 探测本身已经花了 ~2.5s；只剩不到 1 秒就别再睡，直接再探一次。
        if left > 1.2:
            time.sleep(min(0.4, left - 1.0))


def _fire_and_watch(dev: Device, r, app_package: str,
                    window_sec: int = CHECK_WINDOW_SEC):
    """发一次 AppSuggestEvent，然后**马上**回桌面小部件盯 window_sec 秒。

    返回命中时的 `CardHit`，窗口内没出卡返回 None。只负责发和看，
    清缓存重试由 run() 决定。
    """
    out = dispatch_app_suggest(dev, app_package)
    err = ("Error" in out or "Exception" in out
           or "Not found" in out or "no service started" in out)
    if err:
        # 这条 DISPATCH_EVENT 只是额外的一条投递路径：没装 com.example.tpk.client
        # 的机器上 query-services 返回 "No services found"，回退隐式启动必然报
        # "Not found; no service started."。卡片实际由已安装的 App 自身触发，
        # 所以这里只降级成警告，不判失败。
        r.log("提示：AppSuggestEvent 投递未成功（"
              f"{out.strip()[:160]}），这台机器没有 DISPATCH_EVENT mock 服务；"
              "卡片由 App 自身触发，继续等待出卡")
    else:
        r.ok(out.strip()[:200])

    # 发完立刻回桌面：用户口径是「输入指令后马上返回桌面智慧建议小部件实时检查」。
    # 这里不再调 ensure_home_before_confirm（它要 dump 整棵树判断首页，实测 3.1s）；
    # find_card_fast 内部用 focus() 判断当前窗口，不在桌面才按 HOME，快 30 倍。
    r.step(f"回桌面智慧建议小部件实时检查（{window_sec} 秒）")
    return _watch_card(dev, r, app_package, window_sec)


def run(dev: Device | None = None, emit=None, *, app_package: str,
        hour: int | None = None, minute: int | None = None,
        wait_sec: int = 5, control: dict | None = None,
        confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log
    if not app_package:
        raise UiError("缺少 app_package（一键打车/点餐包名）")
    if not (2 <= wait_sec <= 120):
        raise UiError("wait_sec 必须在 2~120 秒之间")

    result = {"app_package": app_package, "wait_sec": wait_sec}

    # 卡片触发前先检查 App，没有就触发本地 APK / 商店安装
    _ensure_app(dev, r, app_package)
    result["app_installed"] = True

    if hour is not None and minute is not None:
        hour, minute = int(hour), int(minute)   # 外部脚本可能传字符串，:02d 要求 int
        if app_package == FOOD_PACKAGE and not _in_food_window(hour, minute):
            raise UiError(
                f"点餐卡片只在午餐 10:45~13:00 或晚餐 17:00~19:00 出现，"
                f"当前设置 {hour:02d}:{minute:02d} 不在窗口内")
        target = device_date(dev)
        result["time"] = f"{hour:02d}:{minute:02d}"
        set_system_datetime(dev, r, target, hour, minute)
    else:
        r.log("不调整系统时间（一键打车任何时间都可触发）")

    # 用户口径（两张生活服务卡一致）：发完指令**马上**回桌面智慧建议小部件
    # 实时盯 wait_sec（默认 10 秒），一出现就收工；到点还没出卡，就清空三个
    # 原子服务的数据，再**按原步骤**（回桌面亮屏 → 发 AppSuggestEvent →
    # 实时检查）整轮重来一次。两轮都不出才判失败。
    rounds = 2

    r.step("回桌面并保持亮屏")
    _prepare(dev, r)
    dev.key(KEY_HOME)
    time.sleep(0.6)
    dev.stayon(True)
    try:
        for rnd in range(1, rounds + 1):
            if rnd > 1:
                r.step("清缓存后按原步骤重试")
                dev.clear_atomic_services()
                r.log("已清空 launcher3 / atomicbrain / atomiccore，"
                      "等桌面重建后再发一次事件…")
                # 清完 launcher 后桌面要重建，立刻 dump 只会读到空小部件。
                for _ in range(3):
                    r.check()
                    time.sleep(1)
                r.step("回桌面并保持亮屏")
                _prepare(dev, r)
                dev.key(KEY_HOME)
                time.sleep(0.6)
                dev.stayon(True)

            tag = f"（第 {rnd}/{rounds} 轮）" if rounds > 1 else ""
            r.step(f"发送 AppSuggestEvent：{app_package}{tag}")
            hit = _fire_and_watch(dev, r, app_package, wait_sec)
            if hit:
                # 认到卡了：把 CardHit 交给 Runner，main.py 的 _confirm_fn 看到
                # 就直接截图入库、不再回头重扫 —— 「只要识别到了就报成功」。
                r.pre_hit = hit
                r.shot("生活服务卡片")
                break
            if rnd < rounds:
                r.log(f"实时检查了 {wait_sec} 秒还没出现卡片，清缓存重试一次")
        else:
            raise UiError(
                f"实时检查了 {wait_sec} 秒、清缓存按原步骤重试一次后，桌面仍然"
                f"没有出现生活服务卡片（{app_package}）。请确认该 App 已登录、"
                f"系统时间与网络正常后重试。")

        r.step("确认生活服务卡片是否出现")
        if not r.confirm():
            r.log("桌面未确认，展开通知栏再检查")
            dev.shell("cmd statusbar expand-notifications")
            time.sleep(1.0)
            r.shot("通知栏")
            ok = r.confirm()
            dev.shell("cmd statusbar collapse")
            time.sleep(0.4)
            if not ok:
                raise UiError("桌面和通知栏都没有确认到生活服务卡片")
        ensure_home_before_confirm(dev, r)
        r.ok("已确认生活服务卡片")
    finally:
        dev.stayon(False)

    result["tries"] = rnd
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (
        f"完成。已发送 AppSuggestEvent（{app_package}），"
        f"桌面应出现对应的一键生活服务卡片。")
    return result


if __name__ == "__main__":
    import sys

    pkg = sys.argv[1] if len(sys.argv) > 1 else TAXI_PACKAGE
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else CHECK_WINDOW_SEC
    try:
        out = run(emit=_cli_emit, app_package=pkg, wait_sec=wait)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

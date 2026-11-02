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
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from phone_ctl import KEY_HOME, Device, UiError

from scenario_alarm import DESKCLOCK_PKG  # noqa: F401  (仅保持同目录导入习惯)
from scenario_birthday import (
    Runner,
    _cli_emit,
    _prepare,
    device_date,
    set_system_datetime,
)

TAXI_PACKAGE = "com.yandex.yango"
FOOD_PACKAGE = "com.global.foodpanda.android"

APK_DIR = Path(__file__).with_name("apks")
TAXI_APK = APK_DIR / "yango_full.apk"
FOOD_XAPK = APK_DIR / "foodpanda.apk"
FOOD_EXTRACT = APK_DIR / "foodpanda_xapk"

# 点餐卡片允许的时段（分钟数）
LUNCH = (10 * 60 + 45, 13 * 60)
DINNER = (17 * 60, 19 * 60)


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


def _extract_food_xapk() -> None:
    if FOOD_EXTRACT.exists():
        return
    if not FOOD_XAPK.exists():
        raise UiError(f"foodpanda XAPK 不存在：{FOOD_XAPK}")
    FOOD_EXTRACT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(FOOD_XAPK) as z:
        z.extractall(FOOD_EXTRACT)


def _install_local(dev: Device, r: Runner, package: str) -> bool:
    if package == TAXI_PACKAGE:
        if not TAXI_APK.exists():
            return False
        r.log(f"本地 APK 安装 Yango：{TAXI_APK.name}")
        rc, out = _adb(dev, "install", "-r", "-g", str(TAXI_APK))
    elif package == FOOD_PACKAGE:
        try:
            _extract_food_xapk()
        except UiError as exc:
            r.log(str(exc))
            return False
        base = FOOD_EXTRACT / "com.global.foodpanda.android.apk"
        if not base.exists():
            r.log("foodpanda 解包目录里没有 base APK")
            return False
        splits = sorted(FOOD_EXTRACT.glob("config.*.apk"))
        r.log(f"本地 XAPK 安装 foodpanda：base + {len(splits)} splits")
        rc, out = _adb(dev, "install-multiple", "-r", "-g",
                       str(base), *[str(p) for p in splits])
    else:
        return False

    if rc != 0:
        r.log(f"本地安装失败：{out.strip()[:400]}")
        return False
    if not _app_installed(dev, package):
        r.log("adb install 返回成功但 pm path 仍找不到包")
        return False
    r.ok("本地 APK 安装成功")
    return True


def _ensure_app(dev: Device, r: Runner, package: str) -> None:
    """触发卡片前的检查：已安装直接继续；没装则本地 APK 安装，
    本地没有安装包时打开应用商店详情页，等用户在手机上装好。"""
    r.step(f"检查应用是否已安装：{package}")
    if _app_installed(dev, package):
        r.ok("已安装")
        return

    r.step(f"未检测到 {package}，触发下载/安装")
    if _install_local(dev, r, package):
        return

    r.log("本地没有可用安装包，打开应用商店详情页，请在手机上点击安装")
    dev.shell(
        f'am start -a android.intent.action.VIEW '
        f'-d "market://details?id={package}"')
    r.log("等待商店安装完成（最多 180 秒）…")
    for remain in range(180, 0, -1):
        r.check()
        if remain % 5 == 0:
            r.tick(remain)
        if _app_installed(dev, package):
            r.ok("已检测到安装完成")
            return
        time.sleep(1)
    raise UiError(f"{package} 未安装，且商店自动安装超时；请在手机上装好后重试")


def _in_food_window(hour: int, minute: int) -> bool:
    m = hour * 60 + minute
    return LUNCH[0] <= m <= LUNCH[1] or DINNER[0] <= m <= DINNER[1]


def _service_component(dev: Device) -> str | None:
    """查哪个服务注册了 core.intent.action.DISPATCH_EVENT。

    某些系统上 am 对隐式 service intent 会报 "Not found"，必须用
    cmd package query-services 找到组件名再用 -n 显式启动。
    """
    out = dev.shell(
        'cmd package query-services --brief '
        '-a core.intent.action.DISPATCH_EVENT')
    for line in out.splitlines():
        line = line.strip()
        if re.fullmatch(r"[A-Za-z0-9_.]+/[\w.$]+", line):
            return line
    return None


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


def run(dev: Device | None = None, emit=None, *, app_package: str,
        hour: int | None = None, minute: int | None = None,
        wait_sec: int = 5, control: dict | None = None,
        confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log
    if not app_package:
        raise UiError("缺少 app_package（一键打车/点餐包名）")
    if not (2 <= wait_sec <= 60):
        raise UiError("wait_sec 必须在 2~60 秒之间")

    result = {"app_package": app_package, "wait_sec": wait_sec}

    # 卡片触发前先检查 App，没有就触发本地 APK / 商店安装
    _ensure_app(dev, r, app_package)
    result["app_installed"] = True

    if hour is not None and minute is not None:
        if app_package == FOOD_PACKAGE and not _in_food_window(hour, minute):
            raise UiError(
                f"点餐卡片只在午餐 10:45~13:00 或晚餐 17:00~19:00 出现，"
                f"当前设置 {hour:02d}:{minute:02d} 不在窗口内")
        target = device_date(dev)
        result["time"] = f"{hour:02d}:{minute:02d}"
        set_system_datetime(dev, r, target, hour, minute)
    else:
        r.log("不调整系统时间（一键打车任何时间都可触发）")

    r.step("回桌面并保持亮屏")
    _prepare(dev, r)
    dev.key(KEY_HOME)
    time.sleep(0.6)
    dev.stayon(True)

    r.step(f"发送 AppSuggestEvent：{app_package}")
    out = dispatch_app_suggest(dev, app_package)
    if "Error" in out or "Exception" in out:
        raise UiError(f"AppSuggestEvent 发送失败：{out.strip()[:400]}")
    r.ok(out.strip()[:200])

    r.step(f"等待 {wait_sec} 秒检查生活服务卡片")
    for remain in range(wait_sec, 0, -1):
        r.check()
        r.tick(remain)
        time.sleep(1)
    time.sleep(1.0)
    r.shot("生活服务卡片")

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
    r.ok("已确认生活服务卡片")

    dev.stayon(False)
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
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    try:
        out = run(emit=_cli_emit, app_package=pkg, wait_sec=wait)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

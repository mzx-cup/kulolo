"""跨国 / 跨城智能建议卡片触发场景。

两种触发方式，前端下拉框自选（method 参数）：

A. 定位切换法  method=location
   定位到上海 → 亮屏停 20 分钟 → 定位切到新德里 → 亮屏再停 20 分钟
   → 上滑回桌面，跨国 / 跨城卡片出现。
   定位走 mock provider（不用 root、不用装模拟位置 App）：
       appops set 2000 android:mock_location allow
       cmd location providers add-test-provider gps ...
       cmd location providers set-test-provider-location gps --location LAT,LON
   provider 名必须写 gps：自造名字（如 test_gps）不会被 fused 采纳，
   而卡片引擎 com.transsion.atomicbrain 正是从 fused 取位置。

B. Mock 事件法  method=mock_country / mock_city_1148 / mock_city_1057
   直接发系统广播服务事件：
       am start-foreground-service --user 0 \\
         -a "core.intent.action.DISPATCH_EVENT" \\
         --es "data_type" "LocationEvent" \\
         --es "action_type" "listener" \\
         --es "json_data" '{"country_code":"IN","city_code":""}'
   城市码：留空 = 跨国卡片；1148 = 德里跨城卡片；1057 = 新德里跨城卡片。
"""
from __future__ import annotations

import json
import re
import time

from phone_ctl import KEY_HOME, Device, UiError

from scenario_birthday import (
    Runner,
    _cli_emit,
    _prepare,
    _unlock_with_retries,
)
from scenario_app_suggest import _service_component

DISPATCH_ACTION = "core.intent.action.DISPATCH_EVENT"
DATA_TYPE = "LocationEvent"

# 上海人民广场 / 新德里市区
SHANGHAI = (31.230416, 121.473701)
NEW_DELHI = (28.613900, 77.209000)

CITY_CARDS = {
    "mock_country": ("跨国卡片（IN · 城市留空）", ""),
    "mock_city_1148": ("跨城卡片 · 德里（1148）", "1148"),
    "mock_city_1057": ("跨城卡片 · 新德里（1057）", "1057"),
}
METHODS = {
    "location": "定位切换法（上海 20 分钟 → 新德里 20 分钟）",
    "mock_country": CITY_CARDS["mock_country"][0],
    "mock_city_1148": CITY_CARDS["mock_city_1148"][0],
    "mock_city_1057": CITY_CARDS["mock_city_1057"][0],
}

_RE_LOC = re.compile(r"last location=Location\[([\w.-]+) ([-\d.]+),([-\d.]+)")


# ---------------------------------------------------------------- 定位 mock
def _location_enabled(dev: Device) -> bool:
    return "true" in dev.shell("cmd location is-location-enabled").strip().lower()


def _ensure_location_enabled(dev: Device, r: Runner) -> None:
    if _location_enabled(dev):
        return
    r.log("定位服务是关闭的，先打开")
    mode = _location_mode(dev) or "3"
    dev.shell(f"settings put secure location_mode {mode}")
    time.sleep(1.0)
    if not _location_enabled(dev):
        raise UiError(f"无法打开定位服务（settings put secure location_mode {mode} 无效）")


def _last_locations(dev: Device) -> dict[str, tuple[float, float]]:
    out = dev.shell('dumpsys location | grep "last location="')
    return {m.group(1): (float(m.group(2)), float(m.group(3)))
            for m in _RE_LOC.finditer(out)}


def set_mock_location(dev: Device, r: Runner, loc: tuple[float, float],
                      label: str) -> bool:
    """把 gps / fused 位置改到 loc。返回 fused 是否已跟着变（只是提示，不阻断）。"""
    lat, lon = loc
    r.step(f"把手机定位改到{label} {lat},{lon}")
    dev.shell("appops set 2000 android:mock_location allow")
    dev.shell("cmd location providers add-test-provider gps "
              "--supportsAltitude --supportsSpeed --supportsBearing")
    dev.shell(f"cmd location providers set-test-provider-location gps "
              f"--location {lat},{lon} --accuracy 5")
    out = dev.shell("cmd location providers set-test-provider-enabled gps true")
    if "Error" in out or "Exception" in out:
        raise UiError(f"启用 gps 测试 provider 失败：{out.strip()[:300]}")

    seen: dict[str, tuple[float, float]] = {}
    for _ in range(10):
        time.sleep(1.0)
        seen = _last_locations(dev)
        if "gps" in seen:
            break
    gps = seen.get("gps")
    if gps is None:
        raise UiError("定位没有生效：dumpsys location 里没有 gps 的 last location")
    if abs(gps[0] - lat) > 0.001 or abs(gps[1] - lon) > 0.001:
        raise UiError(f"定位没有生效：期望 {lat},{lon}，实际 {gps[0]},{gps[1]}")
    fused = seen.get("fused")
    follow = fused is not None and abs(fused[0] - lat) < 0.05 and abs(fused[1] - lon) < 0.05
    r.ok(f"gps={gps[0]:.6f},{gps[1]:.6f}"
         + (f"｜fused={fused[0]:.6f},{fused[1]:.6f}" if fused else "｜fused 未读到")
         + ("" if follow else "（fused 还没跟上，继续观察）"))
    return follow


def _location_mode(dev: Device) -> str:
    return (dev.shell("settings get secure location_mode") or "").strip()


def clear_mock_location(dev: Device) -> None:
    """收尾：删掉测试 provider，并重开一次定位开关清掉缓存的 mock 坐标。

    本机（X6765 / XOS 17）实测：
      · `cmd location providers set-location-enabled` 这个子命令根本不存在
        （报 Unknown command），之前用它做 toggle 等于什么都没做；
      · 正确的是改 secure setting location_mode（0=全关，3=高精度）；
      · 顺序必须是先 remove-test-provider、再关再开。反过来（先 toggle）
        会让 gps provider 进入「不是 test provider」状态，之后 add 返回
        False、remove 返回 False，最后一条 mock 坐标就永久留在
        dumpsys location 里（last location 一直挂着 28.6139,77.209）。
    """
    dev.shell("cmd location providers remove-test-provider gps")
    dev.shell("cmd location providers set-test-provider-enabled gps false")
    mode = _location_mode(dev)
    if mode:
        dev.shell("settings put secure location_mode 0")
        time.sleep(0.8)
        dev.shell(f"settings put secure location_mode {mode}")
        time.sleep(1.5)


# ---------------------------------------------------------------- 桌面 / 等待
def _sit_on_desktop(dev: Device, r: Runner, seconds: int, label: str) -> None:
    """回桌面、保持亮屏停 seconds 秒。"""
    r.step(f"在桌面亮屏停留 {seconds // 60} 分 {seconds % 60} 秒：{label}")
    dev.stayon(True)
    _unlock_with_retries(dev, r, unlock_retries=2, wake=True)
    dev.key(KEY_HOME)
    time.sleep(0.8)
    deadline = time.time() + seconds
    last_tick = -1
    while True:
        r.check()
        remain = int(deadline - time.time())
        if remain <= 0:
            break
        if remain != last_tick and (remain % 5 == 0 or remain <= 5):
            r.tick(remain)
            last_tick = remain
        time.sleep(1)
    r.ok(label)


def _swipe_up_to_home(dev: Device, r: Runner) -> None:
    """上滑进桌面：回桌面 → 底部上滑 → 再回桌面。"""
    r.step("上滑进入桌面")
    w, h = dev.screen_size()
    dev.key(KEY_HOME)
    time.sleep(0.8)
    dev.swipe(w // 2, int(h * 0.88), w // 2, int(h * 0.42), 260)
    time.sleep(1.2)
    dev.key(KEY_HOME)
    time.sleep(0.8)
    r.ok(f"{w}x{h}")


# ---------------------------------------------------------------- 事件下发
def location_event_json(city_code: str) -> str:
    return json.dumps({"country_code": "IN", "city_code": city_code},
                      separators=(",", ":"))


def dispatch_location_event(dev: Device, data: str) -> str:
    """发 LocationEvent。隐式 service 在部分系统上找不到，先查组件再 -n 显式启动。"""
    comp = _service_component(dev)
    target = f"-n {comp} " if comp else ""
    cmd = (
        "am start-foreground-service --user 0 "
        f"{target}"
        f'-a "{DISPATCH_ACTION}" '
        f'--es "data_type" "{DATA_TYPE}" '
        '--es "action_type" "listener" '
        f"--es \"json_data\" '{data}'"
    )
    dev.log(f"LocationEvent 服务组件：{comp or '（隐式）'}")
    dev.log(f"命令：{cmd}")
    return dev.shell(cmd)


# ---------------------------------------------------------------- 主流程
def _run_location(dev: Device, r: Runner, wait_min: int, settle_sec: int) -> bool:
    minutes = max(1, int(wait_min))
    _ensure_location_enabled(dev, r)
    try:
        set_mock_location(dev, r, SHANGHAI, "上海")
        _sit_on_desktop(dev, r, minutes * 60, "上海")
        set_mock_location(dev, r, NEW_DELHI, "新德里")
        _sit_on_desktop(dev, r, minutes * 60, "新德里")
        _swipe_up_to_home(dev, r)
        # 先拍照确认桌面卡片，再还原定位：清缓存会让 provider 重新注册，
        # 卡片还没来得及刷新就没了，所以确认界面必须在 finally 之前。
        r.step(f"等待 {settle_sec} 秒检查跨国 / 跨城卡片")
        for remain in range(settle_sec, 0, -1):
            r.check()
            r.tick(remain)
            time.sleep(1)
        r.shot("桌面 跨国跨城卡片")
        r.step("确认跨国 / 跨城卡片是否出现")
        ok = bool(r.confirm())
        if not ok:
            r.shot("桌面 未出现跨国跨城卡片")
            r.log("桌面没有看到跨国 / 跨城卡片，本次结束（可点重试重新触发）")
        return ok
    finally:
        clear_mock_location(dev)
        r.log("已还原定位（删除 gps 测试 provider，重开一次定位开关）")


def _run_mock(dev: Device, r: Runner, method: str, wait_sec: int) -> bool:
    label, city_code = CITY_CARDS[method]
    data = location_event_json(city_code)

    _prepare(dev, r)
    dev.key(KEY_HOME)
    time.sleep(0.6)
    dev.stayon(True)

    r.step(f"发送 LocationEvent：{label}")
    out = dispatch_location_event(dev, data)
    if "Error" in out or "Exception" in out:
        raise UiError(f"LocationEvent 发送失败：{out.strip()[:400]}")
    r.ok(out.strip()[:200] or "已下发")

    r.step(f"等待 {wait_sec} 秒检查卡片")
    for remain in range(wait_sec, 0, -1):
        r.check()
        r.tick(remain)
        time.sleep(1)
    r.shot(label)

    r.step(f"确认{label}是否出现")
    if not r.confirm():
        r.shot("桌面 未出现卡片")
        r.log("桌面没有看到卡片，本次结束（可点重试重新触发）")
        return False
    r.ok(f"已确认{label}")
    return True


def run(dev: Device | None = None, emit=None, *, method: str = "mock_country",
        wait_min: int = 20, wait_sec: int = 10, settle_sec: int = 15,
        control: dict | None = None, confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    method = (method or "").strip() or "mock_country"
    if method not in METHODS:
        raise UiError(f"未知触发方式 {method!r}，可选：{', '.join(METHODS)}")
    if not (1 <= int(wait_min) <= 60):
        raise UiError("wait_min 必须在 1~60 分钟之间")
    if not (5 <= int(wait_sec) <= 120):
        raise UiError("wait_sec 必须在 5~120 秒之间")

    label = METHODS[method]
    result = {"method": method, "label": label, "wait_min": int(wait_min),
              "wait_sec": int(wait_sec)}

    if method == "location":
        ok = _run_location(dev, r, wait_min, wait_sec)
        result["summary_ok"] = (
            f"完成。定位先到上海亮屏 {wait_min} 分钟，再切到新德里亮屏 "
            f"{wait_min} 分钟，上滑回桌面后应出现跨国 / 跨城卡片。")
    else:
        ok = _run_mock(dev, r, method, wait_sec)
        result["city_code"] = CITY_CARDS[method][1]
        result["json_data"] = location_event_json(CITY_CARDS[method][1])
        result["summary_ok"] = (
            f"完成。已下发 LocationEvent"
            f"（country_code=IN，city_code={CITY_CARDS[method][1] or '留空'}），"
            f"桌面应出现{label}。")

    dev.stayon(False)
    result["device_time_after"] = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    result["steps"] = r._no
    result["ok"] = ok
    result["triggered"] = ok
    result["summary"] = result.pop("summary_ok") if ok else (
        f"未触发。{label} 流程已跑完，桌面没有看到卡片。")
    return result


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="跨国 / 跨城卡片")
    ap.add_argument("--method", default="mock_country", choices=list(METHODS))
    ap.add_argument("--wait-min", type=int, default=20)
    ap.add_argument("--wait-sec", type=int, default=10)
    args = ap.parse_args()
    try:
        out = run(emit=_cli_emit, method=args.method,
                  wait_min=args.wait_min, wait_sec=args.wait_sec)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

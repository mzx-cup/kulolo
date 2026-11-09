"""串行跑 8 个「节日祝福卡片」场景，把每张真机卡片自动采集到卡片库。

用法
----
    python tools/collect_festivals.py                 # 跑全部 8 张
    python tools/collect_festivals.py shengdan duanwu # 只跑指定节日后缀
    python tools/collect_festivals.py --status        # 只看采集进度，不跑

与重要日卡片采集的区别
----------------------
1. **自动应答 OOBE 询问**：中国节日（新年/端午/中秋/国庆/冬至/春节）在
   `scenario_festival.run()` 里会 `r.ask("是否已在 OOBE 里把国家调整到中国？")`。
   无人点网页时 `_ask_fn` 会阻塞 120 秒才默认放行 —— 8 个节日就白等 12 分钟。
   所以轮询时一看到 `ask` 事件就自动 `POST /api/scenario/ask {"ok": true}`。
   前提：设备 OOBE 国家确实已经是中国（这台机器实测是），否则卡片不会出。

2. 节日场景的 `hidden.festival` 已经把「跑哪个节日」写死在场景定义里，
   请求体只需要 hour / minute / wait_sec，不需要额外传 festival。

服务必须已经在跑（`python main.py`），脚本只走 HTTP，和网页点「一键运行」
是同一条链路。串行而非并行：设备只有一台，并行会互相改系统时间。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8765"

# (场景 id, 中文名)。顺序与前端目录一致：新年 → 端午 → 中秋 → 国庆 →
# 冬至 → 圣诞夜 → 圣诞节 → 春节。
TARGETS = [
    ("festival_xinnian",    "新年"),
    ("festival_duanwu",     "端午节"),
    ("festival_zhongqiu",   "中秋节"),
    ("festival_guoqing",    "国庆节"),
    ("festival_dongzhi",    "冬至"),
    ("festival_shengdanye", "圣诞夜"),
    ("festival_shengdan",   "圣诞节"),
    ("festival_chunjie",    "春节"),
]

PARAMS = {"hour": 9, "minute": 30, "wait_sec": 60}
# 单个场景最长等多久：改时间 + 常亮 60s + 锁屏亮屏 8s +
# 自动识别最长 8 分钟（节日卡片专用预算）+ 余量。
RUN_TIMEOUT = 10 * 60
POLL_GAP = 3


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.load(r)


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def cards() -> dict:
    try:
        return _get("/api/cards").get("cards", {})
    except Exception:
        return {}


def run_one(sid: str, name: str) -> dict:
    """跑一个节日场景，返回 {ok, card, text, elapsed}。"""
    before = cards().get(sid, {}).get("ts", 0)
    try:
        resp = _post(f"/api/scenario/{sid}", PARAMS)
    except Exception as exc:
        return {"ok": False, "reason": f"启动失败：{exc}"}
    if resp.get("error"):
        return {"ok": False, "reason": resp["error"]}

    t0 = time.time()
    answered_ask = False
    while time.time() - t0 < RUN_TIMEOUT:
        time.sleep(POLL_GAP)
        # 中国节日会先弹 OOBE 国家询问；自动应答「是」，别白等 120 秒
        try:
            ev = _get("/api/events?after=0")
            for e in ev.get("events", []):
                if e.get("t") == "ask" and not answered_ask:
                    _post("/api/scenario/ask", {"ok": True})
                    answered_ask = True
                    print("[自动应答 OOBE 询问：是]", end=" ", flush=True)
        except Exception:
            pass
        try:
            status = _get("/api/status")
        except Exception:
            continue
        if not status.get("run", {}).get("running"):
            entry = cards().get(sid)
            if entry and entry.get("ts", 0) > before:
                return {"ok": True, "card": entry,
                        "text": entry.get("text", ""),
                        "elapsed": round(time.time() - t0)}
            return {"ok": False, "reason": "场景跑完了但没采到卡片图",
                    "elapsed": round(time.time() - t0)}
    return {"ok": False, "reason": f"超过 {RUN_TIMEOUT}s 仍未结束"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*",
                    help="只跑这些节日后缀（如 shengdan duanwu）；留空跑全部 8 张")
    ap.add_argument("--status", action="store_true", help="只看卡片库现状")
    args = ap.parse_args()

    if args.status:
        for sid, name in TARGETS:
            info = cards().get(sid)
            if info:
                print(f"  {name:6s} {sid:22s} {info.get('where','?'):5s} "
                      f"{info.get('text','')[:36]}")
            else:
                print(f"  {name:6s} {sid:22s} ---- 未采集")
        return 0

    todo = [(s, n) for s, n in TARGETS
            if not args.ids or any(s.endswith(x) or s == x for x in args.ids)]
    if not todo:
        print("没有匹配的节日。可选后缀：", ", ".join(n for _, n in TARGETS))
        return 1

    print(f"准备串行采集 {len(todo)} 张节日祝福卡片（OOBE 询问自动应答）")
    print("=" * 70)
    ok, fail = [], []
    for i, (sid, name) in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {name} ({sid}) ... ", end="", flush=True)
        # 后端 _confirm_fn 自带「三条 pm clear + 最长 8 分钟」重试循环，
        # 脚本层不再重复重试，否则单张卡会被拖到 18 分钟。
        res = run_one(sid, name)
        if res["ok"]:
            ok.append(name)
            print(f"OK  {res['text'][:30]}  ({res['elapsed']}s)")
        else:
            fail.append((name, res.get("reason", "?")))
            print(f"FAIL  {res.get('reason','?')}")
    print("=" * 70)
    print(f"成功 {len(ok)}：{'、'.join(ok) if ok else '（无）'}")
    if fail:
        print(f"失败 {len(fail)}：")
        for name, why in fail:
            print(f"  - {name}: {why}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())

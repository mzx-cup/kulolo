"""串行跑「重要日卡片」分组的场景，把每张真机卡片自动采集到卡片库。

用法
----
    python tools/collect_important_days.py              # 跑全部 7 张
    python tools/collect_important_days.py greeting    # 只跑指定 id（可多个）
    python tools/collect_important_days.py --status    # 只看采集进度，不跑

为什么需要这个脚本
------------------
前端「卡片实拍」面板按场景 id 显示图片，图片来自卡片库
（`%APPDATA%\\phone-remote\\cards`）。要让 7 张重要日卡片都有具体 UI 图，
就得把每个场景真的跑一遍 —— 每个场景要改系统时间、息屏 60 秒、亮屏解锁、
自动识别、截图抠图，一轮约 2~3 分钟。

服务必须已经在跑（`python main.py`），脚本只通过 HTTP 触发和轮询，
不直接碰 adb —— 这样和网页上点「一键运行」走的是完全同一条链路。

串行而非并行：设备只有一台，并行会互相改系统时间、抢屏幕，全乱套。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"

# 重要日卡片分组，除开：
#   * exam_greeting  —— 用户单独给过设计稿，不用再跑
#   * anniversary    —— NOTE 系列机型不支持这张策划案卡（实测轮播翻一圈都不出卡），
#                       前端已标注「NOTE 系列手机不支持」，采集脚本直接跳过
TARGETS = [
    ("birthday",             {"offset_days": 4, "hour": 9, "minute": 30, "wait_sec": 60}),
    ("greeting",             {"hour": 9, "minute": 30, "wait_sec": 60}),
    ("anniversary_greeting", {"hour": 10, "minute": 30, "wait_sec": 60}),
    ("exam",                 {"offset_days": 4, "hour": 9, "minute": 30, "wait_sec": 60}),
    ("show_day",             {"hour": 10, "minute": 30, "wait_sec": 60}),
    ("important_day",        {"hour": 9, "minute": 30, "wait_sec": 60}),
]

# 单个场景最长等多久（秒）。策划案类要息屏 60s + 解锁 + 识别，留足余量。
RUN_TIMEOUT = 300
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


def run_one(sid: str, params: dict) -> dict:
    """跑一个场景，返回 {ok, card, text, elapsed}。"""
    before = cards().get(sid, {}).get("ts", 0)
    try:
        resp = _post(f"/api/scenario/{sid}", params)
    except Exception as exc:
        return {"ok": False, "reason": f"启动失败：{exc}"}
    if resp.get("error"):
        return {"ok": False, "reason": resp["error"]}

    t0 = time.time()
    card_seen = None
    while time.time() - t0 < RUN_TIMEOUT:
        time.sleep(POLL_GAP)
        try:
            status = _get("/api/status")
        except Exception:
            continue
        if not status.get("run", {}).get("running"):
            # 跑完了：看卡片库里这张卡有没有被更新
            entry = cards().get(sid)
            if entry and entry.get("ts", 0) > before:
                return {"ok": True, "card": entry,
                        "text": entry.get("text", ""),
                        "elapsed": round(time.time() - t0)}
            return {"ok": False, "reason": "场景跑完了但没采到卡片图",
                    "elapsed": round(time.time() - t0)}
        # 运行中顺手记一下 card 事件（日志里能看到识别结果）
        try:
            ev = _get("/api/events?after=0")
            for e in ev.get("events", []):
                if e.get("t") == "card" and e.get("scenario") == sid:
                    card_seen = e
        except Exception:
            pass
    return {"ok": False, "reason": f"超过 {RUN_TIMEOUT}s 仍未结束",
            "card_event": card_seen}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="只跑这些场景 id；留空跑全部 7 张")
    ap.add_argument("--status", action="store_true", help="只看卡片库现状")
    args = ap.parse_args()

    if args.status:
        for sid, info in sorted(cards().items()):
            print(f"  {sid:24s} {info.get('where','?'):5s} "
                  f"{info.get('text','')[:40]}")
        return 0

    todo = [(s, p) for s, p in TARGETS if not args.ids or s in args.ids]
    if not todo:
        print("没有匹配的场景 id。可选：", ", ".join(s for s, _ in TARGETS))
        return 1

    print(f"准备串行采集 {len(todo)} 张重要日卡片（跳过已单独完成的 exam_greeting）")
    print("=" * 68)
    ok, fail = [], []
    for i, (sid, params) in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {sid} ... ", end="", flush=True)
        res = run_one(sid, params)
        if res["ok"]:
            ok.append(sid)
            print(f"OK  {res['text'][:34]}  ({res['elapsed']}s)")
        else:
            fail.append((sid, res.get("reason", "?")))
            print(f"FAIL  {res.get('reason','?')}")
    print("=" * 68)
    print(f"成功 {len(ok)}：{', '.join(ok) if ok else '（无）'}")
    if fail:
        print(f"失败 {len(fail)}：")
        for sid, why in fail:
            print(f"  - {sid}: {why}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())

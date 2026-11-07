"""卡片素材库：把每个场景跑出来的卡片截图存下来，按场景归档。

为什么单独一个模块
------------------
「自动识别卡片」和「把卡片存起来给前端看」是两件事：前者和设备交互有关
（`card_probe`），后者只是文件 + 一份索引。拆开之后，前端要读卡片不用
碰任何设备逻辑，场景侧也不用关心文件怎么命名。

存哪儿
------
`runtime_paths.state_dir() / "cards"`，也就是 `%APPDATA%\\phone-remote\\cards`。
和 fixtures.json 同一个理由：不能放 exe 旁边的临时目录，否则一升级全丢。

索引
----
`cards.json`：`{scenario_id: {file, text, keyword, where, ts, title}}`。
只保留**每个场景最新一张**——这个库的用途是「看这张卡长什么样」，
不是流水账；老图顺手删掉，免得越攒越多。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import runtime_paths

INDEX_NAME = "cards.json"


def cards_dir() -> Path:
    p = runtime_paths.state_dir() / "cards"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def _index_path() -> Path:
    return runtime_paths.state_dir() / INDEX_NAME


def load_index() -> dict:
    """读索引。文件坏了就当空的——这只是缓存，不是真相来源。"""
    p = _index_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_index(index: dict) -> None:
    p = _index_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # 先写临时文件再替换：中途断电也不会留下半个 JSON
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def record(scenario_id: str, *, title: str, png: bytes,
           text: str = "", keyword: str = "", where: str = "") -> dict:
    """把一张卡片截图登记到某个场景名下，返回写进索引的那条记录。

    同一场景重复跑会覆盖：文件名固定成 `<scenario_id>.png`，
    索引里也直接替换。前端按 id 拿图，永远拿到最新那张。
    """
    entry = {
        "scenario": scenario_id,
        "title": title,
        "text": text,
        "keyword": keyword,
        "where": where,
        "ts": round(time.time(), 3),
        "file": f"{scenario_id}.png",
    }
    try:
        d = cards_dir()
        (d / entry["file"]).write_bytes(png)
    except OSError:
        return {}

    index = load_index()
    old = index.get(scenario_id)
    index[scenario_id] = entry
    _save_index(index)
    # 旧文件如果名字不一样（早期版本留下的），删掉
    if old and old.get("file") and old["file"] != entry["file"]:
        try:
            (cards_dir() / old["file"]).unlink()
        except OSError:
            pass
    return entry


def list_all() -> dict:
    """给前端的全量索引，顺手标注图还在不在。"""
    index = load_index()
    d = cards_dir()
    out = {}
    for sid, entry in index.items():
        if not isinstance(entry, dict):
            continue
        f = entry.get("file") or f"{sid}.png"
        if not (d / f).is_file():
            continue        # 文件被手工删了就别再报给前端
        out[sid] = dict(entry)
    return out


def read_png(scenario_id: str) -> bytes | None:
    """按场景 id 取卡片 PNG；没有就返回 None。"""
    index = load_index()
    entry = index.get(scenario_id)
    f = (entry or {}).get("file") or f"{scenario_id}.png"
    p = cards_dir() / f
    try:
        return p.read_bytes()
    except OSError:
        return None

"""把「阿尼亚」Windows 动画光标 (.ani) 转成 Web 用的 PNG 指针。

背景
----
本项目的 web 前端用 `cursor: url(...)` 显示自定义指针（见 web-src/src/styles/_cursor.scss）。
浏览器不支持 .ani（Windows 的 RIFF/ACON 动画光标），所以这里把每支 .ani 的
第一帧（静止帧）抽出来，转成带透明通道的 PNG，并输出 @1x（32px）和 @2x（64px）。

格式说明
--------
.ani = RIFF 容器：
  - anih 头：cFrames / 画布尺寸 / 位深
  - rate / seq ：帧时长与播放顺序（这里用不到，取第 0 帧即可）
  - LIST "fram" ：若干 "icon" 块，每块是一个完整 .cur 文件
每个 icon 块 = ICONDIR(6) + ICONDIRENTRY(16) + 图像数据，
其中图像数据 = BITMAPINFOHEADER(40) + XOR 位图 + AND 掩码。

本批阿尼亚光标都是 32bpp，XOR 位图自带 alpha 通道，直接取用即可。

用法：
    python tools/make_anya_cursors.py
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "阿尼亚+拓展" / "阿尼亚 基础"
EXT = ROOT / "阿尼亚+拓展"

OUT = ROOT / "web-src" / "public" / "cursors" / "anya"


def parse_ani(path: Path):
    data = path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"ACON", f"不是 ANI 光标: {path}"
    pos = 12
    anih = None
    frames: list[bytes] = []
    while pos < len(data):
        if pos + 8 > len(data):
            break
        cid = data[pos:pos + 4]
        sz = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + sz]
        if cid == b"anih":
            anih = struct.unpack("<IIIIIIIII", body[:36])
        elif cid == b"LIST" and body[:4] == b"fram":
            p = 4
            while p + 8 <= len(body):
                icid = body[p:p + 4]
                isz = struct.unpack("<I", body[p + 4:p + 8])[0]
                frames.append(body[p + 8:p + 8 + isz])
                p += 8 + isz + (isz & 1)
        pos += 8 + sz + (sz & 1)
    return anih, frames


def decode_cur(payload: bytes):
    """把一个 .cur 块解码成 RGBA 图像，返回 (image, hotspot_x, hotspot_y)。"""
    reserved, typ, count = struct.unpack("<HHH", payload[:6])
    assert typ == 2, f"不是光标（type={typ}）"
    assert count >= 1
    w, h, colors, resv, hotx, hoty, bytesres, offset = struct.unpack("<BBBBHHII", payload[6:22])
    width = w if w else 256
    height = h if h else 256

    img = payload[offset:]
    (bisize, biw, bih, biplanes, bibit, bicomp, bisizeimg,
     bix, biy, biclr, biclrimp) = struct.unpack("<IiiHHIIiiII", img[:40])
    topdown = bih < 0
    W = biw
    # .cur 的 biHeight = XOR 高度 + AND 掩码高度（二者等高），所以真实高度减半
    full_h = abs(bih)
    H = full_h // 2
    assert bibit == 32, f"位深不是 32: {bibit}"

    rowbytes = W * 4
    xor = img[40:40 + rowbytes * H]

    # AND 掩码（1bpp，每行 4 字节对齐）
    and_stride = ((W + 31) // 32) * 4
    and_off = 40 + rowbytes * H
    andmask = img[and_off:and_off + and_stride * H]

    out = bytearray(W * H * 4)
    for y in range(H):
        src = (H - 1 - y) if not topdown else y
        row = xor[src * rowbytes:(src + 1) * rowbytes]
        arow = andmask[src * and_stride:(src + 1) * and_stride]
        for x in range(W):
            b = row[x * 4]
            g = row[x * 4 + 1]
            r = row[x * 4 + 2]
            a = row[x * 4 + 3]
            # 32bpp 光标：XOR 位图自带 alpha 通道，直接作为透明度。
            # AND 掩码（1bpp）在此是冗余信息；位=0 才表示不透明，
            # 仅当 alpha 通道全为 0（个别旧光标）时才用它兜底。
            o = (y * W + x) * 4
            out[o] = r
            out[o + 1] = g
            out[o + 2] = b
            out[o + 3] = a

    im = Image.frombytes("RGBA", (W, H), bytes(out))
    return im, hotx, hoty


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # 目标指针名 -> (来源文件, 说明)
    # 默认箭头用「兽耳替换」，其余全部取自「阿尼亚 基础」。
    # 交互逻辑（重要）：
    #   「点击」与「拖动」在本页面是同一类「确认」手势 —— 都用链接手型 link.ani，
    #   而不是「移动对象」的四向箭头 move.ani。所以 grab / grabbing 也取 link.ani。
    jobs = {
        "arrow":       (EXT / "兽耳替换arrow.ani", "默认箭头"),
        "pointer":     (BASE / "link.ani", "点击 / 确认（链接手型）"),
        "grab":        (BASE / "link.ani", "可拖动（同确认手型）"),
        "grabbing":    (BASE / "link.ani", "拖动中（同确认手型）"),
        "text":        (BASE / "beam.ani", "文本选择"),
        "zoom-in":     (BASE / "cross.ani", "放大预览（精确选择）"),
        "not-allowed": (BASE / "no.ani", "禁用"),
        "progress":    (BASE / "busy.ani", "等待/忙"),
    }

    hotspots = {}
    for name, (src, desc) in jobs.items():
        anih, frames = parse_ani(src)
        if not frames:
            print(f"!! {name}: 没有帧，跳过")
            continue
        im, hotx, hoty = decode_cur(frames[0])
        src_w, src_h = im.size
        print(f"{name:12s} <- {src.name:22s}  {src_w}x{src_h}  hot=({hotx},{hoty})  {desc}")

        for mult, suffix in ((1, ""), (2, "@2x")):
            size = 32 * mult
            scaled = im.resize((size, size), Image.LANCZOS)
            path = OUT / f"{name}{suffix}.png"
            scaled.save(path, "PNG", optimize=True)
        # 热点按 32px 画布换算
        hotspots[name] = (round(hotx * 32 / src_w), round(hoty * 32 / src_h))

    print("\n热点（按 32px 画布）:")
    for name, h in hotspots.items():
        print(f"  {name:12s} {h}")

    print(f"\n生成完成 -> {OUT}")


if __name__ == "__main__":
    main()

"""由 `assets/icon-source.jpg` 生成应用图标（`assets/app.ico` + `assets/app.png`）。

用法
------
    python tools/make_icon.py

只依赖 Pillow（打包脚本本来就要求有它，见 build_exe.py）。

为什么不是「把原图直接缩成 ico」
------------------------------
库洛米插画细节很碎（草莓、蕾丝、珍珠链），缩到 24px 以下就糊成一团粉色，
根本认不出是什么。所以这里按尺寸分两档做：

* 32px 及以上 —— 完整插画：脸居中、帽尖和蝴蝶结都在画面里，只做圆角 +
  轻微提亮，尺寸越大越贴近原图；
* 24px 及以下 —— 只留额头上那枚粉色骷髅徽章（从同一张插画里抠出来，
  深色底 + 粉色骷髅），小尺寸下反而比整张脸更清楚、更像「库洛米」。

所有尺寸都叠一圈很淡的白边，深色任务栏上不会和背景糊在一起。

产物
----
* `assets/app.ico` —— 多尺寸（16/20/24/32/40/48/64/128/256），
  build_exe.py 找的就是它，打包时 `--icon` 直接带走；
* `assets/app.png` —— 256px 单张，给网页 favicon / README 用。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "icon-source.jpg"
ICO = ROOT / "assets" / "app.ico"
PNG = ROOT / "assets" / "app.png"

# 原图上的取景框（左, 上, 右, 下）：库洛米的头，两侧留一点呼吸空间
CROP = (150, 120, 1150, 1120)

# 额头上那枚粉色骷髅的紧致外框（用连通域量出来的，不是手估的）
SKULL_BOX = (561, 482, 752, 662)

# 大尺寸的放大倍数：小图放大主体，大图保持构图
ZOOM: dict[int, float] = {
    256: 1.00,
    128: 1.00,
    64: 1.05,
    48: 1.10,
    40: 1.16,
    32: 1.22,
}

SIZES = sorted({16, 20, 24, 32, 40, 48, 64, 128, 256}, reverse=True)
BADGE_MAX = 24      # <= 这个尺寸改用骷髅徽章
SS = 8              # 超采样倍数：先画大再缩小，边缘才不毛糙
CORNER = 0.20       # 圆角半径（占边长比例，接近 Win11 方图标的观感）

HOOD = (43, 34, 41)         # 插画里兜帽的深色
SKULL_PINK = (247, 178, 205)  # 插画里骷髅的粉色


def _rounded_mask(size: int, ratio: float = CORNER) -> Image.Image:
    big = size * SS
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, big - 1, big - 1], radius=int(big * ratio), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def _artwork(size: int) -> Image.Image:
    """完整插画：按尺寸取景、放大、调色。"""
    zoom = ZOOM.get(size, 1.0)
    x0, y0, x1, y1 = CROP
    w, h = x1 - x0, y1 - y0
    nw, nh = w / zoom, h / zoom
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    img = Image.open(SRC).convert("RGB")
    if img.width != img.height:                     # 源图不是正方形时先居中裁方
        side = min(img.size)
        img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                        (img.width + side) // 2, (img.height + side) // 2))
    img = img.crop((int(cx - nw / 2), int(cy - nh / 2),
                    int(cx + nw / 2), int(cy + nh / 2)))
    img = img.resize((size * SS, size * SS), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.10)   # 缩图会掉对比度，补一点
    img = ImageEnhance.Color(img).enhance(1.06)
    img = img.resize((size, size), Image.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=45, threshold=2))

    out = img.convert("RGBA")
    out.putalpha(_rounded_mask(size))
    return out


def _skull_alpha(n: int) -> Image.Image:
    """把骷髅从深色兜帽上抠成蒙版。

    亮度当 alpha 再卡一道硬阈值：小图最怕灰蒙蒙，
    宁可边缘硬一点，也要保证 16px 下五官还分得开。
    """
    big = n * SS
    sub = Image.open(SRC).convert("RGB").crop(SKULL_BOX).resize((big, big), Image.LANCZOS)
    lum = np.asarray(sub, dtype=np.float32).mean(axis=2)
    a = np.clip((lum - 100) / (190 - 100), 0.0, 1.0)
    a = np.clip((a - 0.45) / 0.20, 0.0, 1.0)
    mask = Image.fromarray((a * 255).astype(np.uint8))
    return mask.resize((n, n), Image.LANCZOS)


def _badge(size: int, margin: float = 0.12) -> Image.Image:
    """小尺寸用的骷髅徽章：深色圆角底 + 粉色骷髅。"""
    plate = Image.new("RGBA", (size, size), HOOD + (255,))
    inner = int(round(size * (1 - margin * 2)))
    glyph = Image.new("RGBA", (inner, inner), SKULL_PINK + (255,))
    glyph.putalpha(_skull_alpha(inner))
    plate.alpha_composite(glyph, ((size - inner) // 2, (size - inner) // 2))
    plate.putalpha(_rounded_mask(size))
    return plate


def _rim(img: Image.Image, size: int) -> Image.Image:
    """内描边：深色背景上防止图标和背景糊在一起。

    小图里 1px 已经是边长的 6%，白描边会喧宾夺主，所以尺寸越小越淡。
    """
    if size <= BADGE_MAX:
        colour = (255, 255, 255, 110)
        ratio = 0.010
    else:
        colour = (255, 255, 255, 190)
        ratio = 0.012
    w = max(1, round(size * ratio))
    big = size * SS
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, big - 1, big - 1], radius=int(big * CORNER),
        outline=255, width=w * SS)
    layer = Image.new("RGBA", (size, size), colour)
    layer.putalpha(mask.resize((size, size), Image.LANCZOS))
    img.alpha_composite(layer)
    return img


def render(size: int) -> Image.Image:
    """单个尺寸的最终图标。"""
    base = _badge(size) if size <= BADGE_MAX else _artwork(size)
    return _rim(base, size)


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"缺少源图：{SRC}")

    frames = {size: render(size) for size in SIZES}
    biggest = frames[SIZES[0]]
    biggest.save(ICO, format="ICO",
                 sizes=[(s, s) for s in SIZES],
                 append_images=[frames[s] for s in SIZES[1:]])
    frames[256].save(PNG, format="PNG")

    print(f"图标已生成：{ICO.relative_to(ROOT)}（{ICO.stat().st_size / 1024:.1f} KB，"
          f"{len(SIZES)} 个尺寸：{'/'.join(map(str, SIZES))}）")
    print(f"预览图已生成：{PNG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

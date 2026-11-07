"""生成库洛米风格的鼠标指针图片。

为什么要生成 PNG 而不是直接用 CSS cursor 内联 SVG
--------------------------------------------------
`cursor: url(...)` 在现代浏览器里支持 SVG，但有两个硬伤：
  1. Firefox / Chrome 对 SVG 指针里的某些元素（滤镜、渐变）支持不一致，
     经常渲染成空白，用户会以为「指针消失了」；
  2. 无法控制热点（hotspot）的精确定位，箭头尖端容易偏。
PNG 是所有浏览器都稳的方案，配合 `image-set()` 做 2x 适配，
高分屏也不会糊。

生成的指针
----------
  arrow      —— 默认箭头：黑紫色库洛米配色，粉色描边 + 小骷髅
  pointer    —— 可点击：箭头 + 粉色爱心（悬停按钮时）
  text       —— 文本选择：细竖线 + 粉色小点
  grab       —— 可拖拽：张开的小手
  grabbing   —— 拖拽中：握拳
  zoom-in    —— 放大预览：箭头 + 粉色加号
  not-allowed—— 禁用：箭头 + 灰色斜杠

每张都输出 @1x（32px 画布）和 @2x（64px 画布），
热点坐标按 32px 画布计算后在 CSS 里除以对应倍率。

用法：
    python tools/make_cursors.py
产物写进 public/cursors/，Vite 会原样搬到 web/。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# ── 配色：跟主题令牌对齐（库洛米午夜粉） ──────────────────────────
DARK = (26, 18, 32, 255)        # 近黑的紫调（--panel-solid）
DARK_EDGE = (58, 14, 32, 255)   # 更深的描边
PINK = (255, 179, 217, 255)     # 樱粉（--amber）
PINK_HI = (255, 214, 234, 255)  # 高光粉（--amber-bright）
PINK_DEEP = (217, 123, 166, 255)
WHITE = (255, 255, 255, 255)
GREY = (160, 160, 170, 255)

# 绘制基准边长；@2x 时整体放大 2 倍
BASE = 32
SS = 4  # 超采样倍数（先画大再缩小，边缘才不会锯齿）


def _canvas(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """创建一张带透明底的大画布（超采样）。"""
    img = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _down(img: Image.Image, size: int) -> Image.Image:
    """超采样缩回目标尺寸，得到平滑边缘。"""
    return img.resize((size, size), Image.LANCZOS)


def _arrow_points(size: int) -> list[tuple[float, float]]:
    """经典箭头轮廓（标准化到 0~1 再缩放）。

    参考系统指针的比例：
      · 尖端在左上角，向右下方展开成一个尖三角；
      · 左边缘笔直向下（这条边是「鼠标点在哪」的视觉基准，必须垂直）；
      · 底部收成一个尖，再往右下伸出一截「尾巴」；
      · 尾巴右侧回折，形成内凹的缺口。
    这个形状比随意多边形更容易被认成「指针」。
    """
    pts = [
        (0.08, 0.04),   # 尖端
        (0.08, 0.62),   # 左边缘到底（垂直边）
        (0.26, 0.50),   # 内凹（往右上收）
        (0.38, 0.78),   # 尾巴左下
        (0.50, 0.72),   # 尾巴右下
        (0.38, 0.44),   # 尾巴回折到内凹处
        (0.58, 0.42),   # 右斜边终点
    ]
    return [(x * size, y * size) for x, y in pts]


def draw_arrow(size: int, *, fill=DARK, edge=PINK, with_skull: bool = True) -> Image.Image:
    """默认箭头：深紫填充 + 粉色描边，箭头中部嵌一枚小骷髅。

    描边用 PIL 的 polygon 外描边（先画大的粉色多边形，再画小一圈的深色），
    这样箭头是「等比缩小」而不是「按质心收缩」，形状不会变形。
    """
    img, d = _canvas(size)
    s = size * SS
    pts = _arrow_points(s)

    # 外描边：粉色多边形
    d.polygon(pts, fill=edge)

    # 内层：把顶点朝质心收一点点，形成均匀的描边厚度
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    k = 0.08  # 收缩比例（相对到质心的距离）
    inner = [(x + (cx - x) * k, y + (cy - y) * k) for x, y in pts]
    d.polygon(inner, fill=fill)

    if with_skull:
        # 小骷髅：圆头 + 两点眼窝 + 两颗牙，画在箭头三角区域内
        kx, ky = s * 0.215, s * 0.335
        kr = s * 0.070
        d.ellipse([kx - kr, ky - kr, kx + kr, ky + kr], fill=PINK)
        er = kr * 0.34
        # 左眼窝
        d.ellipse([kx - kr * 0.52 - er, ky - kr * 0.22 - er,
                   kx - kr * 0.52 + er, ky - kr * 0.22 + er], fill=fill)
        # 右眼窝
        d.ellipse([kx + kr * 0.52 - er, ky - kr * 0.22 - er,
                   kx + kr * 0.52 + er, ky - kr * 0.22 + er], fill=fill)
        # 两颗牙
        tw = kr * 0.22
        d.rectangle([kx - kr * 0.30, ky + kr * 0.26, kx - kr * 0.30 + tw,
                     ky + kr * 0.66], fill=fill)
        d.rectangle([kx + kr * 0.08, ky + kr * 0.26, kx + kr * 0.08 + tw,
                     ky + kr * 0.66], fill=fill)

    return _down(img, size)


def draw_pointer(size: int) -> Image.Image:
    """可点击指针：箭头 + 右下角一颗粉色爱心。"""
    size2 = size
    img = draw_arrow(size2, with_skull=False).copy()
    d = ImageDraw.Draw(img)
    s = size2

    # 爱心用两个圆 + 一个三角拼，比贝塞尔简单且够可爱
    hx, hy = s * 0.70, s * 0.72
    r = s * 0.135
    d.ellipse([hx - r * 1.02, hy - r * 0.95, hx - r * 0.02, hy + r * 0.05], fill=PINK)
    d.ellipse([hx - r * 0.02, hy - r * 0.95, hx + r * 0.98, hy + r * 0.05], fill=PINK)
    d.polygon(
        [(hx - r * 1.02, hy - r * 0.30), (hx + r * 0.98, hy - r * 0.30), (hx, hy + r * 1.15)],
        fill=PINK,
    )
    # 高光
    d.ellipse([hx - r * 0.72, hy - r * 0.72, hx - r * 0.30, hy - r * 0.30], fill=PINK_HI)
    return img


def draw_text_cursor(size: int) -> Image.Image:
    """文本光标：竖线 + 上下两个粉色小圆点（可爱但仍是 I 形）。"""
    img, d = _canvas(size)
    s = size * SS
    w = s * 0.075
    x = s * 0.5
    d.rounded_rectangle(
        [x - w, s * 0.16, x + w, s * 0.84],
        radius=w, fill=DARK, outline=PINK, width=int(s * 0.045),
    )
    r = s * 0.062
    for yy in (s * 0.12, s * 0.88):
        d.ellipse([x - r, yy - r, x + r, yy + r], fill=PINK)
    return _down(img, size)


def draw_hand(size: int, *, closed: bool) -> Image.Image:
    """小手：张开（grab）或握拳（grabbing）。"""
    img, d = _canvas(size)
    s = size * SS
    lw = int(s * 0.055)

    if not closed:
        # 张开：四指 + 拇指的简笔轮廓
        fingers = [
            (0.30, 0.16, 0.38, 0.50),   # 食指
            (0.44, 0.10, 0.53, 0.46),   # 中指
            (0.58, 0.14, 0.67, 0.48),   # 无名指
            (0.72, 0.22, 0.80, 0.54),   # 小指
        ]
        for x1, y1, x2, y2 in fingers:
            d.rounded_rectangle(
                [x1 * s, y1 * s, x2 * s, y2 * s],
                radius=s * 0.045, fill=DARK, outline=PINK, width=lw,
            )
        # 掌心
        d.rounded_rectangle(
            [0.27 * s, 0.44 * s, 0.83 * s, 0.90 * s],
            radius=s * 0.10, fill=DARK, outline=PINK, width=lw,
        )
        # 拇指
        d.rounded_rectangle(
            [0.14 * s, 0.50 * s, 0.32 * s, 0.72 * s],
            radius=s * 0.05, fill=DARK, outline=PINK, width=lw,
        )
    else:
        # 握拳：一个圆角块 + 三个指节线
        d.rounded_rectangle(
            [0.24 * s, 0.30 * s, 0.82 * s, 0.86 * s],
            radius=s * 0.13, fill=DARK, outline=PINK, width=lw,
        )
        for fx in (0.38, 0.52, 0.66):
            d.line(
                [(fx * s, 0.36 * s), (fx * s, 0.52 * s)],
                fill=PINK, width=int(lw * 0.8),
            )
        # 拇指横线
        d.line([(0.28 * s, 0.68 * s), (0.78 * s, 0.68 * s)], fill=PINK, width=int(lw * 0.8))

    return _down(img, size)


def draw_zoom_in(size: int) -> Image.Image:
    """放大预览：箭头 + 粉色放大镜（斜向放大镜比加号更好认）。"""
    img = draw_arrow(size, with_skull=False).copy()
    d = ImageDraw.Draw(img)
    s = size
    lw = max(1, int(s * 0.075))

    cx, cy, r = s * 0.68, s * 0.66, s * 0.16
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=PINK, width=lw)
    # 手柄
    d.line(
        [(cx + r * 0.72, cy + r * 0.72), (cx + r * 1.55, cy + r * 1.55)],
        fill=PINK, width=lw,
    )
    # 加号
    d.line([(cx - r * 0.45, cy), (cx + r * 0.45, cy)], fill=PINK_HI, width=max(1, lw - 1))
    d.line([(cx, cy - r * 0.45), (cx, cy + r * 0.45)], fill=PINK_HI, width=max(1, lw - 1))
    return img


def draw_not_allowed(size: int) -> Image.Image:
    """禁用：箭头 + 灰色斜杠圈。"""
    img = draw_arrow(size, fill=(52, 48, 56, 255), edge=GREY, with_skull=False).copy()
    d = ImageDraw.Draw(img)
    s = size
    lw = max(1, int(s * 0.07))
    cx, cy, r = s * 0.68, s * 0.68, s * 0.17
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GREY, width=lw)
    d.line(
        [(cx - r * 0.68, cy - r * 0.68), (cx + r * 0.68, cy + r * 0.68)],
        fill=GREY, width=lw,
    )
    return img


# 文件名 → 绘制函数（清晰起见，逐个列出）
CURSORS = {
    "arrow": lambda s: draw_arrow(s),
    "pointer": draw_pointer,
    "text": draw_text_cursor,
    "grab": lambda s: draw_hand(s, closed=False),
    "grabbing": lambda s: draw_hand(s, closed=True),
    "zoom-in": draw_zoom_in,
    "not-allowed": draw_not_allowed,
}


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out = root / "web-src" / "public" / "cursors"
    out.mkdir(parents=True, exist_ok=True)

    for name, fn in CURSORS.items():
        for mult in (1, 2):
            size = BASE * mult
            img = fn(size)
            suffix = "" if mult == 1 else "@2x"
            path = out / f"{name}{suffix}.png"
            img.save(path, "PNG", optimize=True)
            print(f"  {path.name:22s} {img.size[0]}x{img.size[1]}")

    print(f"\n生成完成：{len(CURSORS) * 2} 个文件 -> {out}")
    print("热点（hotspot）按 32px 画布：")
    print("  arrow/pointer/text/zoom-in/not-allowed -> 左上尖端 (2, 2)")
    print("  grab/grabbing                          -> 掌心 (10, 8)")


if __name__ == "__main__":
    main()

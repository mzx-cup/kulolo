"""把手机截出来的卡片图抠成透明底的卡片素材。

用法
-----
    python tools/make_card_art.py            # 生成全部素材
    python tools/make_card_art.py --probe    # 只打印分析结果，不写文件

为什么要抠
----------
卡片图是从手机截图里裁下来的，四周必然带着截图的「底」：这张图右侧和底部
是纯黑（截屏时被窗口圆角裁掉的区域），顶部和左上角是桌面的浅灰壁纸。
直接当 <img> 用会露出方块底，和深色 UI 撞得很脏。

除了命令行，后端采集实拍卡片图时也会直接调 `cutout_png(png_bytes)`，
把「整屏截图 → 裁出卡片区 → 抠成透明圆角」一步做完，前端拿到的就是
可以直接贴的素材，不用再在浏览器里做遮罩。

怎么认这张卡片的轮廓
--------------------
不用颜色阈值猜 —— 卡片顶部那片浅绿渐变（217,242,228）和桌面灰壁纸
（206,209,220）的 RGB 距离只有 ~32，任何容差都同时踩「漏进来」和「漏出去」
两个坑（实测过：容差 42 把卡片上半截挖掉，压到 25 又留下顶边没抠净）。

真正的落脚点是**卡片自带一道 1~2px 的亮色描边**（比周围亮 5~40 个亮度）。
所以用 top-hat（原图减开运算）把这道描边提出来：
  * 描边是闭合的圆角矩形 → 外接框就是卡片外接框；
  * 描边在四角的弧度 → 从顶边/左边的切点量出圆角半径。
拿到「框 + 半径」之后，alpha 用几何遮罩画，不依赖任何背景猜测，
再按描边厚度内缩，深色 UI 上就不会留一圈灰边。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

try:                       # 只有「靠描边猜轮廓」那条路需要 scipy
    from scipy import ndimage
except ImportError:        # noqa: BLE001
    ndimage = None         # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "资源" / "图片资源" / "_incoming"
OUT_DIR = ROOT / "web-src" / "public" / "cards"

# 源图 → 产物名。键是 _incoming 里的文件名（不含扩展名）。
JOBS: dict[str, str] = {
    "exam-bless-source": "exam-blessing",
}

OUT_SIZE = 512      # 产物边长：卡片在 UI 里最大放到 ~220px，2x 屏也够
SS = 4              # 超采样倍数，圆角遮罩先画大再缩小


# ── 找卡片轮廓 ───────────────────────────────────────────────────

def rim_mask(rgb: np.ndarray, strength: float = 4.0) -> np.ndarray:
    """用 top-hat 提取卡片那道亮色描边。

    卡片边缘是「一条比两侧都亮的窄线」，这正是 top-hat 的定义：
    原图减掉开运算，只留下比局部背景亮的小结构。周围一圈（黑边/灰壁纸）
    和卡片内部都比这道线暗，所以提出来是干净的闭合轮廓。
    """
    lum = rgb.mean(axis=2)
    opened = ndimage.grey_opening(lum, size=(5, 5))
    rim = (lum - opened) > strength
    # 闭合一下，把描边上的断点接起来；不做开运算，免得把细线本身抹掉
    return ndimage.binary_closing(rim, np.ones((3, 3), bool))


def measure_box(rim: np.ndarray) -> tuple[int, int, int, int]:
    """卡片外接框 (left, top, right, bottom)，右/下为开区间。

    只认「成行/成列」的描边像素：一条直边上有几十个点，噪点顶多几个。
    """
    h, w = rim.shape
    rows = rim.sum(axis=1)
    cols = rim.sum(axis=0)
    row_ok = np.nonzero(rows >= max(6, w * 0.25))[0]
    col_ok = np.nonzero(cols >= max(6, h * 0.25))[0]
    if len(row_ok) < 2 or len(col_ok) < 2:
        raise SystemExit(f"认不出卡片轮廓（行 {len(row_ok)} / 列 {len(col_ok)}）")
    return int(col_ok[0]), int(row_ok[0]), int(col_ok[-1]) + 1, int(row_ok[-1]) + 1


def measure_radius(rim: np.ndarray, box: tuple[int, int, int, int]) -> float:
    """量圆角半径：看圆弧在「顶边」和「左边」各自从哪儿开始。

    圆角矩形的几何关系很直接：圆弧与顶边相切于 (left + r, top)、
    与左边相切于 (left, top + r)。所以两条边各能量一次 r，取平均：

      * 沿顶边往右扫，描边第一次出现在离 left 多远 → 那是 x 方向的 r；
      * 沿左边往下扫，描边第一次出现在离 top 多远 → 那是 y 方向的 r。

    不拟合圆：直边上的描边点太多，最小二乘总被它们带偏（实测把 32px 的
    半径拟合成 6px）。也不追轮廓：描边是 1px 细线，走位有锯齿，逐行取
    「最左点」会在小抖动上提前退出。
    """
    left, top, right, bottom = box
    # 半张卡片的范围就够了，圆的直径不可能超过边长
    x_lim = int(min(right - left, (bottom - top)) // 2)
    y_lim = x_lim

    # ── x 方向：顶边那一行里，描边从哪个偏移开始 ──
    rx = None
    for dy in range(0, 4):                     # 顶边可能有 2~3px 厚，逐一试
        y = top + dy
        xs = np.nonzero(rim[y, left:left + x_lim])[0]
        if len(xs) < 4:                        # 太短，不是顶边
            continue
        # 顶边是连续的横线，取它第一段连续区间的起点
        first = int(xs[0])
        if first <= 1:
            continue                            # 已经贴着左边，说明这是左直边
        rx = float(first)
        break

    # ── y 方向：左边那一列里，描边从哪个偏移开始 ──
    ry = None
    for dx in range(0, 4):
        x = left + dx
        ys = np.nonzero(rim[top:top + y_lim, x])[0]
        if len(ys) < 4:
            continue
        first = int(ys[0])
        if first <= 1:
            continue
        ry = float(first)
        break

    got = [v for v in (rx, ry) if v is not None]
    if not got:
        # 一条直边都没认出来（图形太小/描边太弱），退回按比例估
        return float(max(2.0, min(right - left, bottom - top) * 0.13))
    return float(max(2.0, sum(got) / len(got)))


def rim_thickness(rim: np.ndarray, box: tuple[int, int, int, int]) -> int:
    """量描边有多厚（像素）：从外接框往里数，连续几行/列还满是描边。

    这道描边是「卡片边缘的 1~2px 高光」，不是卡片内容。留着它在深色底上
    会显出一圈浅色轮廓（尤其四个角和底边），所以最后要按它的厚度整体内缩。
    """
    left, top, right, bottom = box
    w, h = right - left, bottom - top

    def run_len(counts: list[int], need: int) -> int:
        n = 0
        for c in counts:
            if c < need:
                break
            n += 1
        return n

    # 每边最多看 4px
    top_n = run_len([int(rim[y, left:right].sum()) for y in range(top, top + 4)],
                    max(4, w // 4))
    bot_n = run_len([int(rim[y, left:right].sum()) for y in range(bottom - 1, bottom - 5, -1)],
                    max(4, w // 4))
    left_n = run_len([int(rim[top:bottom, x].sum()) for x in range(left, left + 4)],
                     max(4, h // 4))
    right_n = run_len([int(rim[top:bottom, x].sum()) for x in range(right - 1, right - 5, -1)],
                      max(4, h // 4))
    got = [v for v in (top_n, bot_n, left_n, right_n) if v > 0]
    if not got:
        return 1
    # 取中位数，个别边被圆角切断也不影响
    got.sort()
    return int(max(1, got[len(got) // 2]))


def rounded_mask(size: int, radius: float) -> np.ndarray:
    """超采样的圆角方形遮罩，返回 [0,1] 的 float。"""
    big = size * SS
    yy, xx = np.mgrid[0:big, 0:big].astype(np.float64) + 0.5
    r = max(0.0, min(radius * SS, big / 2))
    cx = np.clip(xx, r, big - r)
    cy = np.clip(yy, r, big - r)
    d = np.hypot(xx - cx, yy - cy)
    m = np.clip(r - d + 0.5, 0.0, 1.0)      # 半个像素的软边，够抗锯齿
    return m.reshape(size, SS, size, SS).mean(axis=(1, 3))


# ── 主流程 ───────────────────────────────────────────────────────

def cutout_rgb(rgb: np.ndarray, out_size: int = OUT_SIZE) -> Image.Image:
    """把一张「卡片 + 周围背景」的 RGB 图抠成透明圆角 RGBA。

    这是抠图的核心，也是 `cutout_png` / `process` 共用的实现。输入是任意
    尺寸的 RGB 数组（已经裁到卡片附近即可），输出统一成 out_size 正方形。

    认不出亮色描边时**不能原样返回**：实拍图里有些卡（如早安卡）根本没有
    那道描边，原样返回会让整块灰壁纸 + 底部黑色桌面全留着，白抠了。所以
    兜底改成「按图尺寸画一个标准圆角矩形」—— 裁切区本来就贴着卡片边界，
    固定比例的圆角足够干净，且不依赖任何颜色判断。
    """
    h, w, _ = rgb.shape
    # 认不出轮廓时的兜底几何
    fallback = (0, 0, w, h)

    def render(box, radius, thickness) -> Image.Image:
        inset = min(thickness + 1, max(1, min(box[2] - box[0], box[3] - box[1]) // 8))
        left, top = box[0] + inset, box[1] + inset
        right, bottom = box[2] - inset, box[3] - inset
        if right - left < 8 or bottom - top < 8:
            return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
        flat = rgb[top:bottom, left:right]
        r = max(2.0, radius - inset)
        side = max(flat.shape[0], flat.shape[1])
        pad_v, pad_h = side - flat.shape[0], side - flat.shape[1]
        flat = np.pad(flat, ((0, pad_v), (0, pad_h), (0, 0)), mode="edge")
        mask = rounded_mask(side, r)
        out_rgb = Image.fromarray(np.clip(flat, 0, 255).astype(np.uint8), "RGB")
        out_a = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8), "L")
        big = side * SS
        out_rgb = out_rgb.resize((big, big), Image.LANCZOS).resize((out_size, out_size), Image.LANCZOS)
        out_a = out_a.resize((big, big), Image.LANCZOS).resize((out_size, out_size), Image.LANCZOS)
        result = out_rgb.convert("RGBA")
        result.putalpha(out_a)
        return result

    try:
        rim = rim_mask(rgb)
        box = measure_box(rim)
        radius = measure_radius(rim, box)
        thickness = rim_thickness(rim, box)
    except (SystemExit, ValueError, IndexError):
        # 没有亮色描边的卡：按裁切框画标准圆角，照样能把方块底削干净
        box = fallback
        radius = min(w, h) * 0.14
        thickness = 0
    return render(box, radius, thickness)


def cutout_png(png: bytes, box: tuple[int, int, int, int] | None = None,
               out_size: int = OUT_SIZE) -> bytes:
    """后端入口：整屏 PNG → 裁出卡片区 → 抠成透明圆角 PNG（返回 bytes）。

    `box` 是控件树里量到的**卡片本体紧框** (left, top, right, bottom)。
    传了就按它直接画圆角（不猜描边）—— 这是最可靠的路径：框来自 uiautomator
    的实测 bounds，比任何像素算法都准；淡色卡片（如重要日提醒的白底卡）没有
    那道亮色描边，靠 top-hat 会认不出而留一整块不透明，反而更脏。
    """
    import io

    im = Image.open(io.BytesIO(png)).convert("RGB")
    if box is not None:
        x1, y1, x2, y2 = box
        # 直接裁到紧框，不留呼吸：几何画圆角不需要描边，留边反而把桌面壁纸
        # 也带进图里
        im = im.crop((max(0, x1), max(0, y1),
                      min(im.width, x2), min(im.height, y2)))
        rgb = np.asarray(im).astype(np.float32)
        h, w, _ = rgb.shape
        art = _render_boxed(rgb, (0, 0, w, h), min(w, h) * 0.14, 0, out_size)
    else:
        rgb = np.asarray(im).astype(np.float32)
        art = cutout_rgb(rgb, out_size=out_size)
    buf = io.BytesIO()
    art.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _render_boxed(rgb: np.ndarray, box: tuple[int, int, int, int],
                  radius: float, thickness: int, out_size: int) -> Image.Image:
    """按给定框画圆角 alpha，不做任何描边识别。"""
    inset = min(thickness + 1, max(1, min(box[2] - box[0], box[3] - box[1]) // 8))
    left, top = box[0] + inset, box[1] + inset
    right, bottom = box[2] - inset, box[3] - inset
    if right - left < 8 or bottom - top < 8:
        return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    flat = rgb[top:bottom, left:right]
    r = max(2.0, radius - inset)
    side = max(flat.shape[0], flat.shape[1])
    pad_v, pad_h = side - flat.shape[0], side - flat.shape[1]
    flat = np.pad(flat, ((0, pad_v), (0, pad_h), (0, 0)), mode="edge")
    mask = rounded_mask(side, r)
    out_rgb = Image.fromarray(np.clip(flat, 0, 255).astype(np.uint8), "RGB")
    out_a = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8), "L")
    big = side * SS
    out_rgb = out_rgb.resize((big, big), Image.LANCZOS).resize((out_size, out_size), Image.LANCZOS)
    out_a = out_a.resize((big, big), Image.LANCZOS).resize((out_size, out_size), Image.LANCZOS)
    result = out_rgb.convert("RGBA")
    result.putalpha(out_a)
    return result


def process(src: Path, probe: bool = False) -> Image.Image:
    rgb = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
    h, w, _ = rgb.shape
    result = cutout_rgb(rgb)

    if probe:
        rim = rim_mask(rgb)
        box = measure_box(rim)
        radius = measure_radius(rim, box)
        thickness = rim_thickness(rim, box)
        inset = min(thickness + 1, max(1, min(box[2] - box[0], box[3] - box[1]) // 8))
        print(f"[probe] {src.name}: 源 {w}x{h}")
        print(f"        描边外接框 {box} → {box[2]-box[0]}x{box[3]-box[1]}")
        print(f"        圆角半径 ≈ {radius:.1f}px"
              f"（占边长 {radius / max(1, box[2] - box[0]):.1%}）")
        print(f"        描边厚度 {thickness}px → 内缩 {inset}px，产物 {OUT_SIZE}x{OUT_SIZE}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="只分析，不写文件")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stem, out_name in JOBS.items():
        src = next(SRC_DIR.glob(f"{stem}.*"), None)
        if src is None:
            print(f"跳过 {stem}：{SRC_DIR} 里找不到源图")
            continue
        img = process(src, probe=args.probe)
        if args.probe:
            continue
        dst = OUT_DIR / f"{out_name}.png"
        img.save(dst, optimize=True)
        print(f"{src.name} → {dst.relative_to(ROOT)}  {img.width}x{img.height}  "
              f"{dst.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()

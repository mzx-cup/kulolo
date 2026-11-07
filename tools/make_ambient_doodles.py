"""生成背景用的「简笔画散落图案」SVG。

设计目标
--------
• 不要规整网格 —— 用户明确嫌「一排一排的蝴蝶结」难看。
  这里用抖动采样（jittered scatter）把图案丢在随机位置，
  再用几个不同尺寸层叠，避免出现任何视觉上的行列感。
• 图案种类要多：太阳 / 云 / 树 / 房子 / 山 / 星星 / 月亮 / 鸟 /
  猫 / 兔 / 鱼 / 花 / 蘑菇 / 叶子 / 波浪 / 雨滴，一眼能认出是简笔画。
• 只用**描边不填充**的线条画（line art），配极低透明度，
  远看是若隐若现的底纹，近看才发现画的是什么 —— 不抢前景内容。
• 输出一张 1200×1200 的 SVG data URI，CSS 里平铺即可。
  随机种子固定，保证每次构建产物一致（不会因为重新构建而变样）。

用法：
    python tools/make_ambient_doodles.py
产物直接写进 src/styles/_ambient-doodles.scss（由 main.scss @use）。
"""

from __future__ import annotations

import math
import random
from pathlib import Path

# 画布边长（px）。平铺时用 background-size 控制实际观感尺寸。
CANVAS = 1200


# ─────────────────────────────────────────────────────────────
#  图案库：每个函数返回一段 SVG 路径串（只用 stroke，不填充）
#  约定：图案都画在 (0,0)~(100,100) 的方框里，便于统一缩放。
# ─────────────────────────────────────────────────────────────

def _sun() -> str:
    """太阳：一个圆 + 八道长短不一的光芒。"""
    p = ["<circle cx='50' cy='50' r='17'/>"]
    for i in range(8):
        a = i * math.pi / 4
        r1, r2 = 24, 34 if i % 2 == 0 else 29
        p.append(
            f"<path d='M{50 + r1 * math.cos(a):.1f} {50 + r1 * math.sin(a):.1f}"
            f"L{50 + r2 * math.cos(a):.1f} {50 + r2 * math.sin(a):.1f}'/>"
        )
    return "".join(p)


def _cloud() -> str:
    """云：三段圆弧连成的云朵轮廓。"""
    return (
        "<path d='M26 62c-8 0-14-6-14-13s6-13 14-13c2-9 10-15 19-15"
        " 10 0 18 7 20 17 8 1 13 7 13 14 0 8-6 14-14 14z'/>"
    )


def _tree() -> str:
    """树：三角树冠 + 树干 + 一条地面线。"""
    return (
        "<path d='M50 14 31 44h38z'/><path d='M50 32 27 66h46z'/>"
        "<path d='M50 66v22'/><path d='M34 88h32'/>"
    )


def _pine() -> str:
    """松树：三层锯齿 + 细干，跟圆冠树区分开。"""
    return (
        "<path d='M50 8 38 28h24z'/><path d='M50 22 33 48h34z'/>"
        "<path d='M50 40 29 68h42z'/><path d='M50 68v20'/>"
    )


def _house() -> str:
    """房子：屋顶 + 墙体 + 门 + 窗。"""
    return (
        "<path d='M16 50 50 20l34 30'/><path d='M23 50v36h54V50'/>"
        "<path d='M41 86V64h18v22'/><rect x='30' y='56' width='9' height='9'/>"
        "<rect x='61' y='56' width='9' height='9'/>"
    )


def _mountain() -> str:
    """山：两座一大一小 + 雪线。"""
    return (
        "<path d='M4 82 34 34l30 48'/><path d='M46 82 74 44l22 38'/>"
        "<path d='M24 52l10 8 10-8'/>"
    )


def _star() -> str:
    """星星：五角星。"""
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = 34 if i % 2 == 0 else 14
        pts.append(f"{50 + r * math.cos(a):.1f} {50 + r * math.sin(a):.1f}")
    return f"<path d='M{'L'.join(pts)}Z'/>"


def _moon() -> str:
    """月牙：两段弧拼出的弯月 + 两颗小星。"""
    return (
        "<path d='M62 18a34 34 0 1 0 20 60 28 28 0 0 1-20-60z'/>"
        "<path d='M76 26l2 6 6 2-6 2-2 6-2-6-6-2 6-2z'/>"
    )


def _bird() -> str:
    """飞鸟：两条对称的翼弧。"""
    return "<path d='M22 54c8-9 16-9 24 0 8-9 16-9 24 0'/><path d='M40 36c5-6 10-6 15 0 5-6 10-6 15 0'/>"


def _cat() -> str:
    """猫：圆脸 + 三角耳 + 胡须。"""
    return (
        "<path d='M28 40 24 20l20 9'/><path d='M72 40 76 20 56 29'/>"
        "<circle cx='50' cy='55' r='24'/>"
        "<path d='M40 50v2M60 50v2'/><path d='M46 64h8'/>"
        "<path d='M26 56H12M26 62H14M74 56h14M74 62h12'/>"
    )


def _rabbit() -> str:
    """兔子：长耳 + 圆头 + 身体。"""
    return (
        "<path d='M40 34c-4-12-2-22 3-22s7 10 5 22'/>"
        "<path d='M60 34c2-12 0-22-3-22'/>"
        "<circle cx='50' cy='46' r='15'/>"
        "<path d='M35 58c-6 10-6 24 15 24s21-14 15-24'/>"
        "<path d='M45 44v2M55 44v2'/>"
    )


def _fish() -> str:
    """鱼：椭圆身 + 尾鳍 + 眼睛。"""
    return (
        "<path d='M24 52c10-14 32-18 44-10 6 4 8 8 8 10s-2 6-8 10c-12 8-34 4-44-10z'/>"
        "<path d='M76 52l14-12v24z'/><circle cx='38' cy='48' r='2'/>"
        "<path d='M48 40c2 6 2 12 0 18'/>"
    )


def _flower() -> str:
    """花：五瓣 + 花心 + 茎叶。"""
    p = ["<circle cx='50' cy='38' r='7'/>"]
    for i in range(5):
        a = -math.pi / 2 + i * 2 * math.pi / 5
        p.append(
            f"<circle cx='{50 + 15 * math.cos(a):.1f}' cy='{38 + 15 * math.sin(a):.1f}' r='7'/>"
        )
    p.append("<path d='M50 52v34'/><path d='M50 70c-8-2-12-6-13-12 7 1 11 5 13 12z'/>")
    return "".join(p)


def _mushroom() -> str:
    """蘑菇：伞盖 + 斑点 + 柄。"""
    return (
        "<path d='M20 50c0-16 13-28 30-28s30 12 30 28z'/>"
        "<path d='M41 50v26h18V50'/><circle cx='38' cy='38' r='3'/>"
        "<circle cx='58' cy='34' r='3.5'/><circle cx='50' cy='44' r='2.5'/>"
    )


def _leaf() -> str:
    """叶子：叶形 + 主脉 + 侧脉。"""
    return (
        "<path d='M22 78C22 46 44 24 78 22c-2 34-24 56-56 56z'/>"
        "<path d='M24 76 74 26'/><path d='M40 60l-2-12M52 48l-2-12M34 70l-12-2'/>"
    )


def _wave() -> str:
    """水波：三条起伏线。"""
    return (
        "<path d='M6 44c8-10 16-10 24 0s16 10 24 0 16-10 24 0'/>"
        "<path d='M6 60c8-10 16-10 24 0s16 10 24 0 16-10 24 0'/>"
        "<path d='M6 76c8-10 16-10 24 0s16 10 24 0 16-10 24 0'/>"
    )


def _raindrop() -> str:
    """雨滴：水滴轮廓。"""
    return "<path d='M50 18c14 20 22 30 22 40a22 22 0 0 1-44 0c0-10 8-20 22-40z'/>"


def _butterfly() -> str:
    """蝴蝶：保留一点点原主题的缎带意象，但画成简笔画。"""
    return (
        "<path d='M50 34c-8-14-22-18-28-10s2 22 16 26c-14 4-22 16-16 24s20 4 28-10'/>"
        "<path d='M50 34c8-14 22-18 28-10s-2 22-16 26c14 4 22 16 16 24s-20 4-28-10'/>"
        "<path d='M50 30v44'/><path d='M48 26 42 16M52 26l6-10'/>"
    )


def _umbrella() -> str:
    """雨伞：伞面 + 伞骨 + 弯柄。"""
    return (
        "<path d='M14 50c4-16 18-26 36-26s32 10 36 26'/>"
        "<path d='M14 50c6-6 12-6 18 0 6-6 12-6 18 0 6-6 12-6 18 0 6-6 12-6 18 0'/>"
        "<path d='M50 50v28a8 8 0 0 0 16 0'/><path d='M50 24v-6'/>"
    )


def _balloon() -> str:
    """气球：椭圆 + 绳 + 结。"""
    return (
        "<ellipse cx='50' cy='40' rx='18' ry='22'/><path d='M50 62l-5 6h10z'/>"
        "<path d='M50 68c6 8-6 14 0 22'/>"
    )


def _mountain_house() -> str:
    """小屋 + 烟囱：跟房子区分，带烟。"""
    return (
        "<path d='M24 52 50 30l26 22'/><path d='M30 52v30h40V52'/>"
        "<path d='M56 30v-10h8v16'/><path d='M66 14c4-4 8 0 6 4'/>"
        "<rect x='42' y='62' width='16' height='20'/>"
    )


DOODLES = [
    ("sun", _sun), ("cloud", _cloud), ("tree", _tree), ("pine", _pine),
    ("house", _house), ("mountain", _mountain), ("star", _star),
    ("moon", _moon), ("bird", _bird), ("cat", _cat), ("rabbit", _rabbit),
    ("fish", _fish), ("flower", _flower), ("mushroom", _mushroom),
    ("leaf", _leaf), ("wave", _wave), ("raindrop", _raindrop),
    ("butterfly", _butterfly), ("umbrella", _umbrella),
    ("balloon", _balloon), ("cottage", _mountain_house),
]


def build_svg(seed: int = 20261107) -> str:
    """把图案随机撒在画布上。

    用「泊松式抖动」：把画布切成 cells×cells 的格子，每个格子随机放
    0~1 个图案，位置在格子内随机偏移（不贴边），尺寸也在一个区间里
    随机取。这样既保证了大致的均匀覆盖（不会出现大片空白），
    又完全避免了对齐感。
    """
    rng = random.Random(seed)
    cells = 5                      # 5×5 = 25 个格子
    cell = CANVAS / cells
    parts: list[str] = []

    for gy in range(cells):
        for gx in range(cells):
            # 每个格子 25% 概率留白，避免太满
            if rng.random() < 0.22:
                continue
            name, fn = DOODLES[rng.randrange(len(DOODLES))]
            # 位置：在格子内随机偏移，留 15% 边距
            jx = cell * (0.18 + rng.random() * 0.64)
            jy = cell * (0.18 + rng.random() * 0.64)
            cx = gx * cell + jx
            cy = gy * cell + jy
            # 尺寸：30~68px 的图案方框，层次感来自大小不一
            size = rng.uniform(30, 68)
            rot = rng.uniform(-18, 18)
            opacity = rng.uniform(0.55, 1.0)

            body = fn()
            parts.append(
                f"<g transform='translate({cx:.1f} {cy:.1f}) rotate({rot:.1f}) "
                f"translate({-size / 2:.1f} {-size / 2:.1f}) scale({size / 100:.3f})' "
                f"opacity='{opacity:.2f}'>{body}</g>"
            )

    inner = "".join(parts)
    # stroke 直接写白色：SVG 作为 background-image 时是独立文档，
    # CSS 的 color 传不进去（currentColor 会退化成初始值黑色，在深色底上
    # 完全看不见）。所以这里写死 #fff，再靠 CSS 的 opacity 压淡。
    # 线宽 3.2：底纹会被缩放到 1100px 平铺，再细就糊成一片看不出画的是什么。
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{CANVAS}' height='{CANVAS}' "
        f"viewBox='0 0 {CANVAS} {CANVAS}'>"
        f"<g fill='none' stroke='white' stroke-width='3.2' "
        f"stroke-linecap='round' stroke-linejoin='round'>{inner}</g></svg>"
    )


def to_data_uri(svg: str) -> str:
    """转成 CSS 能直接用的 data URI（# 要转义，否则会被当成 URL 片段）。"""
    from urllib.parse import quote

    return "data:image/svg+xml," + quote(svg, safe="/:='.,;() -")


def main() -> None:
    svg = build_svg()
    uri = to_data_uri(svg)
    out = Path(__file__).resolve().parent.parent / "web-src" / "src" / "styles" / "_ambient-doodles.scss"
    body = f"""// ⚠ 本文件由 tools/make_ambient_doodles.py 自动生成，请勿手改。
//
// 背景用的「简笔画散落图案」：太阳、云、树、房子、山、星星、月亮、
// 鸟、猫、兔、鱼、花、蘑菇、叶子、水波、雨滴、蝴蝶、雨伞、气球、小屋……
// 位置随机、大小不一、角度略有倾斜，完全打散排布，不会出现行列感。
//
// 这里只导出一个 CSS 变量，具体怎么摆由 _ambient.scss 决定
// （透明度、平铺尺寸、遮罩、漂移都在那边控制）。

$doodle-uri: "{uri}";

:root {{
  --doodle-url: url("#{{$doodle-uri}}");
}}
"""
    out.write_text(body, encoding="utf-8")
    print(f"wrote {out}  ({len(uri)} bytes)")
    print(f"patterns: {len(DOODLES)} kinds, scattered without grid alignment")


if __name__ == "__main__":
    main()

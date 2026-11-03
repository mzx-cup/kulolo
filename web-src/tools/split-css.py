# -*- coding: utf-8 -*-
"""把 web/style.css 按原有的分段注释切成 SCSS partial。

只做「按行切片 + 落盘」，不改任何一条规则的内容，保证视觉与改造前逐像素一致。
顺带把每个 partial 里用到的 @media 留在原处（顺序即层叠顺序）。
"""
from pathlib import Path

SRC = Path(r"D:\代码\phone-remote\web\style.css")
OUT = Path(r"D:\代码\phone-remote\web-src\src\styles")
OUT.mkdir(parents=True, exist_ok=True)

# (起始行号, 结束行号(不含), 文件名, 中文说明)
SECTIONS = [
    (7, 199, "_tokens.scss", "主题令牌：尺寸 / 缓动 / 字体 / 色调 + 深浅两套配色"),
    (199, 283, "_base.scss", "基础：reset、滚动条、跳转链接、无障碍焦点"),
    (283, 329, "_ambient.scss", "环境背景：光晕 + 网格 + 星尘 + 噪点"),
    (329, 476, "_topbar.scss", "顶栏：品牌、设备状态、右侧操作"),
    (476, 564, "_buttons.scss", "按钮：btn / commit / icon-btn / vbtn / filter"),
    (564, 593, "_layout.scss", "主布局 shell + workspace 骨架"),
    (593, 1122, "_catalog.scss", "场景目录：搜索、筛选、最近、分组、卡片"),
    (1122, 1185, "_panel.scss", "面板通用：panel / panel-head / head-note"),
    (1185, 1627, "_hero.scss", "主面板 Hero：标题、规格、进度、参数表单"),
    (1627, 1875, "_workspace.scss", "工作区：步骤序列 + 运行日志"),
    (1875, 2165, "_device.scss", "手机预览：机身、截图、扫描线、live 徽标"),
    (2165, 2390, "_modals.scss", "遮罩与弹层：确认 / 询问 / 重试 / 停止 + 各自响应式"),
    (2390, 2443, "_toast.scss", "Toast 提示条"),
    (2443, 2498, "_resultfx.scss", "右下角结算提示 + 其小屏适配"),
    (2498, 2522, "_ripple.scss", "点击涟漪 + 主题切换过渡"),
    (2522, 2666, "_responsive.scss", "全局响应式断点"),
    (2666, 2681, "_a11y.scss", "无障碍：减少动态效果"),
]

lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
total = len(lines)
print(f"source lines: {total}")

written = []
for start, end, name, desc in SECTIONS:
    body = "".join(lines[start - 1:end - 1])
    header = f"// {desc}\n// 源：web/style.css 第 {start}~{end - 1} 行（原样搬运，未改规则）\n\n"
    (OUT / name).write_text(header + body, encoding="utf-8")
    written.append((name, end - start))
    print(f"  {name:<18} {end - start:>5} lines  {desc}")

# 最后一节可能超出源文件行数
if SECTIONS[-1][1] - 1 > total:
    print(f"WARN: last section ends at {SECTIONS[-1][1] - 1}, source has {total}")

covered = sum(n for _, n in written)
print(f"covered {covered} / {total} lines (header 1-6 intentionally dropped)")

imports = "\n".join(f'@use "{n[:-5]}";' for n, _ in written if n.startswith("_"))
main = f"""// ═══════════════════════════════════════════════════════════════════
//   手机遥控台 · 场景工坊 —— 样式总入口
//   夜航工坊（默认深色）+ 象牙纸感（浅色）双主题
//   设计原则：场景目录可搜索 / 可筛选 / 可折叠，主工作区聚焦「选中 → 运行 → 观察」
//
//   拆分为多个 partial 只为便于维护；@use 的书写顺序 = 最终 CSS 的层叠顺序，
//   调整顺序会改变覆盖关系，改动前请先确认。
// ═══════════════════════════════════════════════════════════════════

{imports}
"""
(OUT / "main.scss").write_text(main, encoding="utf-8")
print(f"\nwrote main.scss with {len(written)} @use imports")

# -*- coding: utf-8 -*-
"""语义级对比 SCSS 编译产物与原 style.css。

Sass 会重新排版（拆行、合并多行值、去属性选择器引号、补零 .2s → 0.2s），
这些都不影响渲染结果。所以先把两边都规范化成「无空白 token 流」再逐条比：

  - 去掉注释
  - 属性选择器里的引号去掉     [data-theme="dark"] → [data-theme=dark]
  - 数字补零                   .2s → 0.2s、0.50 → 0.5
  - 去掉所有空白与行尾分号差异

再按「规则块」为单位比对，报出真正有语义差异的块。
"""
import re
import sys
import difflib
from pathlib import Path

orig = Path(r"D:\代码\phone-remote\web\style.css").read_text(encoding="utf-8")
new = Path(r"D:\代码\phone-remote\web-src\out-check.css").read_text(encoding="utf-8")


def strip_calc(text: str) -> str:
    """去掉 calc(...) 这层包装（连配对的右括号一起），用于把 Sass 的
    「min()/clamp() 内部省略 calc()」这种合法优化抹平。"""
    out, i = [], 0
    while True:
        j = text.find("calc(", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        k = j + len("calc(")
        depth = 1
        while k < len(text) and depth > 0:
            if text[k] == "(":
                depth += 1
            elif text[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append(text[j + len("calc("):k])   # 只要括号里面的内容
        i = k + 1                              # 跳过配对的那个右括号
    return "".join(out)


def normalize(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = text.replace('@charset "UTF-8";', "")
    # min()/max()/clamp() 内部允许直接写算式，Sass 会去掉冗余的 calc()
    text = strip_calc(text)
    # 属性选择器去引号
    text = re.sub(r'(\[[\w-]+)=["\']([^"\']*)["\']\]', r"\1=\2]", text)
    # 数字补零：.5 → 0.5
    text = re.sub(r"(?<![\w.])\.(\d)", r"0.\1", text)
    # 0.50 → 0.5，0.0 → 0
    def trim_num(m: re.Match) -> str:
        v = m.group(0)
        if "." in v:
            v = v.rstrip("0").rstrip(".")
            if v in ("", "-"):
                v = "0"
        return v
    text = re.sub(r"-?\d+\.\d+", trim_num, text)
    # 去掉全部空白
    text = re.sub(r"\s+", "", text)
    return text


def blocks(text: str) -> list[str]:
    """把规范化后的 CSS 按顶层块切开（处理 @media 嵌套）。"""
    out, depth, cur = [], 0, ""
    for ch in text:
        cur += ch
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append(cur)
                cur = ""
    if cur.strip():
        out.append(cur)
    return [b for b in out if b.strip()]


a_norm = normalize(orig)
b_norm = normalize(new)

print(f"original normalized length: {len(a_norm)}")
print(f"compiled normalized length: {len(b_norm)}")

if a_norm == b_norm:
    print("\nIDENTICAL (semantically) - split preserved every rule exactly")
    sys.exit(0)

A, B = blocks(a_norm), blocks(b_norm)
print(f"original blocks: {len(A)}, compiled blocks: {len(B)}")

if A == B:
    print("\nBLOCK-LEVEL IDENTICAL - only whitespace/ordering inside blocks differed")
    sys.exit(0)

diff = list(difflib.unified_diff(A, B, fromfile="style.css", tofile="compiled", lineterm="", n=1))
print(f"\nSEMANTIC DIFFERENCES ({len(diff)} lines):\n")
for line in diff[:80]:
    print(line[:400])
if len(diff) > 80:
    print(f"... and {len(diff) - 80} more")
sys.exit(1)

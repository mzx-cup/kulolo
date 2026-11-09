"""临时调试：在 apk 的 dex 里搜字符串（找规则实现细节）。

用法：
    python tools/dex_grep.py diffDays checkTime --ctx 260
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

APK = Path(r"C:\Users\22821\PycharmProjects\Hachiware\智慧建议\_apk\TransAtomicBrain.apk")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("words", nargs="+")
    ap.add_argument("--ctx", type=int, default=240)
    args = ap.parse_args()

    z = zipfile.ZipFile(APK)
    dexes = [n for n in z.namelist() if n.endswith(".dex")]
    for name in dexes:
        blob = z.read(name)
        print(f"== {name} {len(blob)} bytes")
        for word in args.words:
            needle = word.encode()
            start = 0
            count = 0
            while True:
                i = blob.find(needle, start)
                if i < 0:
                    break
                count += 1
                lo = max(0, i - args.ctx)
                chunk = blob[lo:i + args.ctx]
                text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                print(f"\n-- {word} @{i}")
                print(text)
                start = i + len(needle)
                if count >= 6:
                    break
            if count == 0:
                print(f"   {word}: none")


if __name__ == "__main__":
    main()

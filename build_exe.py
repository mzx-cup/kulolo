"""打包成单文件 exe：`python build_exe.py`。

产物：`dist/手机遥控台.exe`（单文件，双击即用，目标机不需要装 Python）。

打进去的东西
--------------------------------------------------
* 全部 .py 源码
* `web/`（前端构建产物，必须先跑 `cd web-src && npm run build`）
* `adb/adb.exe` + `AdbWinApi.dll` + `AdbWinUsbApi.dll`
  —— 从本机已装的 adb 复制过来（默认 `C:\\Program Files\\ADB`，
     可用 `ADB_SRC` 环境变量覆盖）。目标机不用再装 adb。
* `scrcpy/`（可选）—— 本机找到 scrcpy 就一起塞进去，找不到就不塞，
  网页上对应按钮会自动置灰。

不打的：`fixtures.json`、`boomplay_music_state.json` 这类状态文件。
它们现在全部落在 `%APPDATA%\\phone-remote`（见 runtime_paths.py），
升级 exe 不会丢设备记录。

图标
--------------------------------------------------
有 `assets/app.ico` 就用它，没有就用 PyInstaller 默认图标。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
STAGE = BUILD / "stage"          # 收集好要打进去的外部资源
APP_NAME = "手机遥控台"

ADB_SRC_DEFAULT = r"C:\Program Files\ADB"
ADB_FILES = ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")


def say(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[build] 失败：{msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def check_web() -> None:
    """前端产物必须存在，否则打出来的 exe 打开是白屏。"""
    index = ROOT / "web" / "index.html"
    assets = ROOT / "web" / "assets"
    if not index.is_file():
        fail("web/index.html 不存在。先在 web-src 里跑 npm run build。")
    js = list(assets.glob("index-*.js")) if assets.is_dir() else []
    css = list(assets.glob("style-*.css")) if assets.is_dir() else []
    if not js or not css:
        fail("web/assets 里没有构建产物。先在 web-src 里跑 npm run build。")
    say(f"前端产物 OK：{index.name} + {js[0].name} ({js[0].stat().st_size} B) "
        f"+ {css[0].name} ({css[0].stat().st_size} B)")


def stage_adb() -> None:
    src_dir = Path(os.environ.get("ADB_SRC", ADB_SRC_DEFAULT))
    have = {p.name.lower(): p for p in src_dir.glob("*")} if src_dir.is_dir() else {}
    missing = [n for n in ADB_FILES if n.lower() not in have]
    if missing:
        # 退一步：PATH 里的 adb 是哪来的就从哪儿拷 dll
        which = shutil.which("adb")
        if which:
            src_dir = Path(which).parent
            have = {p.name.lower(): p for p in src_dir.glob("*")}
            missing = [n for n in ADB_FILES if n.lower() not in have]
        if missing:
            fail(f"找不到 adb 文件 {missing}（在 {src_dir}）。"
                 f"用 ADB_SRC 环境变量指定 adb 所在目录。")

    out = STAGE / "adb"
    out.mkdir(parents=True, exist_ok=True)
    for name in ADB_FILES:
        shutil.copy2(have[name.lower()], out / name)
    total = sum((out / n).stat().st_size for n in ADB_FILES)
    say(f"adb 已收集：{src_dir} -> {out} ({total / 1e6:.1f} MB)")


def stage_scrcpy() -> bool:
    """本机有 scrcpy 就一起打包；没有就跳过（不是必需功能）。"""
    cand_dirs = [
        Path(r"D:\APPS\scrcpy-win64-v3.3.3"),
        Path(r"D:\tools\scrcpy"),
        Path(r"C:\tools\scrcpy"),
        Path(r"D:\scrcpy"),
        Path(r"C:\scrcpy"),
    ]
    env = os.environ.get("SCRCPY_SRC")
    if env:
        cand_dirs.insert(0, Path(env))

    src: Path | None = None
    for d in cand_dirs:
        if (d / "scrcpy.exe").is_file():
            src = d
            break
    if src is None:
        which = shutil.which("scrcpy")
        if which:
            src = Path(which).parent

    if src is None:
        say("未找到 scrcpy，跳过（网页上的 scrcpy 按钮会置灰）")
        return False

    out = STAGE / "scrcpy"
    if out.exists():
        shutil.rmtree(out)
    # 只带运行必需的那几个，别把文档/示例一起塞进去
    keep = {"scrcpy.exe", "scrcpy-server", "SDL2.dll", "libusb-1.0.dll",
            "avcodec-61.dll", "avformat-61.dll", "avutil-59.dll",
            "swresample-5.dll", "icon.png"}
    out.mkdir(parents=True, exist_ok=True)
    copied = 0
    for p in src.iterdir():
        if p.is_file() and (p.name in keep or p.suffix.lower() == ".dll"):
            shutil.copy2(p, out / p.name)
            copied += 1
    if not (out / "scrcpy-server").is_file():
        # scrcpy-server 缺失的话别的都白搭，干脆不打
        say("scrcpy 目录里没有 scrcpy-server，跳过 scrcpy")
        shutil.rmtree(out, ignore_errors=True)
        return False
    size = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    say(f"scrcpy 已收集：{src} -> {out} ({copied} 个文件, {size / 1e6:.1f} MB)")
    return True


def find_icon() -> Path | None:
    for name in ("assets/app.ico", "app.ico"):
        p = ROOT / name
        if p.is_file():
            return p
    return None


def run_pyinstaller(with_scrcpy: bool) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)

    sep = ";" if os.name == "nt" else ":"
    cmd: list[str] = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--console",
        "--name", APP_NAME,
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        # web/ 与 adb/ 是只读资源，由 runtime_paths.resource_path() 找
        "--add-data", f"{ROOT / 'web'}{sep}web",
        "--add-data", f"{STAGE / 'adb'}{sep}adb",
    ]
    if with_scrcpy:
        cmd += ["--add-data", f"{STAGE / 'scrcpy'}{sep}scrcpy"]
    icon = find_icon()
    if icon:
        cmd += ["--icon", str(icon)]
        say(f"图标：{icon}")
    else:
        say("没有 assets/app.ico，用默认图标")

    # 隐式导入：adbutils 有些子模块是运行时才 import 的。
    # 注意 `retry2` 这个包（0.9.5）装下来的**模块名是 `retry`**，不是 retry2
    # —— 写 `--hidden-import retry2` 会报 not found（不致命，但会少打模块，
    # 而 adbutils.shell / screenrecord 里 `from retry import retry` 就要用到它）。
    for hidden in ("adbutils", "PIL.Image", "retry", "deprecation"):
        cmd += ["--hidden-import", hidden]

    cmd.append(str(ROOT / "main.py"))
    say("开始打包（首次约 1~3 分钟）…")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        fail(f"PyInstaller 返回 {r.returncode}")

    exe = DIST / f"{APP_NAME}.exe"
    if not exe.is_file():
        fail(f"没有生成 {exe}")
    return exe


def main() -> None:
    say(f"项目根目录：{ROOT}")
    check_web()
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True, exist_ok=True)
    stage_adb()
    with_scrcpy = stage_scrcpy()

    exe = run_pyinstaller(with_scrcpy)
    size = exe.stat().st_size
    say(f"完成：{exe} ({size / 1e6:.1f} MB)")
    say("双击即可运行；首次启动约 2~5 秒（单文件要解压到临时目录）。")


if __name__ == "__main__":
    main()

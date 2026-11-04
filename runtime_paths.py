"""运行时路径解析：源码直跑 / 打包成 exe 后都能用。

为什么要单独一个模块
--------------------------------------------------
打包成单文件 exe 后，`__file__` 指向的是 PyInstaller 解压出来的
临时目录（`%TEMP%\\_MEIxxxxx`），进程一退出就整个删掉。任何往它旁边
写的状态文件（fixtures.json、boomplay 记账、日志、截图）都会**悄悄丢失**，
而且换台机器、换个用户都读不到。

所以这里把两类路径彻底分开：

* **只读资源**（web/ 前端产物、adb.exe、scrcpy.exe）
  -> `resource_path()`。打包后在 `sys._MEIPASS` 里，源码直跑时就是
     脚本所在目录。

* **可写状态**（fixtures.json、*.json 记账、screenshots/、日志）
  -> `state_dir()`。永远落在 `%APPDATA%\\phone-remote`（可用环境变量
     PHONE_REMOTE_STATE 覆盖），跟 exe 放哪、是不是临时目录无关。
     这样升级 exe、换个目录放 exe，设备记录和记账都还在。

顺带解决 adb 的定位：打包后 PATH 里通常没有 adb，但 adb.exe 就在
资源目录里，于是设置 `ADBUTILS_ADB_PATH` 让 adbutils 直接用内置那份。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "phone-remote"


def is_frozen() -> bool:
    """是否跑在打包后的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def resource_path(*parts: str) -> Path:
    """只读资源目录（或其中的某个路径）。

    打包后：PyInstaller 的 `sys._MEIPASS`（onefile 是临时解压目录）。
    源码直跑：本文件所在目录。
    """
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    return root.joinpath(*parts) if parts else root


def state_dir() -> Path:
    """可写的状态目录，保证存在。

    优先级：环境变量 PHONE_REMOTE_STATE > %APPDATA%\\phone-remote >
    用户主目录下的 .phone-remote。源码直跑时也用同一个目录，
    避免「开发时找不到设备记录、打包后又好了」这类假问题。
    """
    env = os.environ.get("PHONE_REMOTE_STATE")
    if env:
        p = Path(env).expanduser()
    else:
        appdata = os.environ.get("APPDATA")
        if appdata:
            p = Path(appdata) / APP_NAME
        else:
            p = Path.home() / f".{APP_NAME}"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 极端情况下（只读盘、权限异常）退回临时目录，至少别让整个程序崩掉
        import tempfile

        p = Path(tempfile.gettempdir()) / APP_NAME
        p.mkdir(parents=True, exist_ok=True)
    return p


def state_path(name: str) -> Path:
    """状态目录里的某个文件。"""
    return state_dir() / name


def screenshots_dir() -> Path:
    """截图输出目录，保证存在。"""
    p = state_dir() / "screenshots"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def find_adb() -> str | None:
    """定位 adb 可执行文件。

    顺序：环境变量 ADBUTILS_ADB_PATH > PATH > 资源目录里的内置副本。
    找到资源目录里的副本时顺手设好 ADBUTILS_ADB_PATH，这样 adbutils
    和我们自己 `subprocess.run(["adb", ...])` 的调用都能命中同一份。
    """
    env = os.environ.get("ADBUTILS_ADB_PATH")
    if env and Path(env).is_file():
        return env

    found = shutil.which("adb")
    if found:
        os.environ.setdefault("ADBUTILS_ADB_PATH", found)
        return found

    exe = "adb.exe" if os.name == "nt" else "adb"
    for cand in (resource_path("adb", exe), resource_path(exe), resource_path("bin", exe)):
        if cand.is_file():
            os.environ["ADBUTILS_ADB_PATH"] = str(cand)
            return str(cand)
    return None


def bootstrap() -> str | None:
    """启动时调一次：定位 adb、准备状态目录、返回 adb 路径。

    幂等，重复调用没有副作用。
    """
    state_dir()
    screenshots_dir()
    return find_adb()

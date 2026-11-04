"""设备控制层：adbutils + uiautomator dump + input 命令。

不用 uiautomator2：它自带的 com.wetest.uia2.stub 在 Android 17(SDK37) 上
UiDevice.getDisplaySizeDp() 会抛 ApplicationSharedMemory not initialized。
这里直接解析平台 uiautomator dump 的 XML，零设备侧依赖。

性能要点（实测，Windows + adb over USB）：
    echo 1                        ~80ms
    dumpsys window|grep focus     ~170ms
    input tap / keyevent          ~140ms
    uiautomator dump /dev/tty     ~2400ms   <-- 唯一的大头（设备侧 JVM 启动）
所以提速的关键不是把每次 dump 变快（做不到），而是**少 dump**：
先花 0.17s 轮询廉价的活动/焦点信号，再 dump 一次拿控件树。
"""
from __future__ import annotations

import io
import os
import re
import tempfile
import time
from dataclasses import dataclass

import adbutils

import locale_kit

# 滚轮（NumberPicker）闭环参数。实测一次 700px 滑动约等于 +11 格 => ≈64px/格。
WHEEL_PX_PER_UNIT = 64
WHEEL_MAX_UNITS = 10   # 单次最多滑 10 格，再大就有惯性过冲
WHEEL_SETTLE = 0.3

_NODE_RE = re.compile(r"<node\b[^>]*>")
_ATTR_RE = re.compile(r'([\w:-]+)="([^"]*)"')
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

# adb 传输层掉线的特征。只有这类错误才值得「等设备回来再重试」；
# 其它 AdbError（比如 Unknown command、命令本身写错）重试也没用，直接抛。
_TRANSPORT_DOWN_RE = re.compile(
    r"device '[^']*' not found|device offline|device still connecting|"
    r"no devices/emulators found|connection (?:reset|refused|closed|aborted)|"
    r"error: closed|broken pipe|EOF|timed? ?out|TimeoutError|socket",
    re.I,
)

KEY_BACK = 4
KEY_HOME = 3
KEY_POWER = 26
KEY_WAKEUP = 224
KEY_ESC = 111

# 桌面（launcher）包名与「首页」特征。
# 为什么不能用 page_indicator：XOS 的 page_indicator 每一页都存在且 content-desc
# 恒为「主屏幕」，它只表示「桌面页指示器」，不表示当前停在第几页。
# 也不能靠 dumpsys：TrCellLayout 各页的坐标在所有页上完全一致，TrWorkSpace
# 里没有 scrollX / mCurrentPage 可读。唯一可靠的信号是首页专属控件是否存在：
# 时钟 widget（tc_time / tc_date）、温度（tv_temperature）、「智慧建议」标题。
LAUNCHER_PKG = "com.transsion.launcher3"
ATOMIC_PKG = "com.transsion.atomicbrain"
ATOMIC_CORE_PKG = "com.transsion.atomiccore"
HOME_PAGE_RIDS = ("tc_time", "tc_date", "tv_temperature")
# 首页「智慧建议」标题在三种系统语言下文案完全不同：中文 `智慧建议`、
# 英文 `Smart suggestions`、阿拉伯语 `AI اقتراحات`。这里全部收进来，
# 作为 rid 之外的第二判据（rid 已足够，文本只是兜底）。
HOME_PAGE_TEXTS = ("智慧建议", "Smart suggestions", "Smart Suggestions",
                   "AI suggestions", "AI اقتراحات", "اقتراحات ذكية")


def parse_wheel_value(rid: str, desc: str) -> int:
    """把滚轮 content-desc 解析成数值，兼容数字 / 英/中/阿月份。

    部分设备的日期滚轮把月份显示成 "Oct" 而非 "10"，阿拉伯语下是
    `نوفمبر`、日号还可能是阿拉伯-印度数字 `١٦`，直接搜 \\d 会抛
    「content-desc 无数字」。这里统一交给 locale_kit 归一化后再解析。
    """
    norm = locale_kit.to_ascii_digits(desc)
    m = re.search(r"-?\d+", norm)
    if "month" in rid or "月" in desc:
        idx = locale_kit.month_index_in(norm)
        if idx is not None:
            return idx
    if m:
        return int(m.group(0))
    raise UiError(f"滚轮 {rid} 的 content-desc 无数字：{desc!r}")


class UiError(RuntimeError):
    pass


@dataclass
class Node:
    attrs: dict

    @property
    def text(self) -> str:
        return self.attrs.get("text", "")

    @property
    def desc(self) -> str:
        return self.attrs.get("content-desc", "")

    @property
    def rid(self) -> str:
        return self.attrs.get("resource-id", "")

    @property
    def short_id(self) -> str:
        return self.rid.split("/")[-1]

    @property
    def cls(self) -> str:
        return self.attrs.get("class", "")

    @property
    def pkg(self) -> str:
        return self.attrs.get("package", "")

    @property
    def clickable(self) -> bool:
        return self.attrs.get("clickable") == "true"

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        m = _BOUNDS_RE.match(self.attrs.get("bounds", ""))
        if not m:
            return (0, 0, 0, 0)
        return tuple(int(v) for v in m.groups())

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def __str__(self) -> str:
        return f"<{self.cls.split('.')[-1]} text={self.text!r} desc={self.desc!r} rid={self.short_id!r} center={self.center}>"


def _match(node: Node, text=None, desc=None, rid=None, cls=None,
           text_contains=None, desc_contains=None, rid_contains=None, clickable=None):
    if text is not None and node.text != text:
        return False
    if desc is not None and node.desc != desc:
        return False
    if cls is not None and node.cls != cls and node.cls.split(".")[-1] != cls:
        return False
    if clickable is not None and node.clickable != clickable:
        return False
    if rid is not None:
        if node.rid != rid and node.short_id != rid:
            return False
    if text_contains is not None and text_contains not in node.text:
        return False
    if desc_contains is not None and desc_contains not in node.desc:
        return False
    if rid_contains is not None and rid_contains not in node.rid:
        return False
    return True


class Device:
    def __init__(self, serial: str | None = None, log=None):
        self.log = log or (lambda msg: None)
        if serial is None:
            found = adbutils.adb.device_list()
            if not found:
                raise UiError(
                    "未检测到设备。请确认：USB 已连接、已开启 USB 调试、"
                    "并在手机弹窗中点了「允许」。"
                )
            serial = found[0].serial
        self.d = adbutils.adb.device(serial=serial)
        self.serial = serial
        self._stayon_changed = False
        self._size: tuple[int, int] | None = None
        self._model: str | None = None
        # 刚插上/刚换机时 transport 可能还没注册好，先确认一次再开工，
        # 否则第一步就报 `device 'xxx' not found`。
        self._call(lambda: self.d.shell("echo ok"))

    # ---------- 基础 ----------
    def _wait_transport(self, timeout: float = 20.0) -> None:
        """等设备重新注册回 adb server，回来后重建 adbutils 句柄。

        USB 抖一下 / adb server 刚被重启时，transport 会短暂消失，这时任何
        adb 命令都会报 `device 'xxx' not found`。整条流程动辄几十步，
        中途抖一次就整场报废太脆，所以这里等它回来。
        """
        deadline = time.time() + timeout
        while True:
            try:
                for d in adbutils.adb.device_list():
                    if d.serial == self.serial and d.get_state() == "device":
                        self.d = adbutils.adb.device(serial=self.serial)
                        return
            except Exception:
                pass
            if time.time() >= deadline:
                raise UiError(
                    f"设备 {self.serial} 掉线了，等了 {timeout:.0f} 秒还没回来。"
                    "请检查 USB 线是否插稳、手机有没有弹出「允许 USB 调试」。"
                )
            time.sleep(0.5)

    def _call(self, fn):
        """跑一次 adb 操作 fn()（无参闭包，内部自己取 self.d）。

        遇到传输层错误就等设备回来再试，最多 3 次；3 次都失败才抛 UiError，
        把最后一次的原始报错带上，方便定位是掉线还是命令本身有问题。
        """
        last = None
        for attempt in range(3):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 —— 只挑传输层错误重试
                if not _TRANSPORT_DOWN_RE.search(str(exc)):
                    raise
                last = exc
                self.log(f"[warn] adb 暂时连不上 {self.serial}（{exc}），等它回来…")
                self._wait_transport()
        raise UiError(f"adb 与设备 {self.serial} 通信失败（重试 3 次）：{last}")

    def shell(self, cmd: str) -> str:
        return self._call(lambda: self.d.shell(cmd))

    def clear_atomic_services(self):
        """清空原子服务缓存 + 桌面数据，重试卡片前调用。

        launcher3 也要清：智慧建议卡片区是桌面的一部分，上一轮的卡片状态、
        停留页、卡片被划走的位置都在 launcher 的 SharedPreferences 里，
        不清的话重试时经常「新卡片被旧状态挡住」。
        """
        for pkg in (LAUNCHER_PKG, ATOMIC_PKG, ATOMIC_CORE_PKG):
            self.shell(f"pm clear {pkg}")
            self.log(f"[info] 已清空 {pkg}")

    def key(self, keycode: int) -> None:
        self.shell(f"input keyevent {keycode}")

    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}")

    def input_text(self, text: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9@._%+=:,-]*", text):
            raise UiError(
                f"input text 只支持 ASCII 字母数字和少量符号，收到 {text!r}。"
                "中文需要先在手机上装 ADBKeyboard。"
            )
        # 白名单已排除空格、引号、$、`、\ 等，双引号包裹即可安全传给 adb shell
        self.shell(f'input text "{text}"')

    def focus(self) -> str:
        """当前焦点窗口（约 0.17s）。比 dump 便宜 14 倍，用来轮询界面切换。"""
        out = self.shell("dumpsys window | grep mCurrentFocus")
        m = re.findall(r"u0 ([\w.$/]+)", out)
        return m[-1] if m else out.strip()

    def wait_focus(self, needle: str, timeout: float = 15.0,
                   interval: float = 0.25) -> str:
        """廉价等待：轮询焦点窗口直到出现关键词（切 Activity / 开页面时用）。"""
        deadline = time.time() + timeout
        last = ""
        while True:
            last = self.focus()
            if needle.lower() in last.lower():
                return last
            if time.time() >= deadline:
                raise UiError(f"等待窗口 {needle!r} 超时({timeout}s)，当前 {last!r}")
            time.sleep(interval)

    def keyguard_showing(self) -> bool:
        return self.locked()

    def locked(self) -> bool:
        """锁屏判定：系统标志为准，焦点窗口兜底。

        个别无锁屏密码的设备（平板常见）上滑解锁后 isKeyguardShowing 标志
        不翻转，只信标志会误报「仍锁定」；此时若焦点已离开锁屏窗口
        （回到桌面/应用），判定为已解锁。

        注意：指纹/上滑锁屏的焦点常见是 NotificationShade 或 StatusBar，
        不能把这些窗口误判成「已解锁」，否则 wm dismiss-keyguard 失败时
        不会再回退上滑。
        """
        focus, kg = self.window_info()
        if not kg:
            return False
        if not focus:
            return True
        f = focus.lower()
        if "keyguard" in f or "notificationshade" in f or "statusbar" in f:
            return True
        return False

    def window_info(self) -> tuple[str, bool]:
        """一次 dumpsys 同时拿到焦点窗口和锁屏状态，省掉一次 adb 往返。

        解锁轮询里每次都要问锁屏，和焦点查询合并后每次省 ~0.17s。
        """
        out = self.shell('dumpsys window | grep -E "mCurrentFocus|isKeyguardShowing"')
        m = re.findall(r"u0 ([\w.$/]+)", out)
        focus = m[-1] if m else out.strip()
        return focus, "isKeyguardShowing=true" in out

    def screen_on(self) -> bool:
        return "mWakefulness=Awake" in self.shell("dumpsys power | grep mWakefulness=")

    def screenshot_png(self) -> bytes:
        # 有些机型有多个 display，adb exec-out 的 screencap 会把
        # "Multiple displays..." 警告混进字节流，adbutils 直接解码会失败。
        # 先落到设备文件再 pull，警告只走 stderr，不会污染 PNG。
        remote = f"/sdcard/.dsh_screen_{os.getpid()}.png"
        local = ""
        try:
            self.shell(f"screencap -p {remote}")
            fd, local = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            self._call(lambda: self.d.sync.pull(remote, local))
            with open(local, "rb") as fh:
                data = fh.read()
            if not data.startswith(b"\x89PNG"):
                raise UiError("截图失败：screencap 没有返回有效 PNG")
            return data
        finally:
            if local:
                try:
                    os.unlink(local)
                except OSError:
                    pass
            try:
                self.shell(f"rm -f {remote}")
            except Exception:
                pass

    def screen_size(self) -> tuple[int, int]:
        """缓存：整条流程会反复问，每次都是一次 adb 往返。"""
        if self._size is None:
            out = self.shell("wm size")
            m = re.search(r"(\d+)x(\d+)", out)
            self._size = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        return self._size

    def model(self) -> str:
        if self._model is None:
            self._model = (self._call(lambda: self.d.prop.get("ro.product.model"))
                           or "unknown")
        return self._model

    def stayon(self, on: bool) -> None:
        self.shell(f"svc power stayon {'usb' if on else 'false'}")
        self._stayon_changed = True

    # ---------- 桌面首页 ----------
    def launcher_visible(self) -> bool:
        """廉价判断（一次 dumpsys，约 0.17s）：焦点窗口是不是桌面。"""
        return LAUNCHER_PKG in self.focus().lower()

    def at_launcher_home(self, nodes: list[Node] | None = None) -> bool:
        """是不是停在桌面「首页」（有智慧建议卡片区的那一页）。

        桌面有好几页，page_indicator 每页都在、content-desc 恒为「主屏幕」，
        区分不了；只有首页才挂着时钟 widget（tc_time / tc_date /
        tv_temperature）和「智慧建议」标题。所以按这些控件判断。

        先做 0.17s 的焦点判断，不在桌面上就直接 False，省掉 2.4s 的 dump。
        """
        if not self.launcher_visible():
            return False
        nodes = self.dump() if nodes is None else nodes
        rid_tail = {(n.rid or "").split("/")[-1] for n in nodes}
        if any(t in rid_tail for t in HOME_PAGE_RIDS):
            return True
        texts = {(n.text or "").strip() for n in nodes}
        return any(t in texts for t in HOME_PAGE_TEXTS)

    def goto_launcher_home(self, max_presses: int = 3,
                           settle: float = 0.8) -> bool:
        """回到桌面首页，返回是否成功。

        按一次 HOME 系统就会从任意分页跳回首页，所以通常一次就够；
        多按几次是为了兜住「HOME 被动画/弹窗吞掉」的情况。每次都重新判定，
        避免在已经回到首页时还多按（多按会把页面上的卡片划走）。
        """
        for i in range(max_presses):
            self.key(KEY_HOME)
            time.sleep(settle if i == 0 else 0.5)
            if self.at_launcher_home():
                return True
        return False

    # ---------- 控件树 ----------
    def dump(self, retries: int = 3) -> list[Node]:
        """读控件树。

        `uiautomator dump` 在界面持续刷新时会报 `could not get idle state.`
        （实测：时钟 App 的闹钟列表，倒计时文字每秒都在变），旧实现直接
        抛「控件树为空」。这里改成重试 + `--compressed` 兜底：压缩模式
        不等窗口 idle，能拿到树（只是少了部分无用节点）。
        """
        last = ""
        for attempt in range(1, retries + 1):
            flag = "" if attempt == 1 else " --compressed"
            raw = self.shell(f"uiautomator dump{flag} /dev/tty")
            end = raw.find("</hierarchy>")
            xml = raw[: end + len("</hierarchy>")] if end != -1 else raw
            nodes = []
            for m in _NODE_RE.finditer(xml):
                nodes.append(Node(dict(_ATTR_RE.findall(m.group(0)))))
            if nodes:
                return nodes
            last = raw[:200]
            time.sleep(0.6)
        raise UiError("控件树为空，dump 可能失败。原始输出前 200 字符：" + repr(last))

    def find_all(self, nodes=None, **kw) -> list[Node]:
        nodes = self.dump() if nodes is None else nodes
        return [n for n in nodes if _match(n, **kw)]

    def find_opt(self, nodes=None, **kw):
        r = self.find_all(nodes=nodes, **kw)
        return r[0] if r else None

    def find(self, nodes=None, **kw) -> Node:
        n = self.find_opt(nodes=nodes, **kw)
        if n is None:
            raise UiError(f"未找到控件 {kw}。当前界面：{self.focus()}")
        return n

    # ---------- 等待（核心提速点：一次 dump 拿树，settle 内命中就只 dump 一次） ----------
    def wait_nodes(self, timeout: float = 10.0, settle: float = 0.0, **kw) -> list[Node]:
        """等某个控件出现，并把命中的那次整棵控件树返回，供后续 find 复用。

        settle 是"先干等一段动画时间再 dump"：界面切换通常在 1s 内完成，
        这样一次 dump 就命中，而不是 dump 失败后再等一次（每次 dump 2.4s）。
        """
        if settle:
            time.sleep(settle)
        deadline = time.time() + timeout
        while True:
            try:
                nodes = self.dump()
            except UiError:
                nodes = []
            if nodes and self.find_opt(nodes=nodes, **kw) is not None:
                return nodes
            if time.time() >= deadline:
                raise UiError(f"等待控件超时({timeout}s) {kw}。当前界面：{self.focus()}")

    def wait_node(self, timeout: float = 10.0, settle: float = 0.9, **kw) -> Node:
        nodes = self.wait_nodes(timeout=timeout, settle=settle, **kw)
        return self.find_opt(nodes=nodes, **kw)

    def wait_for(self, timeout: float = 10.0, settle: float = 0.0, **kw) -> Node:
        nodes = self.wait_nodes(timeout=timeout, settle=settle, **kw)
        return self.find_opt(nodes=nodes, **kw)

    def wait_gone(self, timeout: float = 8.0, settle: float = 0.3, **kw) -> None:
        """等控件消失（对话框关闭），按 dump 轮询。"""
        if settle:
            time.sleep(settle)
        deadline = time.time() + timeout
        while True:
            if self.find_opt(**kw) is None:
                return
            if time.time() >= deadline:
                raise UiError(f"等待控件消失超时({timeout}s) {kw}")
            time.sleep(0.4)

    # ---------- 动作 ----------
    def tap_node(self, node: Node, settle: float = 0.4) -> None:
        x, y = node.center
        self.log(f"tap ({x},{y}) {node}")
        self.tap(x, y)
        time.sleep(settle)

    def tap_by(self, settle: float = 0.5, **kw) -> Node:
        n = self.find(**kw)
        self.tap_node(n, settle)
        return n

    # ---------- 滚轮 ----------
    def wheel_values(self, *rids: str, nodes: list[Node] | None = None
                     ) -> tuple[list[Node], dict[str, int]]:
        """一次 dump 读出多个滚轮的当前值。

        逐个读时每个滚轮每轮都要 dump 一次（各 2.4s）；合并成每轮只 dump 一次，
        日期 + 时间两组滚轮能省掉一大半 dump。nodes 可传入已抓好的控件树，
        让首次读取复用调用方的 wait_nodes，省下第一轮 dump。
        """
        if nodes is None:
            nodes = self.dump()
        values: dict[str, int] = {}
        for rid in rids:
            n = self.find(nodes=nodes, rid=rid)
            values[rid] = parse_wheel_value(rid, n.desc)
        return nodes, values

    def set_wheels(self, targets: dict[str, int], max_rounds: int = 8,
                   nodes: list[Node] | None = None) -> list[Node]:
        """闭环批量设定多个滚轮：每轮只 dump 一次读取全部当前值，再逐列滑动到位。

        返回最后一次 dump 的控件树——此时滚轮已收敛，页面标题也是新值，
        调用方可直接复用，不必再补一次 dump。
        """
        for _ in range(max_rounds):
            nodes, cur = self.wheel_values(*targets, nodes=nodes)
            todo = {rid: t - cur[rid] for rid, t in targets.items() if t != cur[rid]}
            if not todo:
                return nodes
            for rid, delta in todo.items():
                units = max(-WHEEL_MAX_UNITS, min(WHEEL_MAX_UNITS, delta))
                cx, cy = self.find(nodes=nodes, rid=rid).center
                # 上滑(终点 y 更小) = 数值增大
                self.swipe(cx, cy, cx, cy - units * WHEEL_PX_PER_UNIT, 250)
                self.log(f"滚轮 {rid}: {cur[rid]} -> {targets[rid]} (滑 {units} 格)")
            time.sleep(WHEEL_SETTLE)
            nodes = None   # 滚轮已动，下一轮必须重新 dump
        _, cur = self.wheel_values(*targets)
        raise UiError(f"滚轮无法收敛：目标 {targets}，当前 {cur}")

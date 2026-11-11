"""生日策划案卡片触发场景。

流程（对应用户描述的 10 步）：
  打开日历 -> 选「今天+4」-> 点添加 -> 选重要日 -> 下拉勾选生日
  -> 输入姓名 -> 保存 -> 设置里改系统日期为「今天+1」09:30
  -> 校验系统日期是生日前3天 -> 息屏60秒 -> 亮屏上滑解锁

可独立运行： python scenario_birthday.py

提速（不改流程语义）：uiautomator dump 每次约 2.4s，是唯一大头，所以
  1) 切 Activity 时先用 ~0.17s 的焦点轮询（wait_focus），再 dump 一次；
  2) 用 wait_nodes 在"命中那一次 dump"里把整棵树带回来给后续 find 复用；
  3) 凡是"点一下 -> 等新界面"的地方，改成 短 settle + 一次 dump 命中，
     而不是旧代码那种"先 sleep 2s 再 dump 轮询"。
"""
from __future__ import annotations

import base64
import calendar as _calendar
import random
import re
import time
from datetime import date, timedelta

import fast_clock
import fixtures
import locale_kit as lk
from phone_ctl import (
    KEY_BACK,
    KEY_ESC,
    KEY_HOME,
    KEY_POWER,
    KEY_WAKEUP,
    Device,
    Node,
    UiError,
)

CALENDAR_PKG = "com.transsion.calendar"
CALENDAR_ACT = "com.android.calendar.AllInOneActivity"
CALENDAR_CMP = f"{CALENDAR_PKG}/{CALENDAR_ACT}"
DATE_SETTINGS_CMP = "com.android.settings/com.android.settings.Settings$DateTimeSettingsActivity"

# 日历的 VIEW content URI。注意：英文系统下系统会把它当成可打开的文件（Google /
# Phone Master / Terabox 等都声明了 content:// 的 VIEW 过滤），弹出「Open With」
# 选择框（com.transsion.resolver）。所以只能作为显式组件启动的兜底，且启动后
# 必须检查是否落到 resolver 上，落上了就关掉重来。
CALENDAR_VIEW_URI = "content://com.transsion.calendar/events"

# 「AI 课程表」子页特征。这个页面是**只读的守门条件**：一旦命中就按返回键退出，
# 任何情况下都不去点它（点进去会卡在课表页，随后日历控件全部找不到 → 报错）。
TIMETABLE_HINTS = ("课表", "课程表", "timetable", "class schedule",
                   "الجدول الدراسي", "جدول الحصص", "جدول الدراسة")


def on_timetable(nodes: list[Node]) -> bool:
    """当前界面是不是「AI 课程表」子页。

    只在顶部标题区找线索：整页正文里出现「课表」二字不算（日历设置里也有这个词），
    否则会把正常的日历页误判成课表页、白白按一堆返回键。
    """
    if any(n.rid.endswith("school_schedule_fragment") for n in nodes):
        return True
    title = [n for n in nodes
             if n.center[1] < 620
             and n.rid.endswith(("toolbar_title", "title", "tv_title"))]
    if not title:
        # 没有标题栏 rid 可依时，退一步看顶部 620px 内的可读文本
        title = [n for n in nodes if n.center[1] < 620 and (n.text or n.desc)]
    for n in title:
        blob = f"{n.text or ''} {n.desc or ''}".lower()
        if any(h in blob for h in TIMETABLE_HINTS):
            return True
    return False


def launch_calendar(dev: Device, timeout: float = 10.0) -> bool:
    """显式组件启动日历，绕开「Open With」选择框。返回是否真的进到日历。

    历史：早期用 `am start -a VIEW -d <content uri>` 直接打开月视图，但它只是
    「内容 URI」，任何声明了 VIEW + content scheme 的应用（Google App、
    Phone Master、Terabox）都能接，英文系统 + 这些应用后装时会弹选择框。
    现在优先用显式组件（不需要任何 intent filter 解析），失败才退回 VIEW。

    两条启动命令都**不带任何 extra**：实测一旦带上日历自己的额外参数，它会直接
    跳到「AI 课程表」子页，而那个页面里没有任何日期格子，后续必然失败。
    万一真落到了课表页，由 _ensure_calendar_month 的 on_timetable 守卫按返回键退出。
    """
    # 只用显式组件、不按 HOME：调用方刚从日历页返回时 HOME 会被 launcher 的动画
    # 吃掉一部分（实测焦点仍是日历，于是退化成「什么都不做」），而日历在前台时
    # 显式组件启动就是一次 NO-OP 的 bringToFront。真没起来再退回 VIEW。
    for i, cmd in enumerate((
            f"am start -f 0x10000000 -n {CALENDAR_CMP}",
            f"am start -a android.intent.action.VIEW -d '{CALENDAR_VIEW_URI}'")):
        dev.shell(cmd)
        try:
            dev.wait_focus("calendar", timeout=timeout)
        except UiError:
            focus = dev.focus() or ""
            if "resolver" not in focus:
                continue
            dev.log(f"打开日历时弹出了「Open With」选择框（{focus}），按返回键关掉重试")
            dev.key(KEY_BACK)
            time.sleep(0.6)
            continue
        # 起来了但落在课表页 → 按返回键退回日历主页，返回 True 让上层继续
        for _ in range(3):
            if not on_timetable(dev.dump()):
                return True
            dev.log("启动后落在「AI 课程表」子页，按返回键退回日历主页")
            dev.key(KEY_BACK)
            time.sleep(0.8)
        return True
    return False

CN_WEEK = "一二三四五六日"
CN_MONTH = ["一月", "二月", "三月", "四月", "五月", "六月",
            "七月", "八月", "九月", "十月", "十一月", "十二月"]

REMIND_DAYS_BEFORE = 3

# 纪念日类卡片（desktop_wait_sec > 0）的二次触发等待。
# 实机踩过：这台 X6766 上「回桌面等 60s + 亮屏等 8s」不够，卡片还没渲染
# 完就截了图，结果翻遍轮播都找不到。加长到 90s / 30s 后稳定出卡。
# 两个值都放这里，避免散在函数里到处硬编码（README 里也单独记了一笔）。
DESKTOP_WAIT_SEC = 90
LOCK_RENDER_SEC = 30
PUA_RE = re.compile(r"[\ue000-\uf8ff]")

# 日历「重要日」事件类型（extendedproperties private:ts_cal_event_type 的 value，均已实机验证）
CAL_TYPE_BIRTHDAY = "birthday"
CAL_TYPE_ANNIVERSARY = "anniversary"
CAL_TYPE_EXAM = "exam"
CAL_TYPE_PERFORMANCE = "performance"   # 观演日（Show Day）
CAL_TYPE_NONE = "none"                 # 不勾选任何类型（下拉 None）
# 事件类型 → 类型下拉文案 / 姓名占位符（中英阿三语）
# `labels` 是下拉里该类型的候选文案全集，用来在控件树里找到那个选项。
_EV_TYPES = {
    CAL_TYPE_BIRTHDAY: dict(cn="生日", en="Birthday", ph="输入姓名",
                            labels=lk.labels("birthday")),
    CAL_TYPE_ANNIVERSARY: dict(cn="纪念日", en="Anniversary", ph="输入纪念日名称",
                               labels=lk.labels("anniversary")),
    CAL_TYPE_EXAM: dict(cn="考试", en="Exam Day", ph="输入考试名称",
                        labels=lk.labels("exam")),
    CAL_TYPE_PERFORMANCE: dict(cn="观演日", en="Show Day", ph="Activity name",
                               labels=lk.labels("performance")),
    CAL_TYPE_NONE: dict(cn="None", en="None", ph="My important day",
                        labels=("None", "无", "لا يوجد")),
}

_EN_MONTHS = ["january", "february", "march", "april", "may", "june",
              "july", "august", "september", "october", "november", "december"]
_EN_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_title_parts(text: str) -> tuple[int | None, int | None]:
    """月份标题 → (年份, 1..12)。

    各机型/各语言写法差得很远，实测见过这些：'十月'、'2026年12月'、'12月'、
    'Oct'、'October 2026'、阿拉伯语 'نوفمبر'。年份认不出就返回 None，
    调用方按「只看月份」处理。

    识别逻辑全部下沉到 locale_kit：中文要**从十二月往一月倒着匹配**（否则
    「十一月」会被「一月」抢先命中），阿拉伯/英/数字写法也都在那边统一处理。
    """
    if not text:
        return None, None
    return lk.year_in(text), lk.month_index_in(text)


def month_title_index(text: str) -> int | None:
    """月份标题 → 1..12。中文「十月」、英文「Oct」、阿拉伯语「نوفمبر」都能认。"""
    return month_title_parts(text)[1]

# 设置/对话框文案要兼容中/英/阿三语系统（实测这台手机三种语言都会切）。
# 具体词表在 locale_kit.UI_LABELS，这里只做别名，避免各场景各写一套。
AUTO_TIME_LABELS = lk.labels("auto_time")
DATE_LABELS = lk.labels("date")
TIME_LABELS = lk.labels("time")
OK_LABELS = lk.labels("ok")
# 日历引导/导入弹窗的按钮文案（三语都认）。btn_negative 优先更安全。
DIALOG_BUTTONS = lk.labels("dialog_buttons")


def _find_first_text(nodes: list[Node], labels: tuple[str, ...]) -> Node | None:
    """精确匹配任一文案，找不到再退到「包含」，兼容长短文案差异。

    包含匹配要**选文本最短的那个**：阿拉伯语里「时间」行是 `الوقت`，而
    「自动设置时间」行是 `تعيين الوقت تلقائيًا`，后者包含前者；按控件顺序
    取第一个会把自动时间行当成时间行点掉（滚轮根本不弹）。中文同理
    （'时间' ⊂ '自动设置时间'）。选最短文本能稳定命中真正的短标题。
    """
    for n in nodes:
        if n.text in labels:
            return n
    best: Node | None = None
    for n in nodes:
        text = n.text or ""
        if not text:
            continue
        if any(lab and lab in text for lab in labels):
            if best is None or len(text) < len(best.text or ""):
                best = n
    return best


def _title_matches_date(title: str, d: date) -> bool:
    """滚轮对话框标题是否符合目标日期，兼容 中文/英文/数字 各种格式。"""
    if f"{d.year}年{d.month}月{d.day}日" in title:
        return True
    mon_abbr = _calendar.month_abbr[d.month]     # Oct
    mon_full = _calendar.month_name[d.month]     # October
    for pat in (f"{d.day} {mon_abbr} {d.year}", f"{mon_abbr} {d.day}, {d.year}",
                f"{d.day} {mon_full} {d.year}", f"{mon_full} {d.day}, {d.year}",
                f"{d.month}/{d.day}/{d.year}", f"{d.day}/{d.month}/{d.year}"):
        if pat in title:
            return True
    return False


def _time_matches_title(title: str, hour: int, minute: int) -> bool:
    m = re.search(r"(\d{1,2}):(\d{2})", title)
    return bool(m) and int(m.group(1)) == hour and int(m.group(2)) == minute


def date_text_matches(text: str, target: date) -> bool:
    """界面上的日期文本是否指向 target（中/英/阿三语、任意排版）。

    以前这里写死了 `'11月8日' / '8 Nov' / 'Nov 8'` 三种格式，换成阿拉伯语后
    日历顶部变成 `الاثنين، ١٦ نوفمبر`，一个都对不上（而且日号还是阿拉伯-印度
    数字）。这里改成「先归一化数字、再分别校验月份词与日号」，不依赖顺序。
    """
    raw = (text or "").strip()
    if not raw:
        return False
    norm = lk.to_ascii_digits(raw)
    mon = lk.month_index_in(norm)
    if mon is not None and mon != target.month:
        return False
    # 日号：按非数字边界精确匹配，避免 '16' 命中 '2016'
    if not re.search(rf"(?<!\d){target.day}(?!\d)", norm):
        return False
    # 月份词认不出时（纯数字格式），至少要求日号对上且没有矛盾月份
    return mon is not None or bool(re.search(r"\d", norm))


def date_cell_descs(dt: date) -> list[str]:
    """日期格子的 content-desc 候选（中/英/阿三语、月网格/周条/周视图通用）。

    具体格式表见 locale_kit.date_cell_descs —— 阿拉伯语下日期格是
    'الاثنين، ١٦ نوفمبر'，日号用阿拉伯-印度数字，中文/英文候选一个都匹配不上。
    """
    return lk.date_cell_descs(dt)
    cn = f"{dt.month}月{dt.day}日星期{CN_WEEK[dt.weekday()]}"
    ab = _EN_MONTHS_ABBR[dt.month - 1]
    en = _EN_MONTHS[dt.month - 1].capitalize()
    wd = ["Monday", "Tuesday", "Wednesday", "Thursday",
          "Friday", "Saturday", "Sunday"][dt.weekday()]
    return [cn,
            f"{dt.month}月{dt.day}日周{CN_WEEK[dt.weekday()]}",
            f"{wd} {dt.day} {en}",
            # 实测日历切英文后，月视图格子的 desc 是 "Monday, November 9"
            # （带逗号、月在前、不带年份），日号数字本身不是 TextView，
            # 所以这两个格式必须包含，否则 desc/日号文本两条路都会漏。
            f"{wd}, {en} {dt.day}",
            f"{wd}, {en} {dt.day}, {dt.year}",
            f"{wd}, {ab} {dt.day}",
            f"{wd}, {ab} {dt.day}, {dt.year}",
            f"{wd} {en} {dt.day}",
            f"{wd}, {dt.day} {en}",
            f"{dt.day} {ab} {dt.year}",
            f"{ab} {dt.day}, {dt.year}", f"{ab} {dt.day}",
            f"{dt.day} {en}", f"{en} {dt.day}", f"{en} {dt.day}, {dt.year}",
            f"{dt.year}年{dt.month}月{dt.day}日",
            f"{dt.year}-{dt.month:02d}-{dt.day:02d}"]


def gen_name(today: date) -> str:
    return f"Bday{today.strftime('%m%d')}{random.randint(10, 99)}"


def device_date(dev: Device) -> date:
    """以手机时钟为基准，不能用电脑时钟。

    本场景会修改手机系统日期，跑过一次后两个时钟就不同步了；
    日历里的「N天后」是相对手机时钟显示的，用电脑时钟算会错位。
    """
    raw = dev.shell("date '+%Y-%m-%d'").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if not m:
        raise UiError(f"无法解析设备日期：{raw!r}")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


class Runner:
    def __init__(self, dev: Device, emit=None, control: dict | None = None,
                 confirm_fn=None, ask_fn=None):
        self.dev = dev
        self.emit = emit or (lambda e: None)
        self.control = control or {}     # {"paused": bool, "stop": bool}，由服务注入
        self.confirm_fn = confirm_fn     # 自动识别卡片的回调，None 时跳过
        self.ask_fn = ask_fn             # 触发前询问用户前置问题（如 OOBE 国家）的回调
        # 这张卡片「长什么样」的自述：卡片标题里带随机名字（Bday110792）时，
        # 名字只有跑到一半才知道，场景在这里写一句，确认时就能拿它当判据。
        self.card_hint = ""
        # 锁屏卡片只在解锁前的一瞬间可见；把那一刻控件树里的文案和区域
        # 记下来，自动识别阶段（已回桌面）才有依据判断卡片是否出现。
        self.lock_texts: list[str] = []
        self.lock_box: tuple[int, int, int, int] | None = None
        # 场景自己在跑的过程中**已经认到卡**时，把 CardHit 放这里。
        # main.py 的 _confirm_fn 看到它就直接入库，不再回头重扫一遍 ——
        # 这就是「只要识别到了就报成功，然后停止任务」。
        self.pre_hit = None
        self._no = 0
        self._t0 = 0.0

    def note_lockscreen(self, dev: Device) -> None:
        """在锁屏卡片可见时抓一份「证据快照」（文案 + 区域），供之后自动识别。

        重要日卡片（生日策划案 / 纪念日 / 追星 / 重要日提醒）是锁屏卡片：
        场景 `r.shot("锁屏卡片")` 拍完立刻就上滑解锁回桌面，等 `r.confirm()`
        时屏幕早不在锁屏了。所以必须在这一刻把控件树记下来。

        只做一次 dump，且不抛错 —— 这是个「顺手取证」的钩子，dump 失败
        不该让整个场景挂掉（自动识别会退回桌面轮播那条路）。
        """
        try:
            import card_probe
            nodes = dev.dump()
            texts = []
            for n in nodes:
                if n.short_id in card_probe.LOCK_CARD_RIDS:
                    t = (n.text or "").strip() or (n.desc or "").strip()
                    if t and t not in texts:
                        texts.append(t)
            self.lock_texts = texts
            self.lock_box = card_probe.lock_card_box(nodes)
            if texts:
                self.log(f"锁屏卡片文案：{' / '.join(texts)}")
                # 不动 card_hint：自动识别阶段直接拿 lock_texts 和关键词比，
                # 比把整句文案塞回 card_hint 更可靠（后者会污染桌面轮播的判据）。
        except Exception as exc:  # noqa: BLE001
            self.log(f"锁屏卡片取证失败（不影响后续识别）：{exc}")

    def check(self) -> None:
        """步骤间/等待循环里检查暂停与结束。暂停则发事件挂起直到继续；结束则抛错终止。"""
        if self.control.get("stop"):
            raise UiError("用户结束场景")
        if self.control.get("paused"):
            self.emit({"t": "pause", "no": self._no})
            while self.control.get("paused"):
                if self.control.get("stop"):
                    raise UiError("用户结束场景")
                time.sleep(0.3)
            self.emit({"t": "resume", "no": self._no})

    def confirm(self) -> bool:
        """等场景自动确认卡片是否已触发。返回 True=已触发 / False=未触发。

        以前是「等用户在网页上点已触发/未触发」，现在由服务端的自动识别
        （card_probe 滑智慧建议轮播 + 认锁屏原子卡片）给出结论，不再打断人。
        """
        if self.confirm_fn is None:
            return True
        return self.confirm_fn(self)

    def ask(self, prompt: str) -> bool:
        """触发前询问用户一个前置问题（如 OOBE 国家是否为中国）。

        返回 True=是 / False=否。没有询问回调（如命令行直跑）时默认通过。"""
        if self.ask_fn is None:
            self.log(f"（无询问回调，默认通过）{prompt}")
            return True
        return self.ask_fn(self, prompt)

    def step(self, title: str) -> None:
        self.check()
        self._no += 1
        self._t0 = time.time()
        self.emit({"t": "step", "no": self._no, "title": title, "state": "start"})

    def ok(self, detail: str = "") -> None:
        self.emit({"t": "step", "no": self._no, "state": "ok",
                   "ms": round((time.time() - self._t0) * 1000), "detail": detail})

    def log(self, msg: str) -> None:
        self.emit({"t": "log", "no": self._no, "msg": msg})

    def shot(self, tag: str = "") -> None:
        try:
            png = self.dev.screenshot_png()
        except Exception as exc:
            self.log(f"截图失败：{exc}")
            return
        self.emit({"t": "shot", "no": self._no, "tag": tag,
                   "png_b64": base64.b64encode(png).decode()})

    def tick(self, remain: int) -> None:
        self.emit({"t": "tick", "no": self._no, "remain": remain})


def _swipe_unlock(dev: Device, start: float = 0.97, end: float = 0.30,
                  ms: int = 250, timeout: float = 2.0) -> bool:
    """上滑解锁。起点必须在屏幕底部提示区：从通知卡片上起滑会被当成滚动卡片。

    解锁判定走 dev.locked()：无锁屏密码的设备（平板常见）上滑后
    isKeyguardShowing 标志不翻转，只信标志会把「已解锁」误判成「仍锁定」。
    """
    w, h = dev.screen_size()
    dev.swipe(w // 2, int(h * start), w // 2, int(h * end), ms)
    # 轮询廉价信号：一次 dumpsys 同时拿锁屏状态（省一次 adb 往返），解锁成功立刻返回
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not dev.locked():
            return True
        time.sleep(0.15)
    return not dev.locked()


def _fast_unlock(dev: Device, r: Runner, unlock_retries: int = 3) -> None:
    """优先用 wm dismiss-keyguard（几十毫秒）；不支持再回退上滑。"""
    try:
        dev.shell("wm dismiss-keyguard")
        time.sleep(0.5)
        if not dev.locked():
            return
        r.log("wm 解锁未生效，回退上滑解锁")
    except Exception:
        pass
    _unlock_with_retries(dev, r, unlock_retries)


def _unlock_with_retries(dev: Device, r: Runner, unlock_retries: int = 3,
                         wake: bool = False) -> None:
    """亮屏后自动上滑解锁，最多试 unlock_retries 次，全失败给出明确报错。

    wake=True 时负责「唤醒 + 等屏幕可交互」：唤醒动画期间第一下上滑常被系统吞掉，
    所以要等屏幕真正就绪后再滑。
    手势轮换多种变体：慢速长滑在部分平板上会被当成拖拽，改贴底边快甩再试。
    起点必须贴到屏幕最底部（>=0.96）：锁屏上有通知卡片时，从卡片区域起滑
    会被当成滚动卡片内容，导致解锁失败。
    若设备设置了 PIN/图案锁，上滑无法解锁，最后会明确提示手动解锁。
    """
    if wake:
        dev.stayon(True)
        dev.key(KEY_WAKEUP)
        _wait_screen_on(dev, True, timeout=3.0)
        time.sleep(0.6)                       # 等唤醒动画结束、触摸可用
    if not dev.keyguard_showing():
        return
    variants = [(0.97, 0.30, 250), (0.965, 0.42, 130), (0.98, 0.52, 150)]
    for i in range(unlock_retries):
        start, end, ms = variants[i % len(variants)]
        r.log(f"上滑解锁（第 {i + 1} 次）")
        if _swipe_unlock(dev, start=start, end=end, ms=ms):
            return
        time.sleep(0.4)
    raise UiError("自动上滑解锁失败，屏幕仍处于锁定状态（可能设置了 PIN/图案锁），"
                  "请手动解锁后重试")


def _dismiss_keyboard_terms(dev: Device, r: Runner) -> None:
    """只关闭 Emoji Keyboard 首次的 Terms and Conditions，别误点键盘按键。"""
    nodes = dev.dump()
    blob = " ".join((n.text or "") for n in nodes).lower()
    if not any(k in blob for k in ("terms and conditions", "terms of use",
                                   "privacy policy", "emoji keyboard",
                                   "الشروط والأحكام", "سياسة الخصوصية")):
        return
    btn = _find_first_text(nodes, ("Agree And Continue", "Agree & Continue",
                                   "同意并继续", "Agree", "同意",
                                   "أوافق", "الموافقة والمتابعة", "موافق"))
    if btn is not None:
        r.log(f"检测到输入法条款弹窗，点「{btn.text}」")
        dev.tap_node(btn, 0.6)
        time.sleep(0.4)
        return
    close = _find_first_text(nodes, ("×", "✕", "Close", "关闭", "إغلاق"))
    if close is not None:
        r.log("输入法条款弹窗没有 Agree 按钮，点关闭")
        dev.tap_node(close, 0.6)
        time.sleep(0.4)


def _in_dialog(node: Node, nodes: list[Node]) -> bool:
    """判断这个节点是不是长在真正的弹窗里（而不是页面上的横幅/正文）。

    病根记录：X6766 日历主页有一条「拍照一键导入，自动生成上课提醒。」横幅
    （rid=tv_banner_desc），它就是 AI 课程表的入口。旧版 _dismiss_popups 的
    文案兜底把它当成弹窗按钮点了进去，于是「明明没点课表却进了课表」。
    这里加上位置约束：必须有 dialog/alert 类容器祖先，或者本身是 Button 且在
    屏幕下半部、字号不大——页面横幅两者都不满足。
    """
    rid = (node.rid or "")
    if any(k in rid for k in ("button", "btn_")):
        if node.cls and node.cls.endswith("Button"):
            return True
    # 找包含它的 dialog 容器（按 bounds 包住来判断，dump 树没给父子指针）
    x1, y1, x2, y2 = node.bounds
    for other in nodes:
        orid = (other.rid or "").lower()
        ocls = (other.cls or "").lower()
        if "dialog" not in orid and "dialog" not in ocls and \
                "alert" not in orid and "alert" not in ocls:
            continue
        a1, b1, a2, b2 = other.bounds
        if a1 <= x1 and b1 <= y1 and x2 <= a2 and y2 <= b2:
            return True
    return False


def _dismiss_popups(dev: Device, r: Runner, nodes: list[Node] | None = None) -> list[Node]:
    """关掉日历的引导/导入类弹窗，复用当前 dump，避免白 dump。

    只认两种东西（顺序严格）：
      1. 真正的对话框按钮资源 id：btn_negative（Cancel/取消，最安全）→ btn_positive；
      2. 文案兜底，且必须 _in_dialog() 为真——**页面横幅绝不能点**，
         否则会误入「AI 课程表」（见 _in_dialog 的注释）。
    循环最多 4 轮：有些日历弹窗点掉一个还会再弹一个。
    """
    nodes = nodes if nodes is not None else dev.dump()
    for _ in range(4):
        btn = dev.find_opt(nodes=nodes, rid="btn_negative")
        if btn is None:
            btn = dev.find_opt(nodes=nodes, rid="btn_positive")
        if btn is None:
            cand = _find_first_text(nodes, DIALOG_BUTTONS)
            if cand is not None and _in_dialog(cand, nodes):
                btn = cand
        if btn is None:
            return nodes
        r.log(f"检测到弹窗，点「{btn.text or btn.desc or '按钮'}」关闭")
        dev.tap_node(btn, 0.5)
        nodes = dev.dump()
    return nodes


def _wait_screen_on(dev: Device, on: bool, timeout: float = 3.0) -> bool:
    """轮询电源状态等亮屏/灭屏，比固定 sleep 更快也更稳。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if dev.screen_on() == on:
            return True
        time.sleep(0.15)
    return dev.screen_on() == on


def goto_launcher_home(dev: Device, r: Runner) -> None:
    """回到桌面「首页」，也就是挂着智慧建议卡片区的那一页。

    为什么必须回首页：桌面有好几页，智慧建议卡片只在首页显示；
    停在别的分页时截图和用户确认都会落空，白等一轮。
    判定走 Device.at_launcher_home()（看首页专属控件，不是看 page_indicator）。
    """
    if dev.goto_launcher_home():
        r.log("已回到桌面首页（有智慧建议卡片区的那一页）")
        return
    raise UiError(f"没能回到桌面首页，当前窗口 {dev.focus()!r}")


def ensure_home_before_confirm(dev: Device, r: Runner) -> None:
    """卡片触发后的收口：确保停在桌面首页，再交给前端确认。

    所有场景在 r.confirm() 之前都调它。回不去只记日志不抛错——
    有的卡片在锁屏/通知栏，回不到首页不该把整条流程判失败。
    """
    try:
        goto_launcher_home(dev, r)
    except UiError as exc:
        r.log(f"回到桌面首页失败（不影响本次确认）：{exc}")


def disconnect_network(dev: Device, r: Runner, settle: float = 5.0) -> None:
    """断网：Wi-Fi + 移动数据一起关掉，再 ping 确认真的断了。

    时间管理三张卡片按测试说明第一步就要断网：卡片靠本地时间 + 本地闹钟
    判定，联网反而会引入「在线时长」这类额外条件，把触发结果搞脏。
    """
    r.step("第一步：断开网络")
    dev.shell("svc wifi disable")
    dev.shell("svc data disable")
    time.sleep(settle)
    offline = False
    for _ in range(10):
        r.check()
        out = dev.shell("ping -c 1 -W 1 8.8.8.8")
        if "1 received" not in out and "1 packets received" not in out:
            offline = True
            break
        time.sleep(1)
    if offline:
        r.ok("Wi-Fi 与移动数据已关闭，设备已断网")
    else:
        r.log("警告：ping 仍然通，网络可能没完全断开，继续执行")


def restore_network(dev: Device, r: Runner, settle: float = 5.0) -> None:
    """跑完后把网络开回来，别把设备丢在断网状态。"""
    r.step("恢复网络")
    dev.shell("svc data enable")
    dev.shell("svc wifi enable")
    time.sleep(settle)
    r.ok("Wi-Fi 与移动数据已重新打开")

def _settings_row_tap(dev: Device, labels: tuple[str, ...], settle: float = 0.3,
                      retries: int = 3, expect_rid: str | None = None) -> None:
    """设置页的行：点标题中心即可（+35px 偏移曾点出行下缘导致滚轮不弹）。
    多组文案兼容中英文。设置页刚跳过来时行可能还没渲染完，先轮询几轮 dump
    再点，避免首轮 dump 落空直接报「找不到」。

    expect_rid 不为空时（如 dayWheel/hourWheel）：点击后验证滚轮对话框真的
    弹出来了，没弹自动重点一次——设置页刚跳转、页面动画未稳时点击会被吞。"""
    n = None
    for _ in range(retries):
        nodes = dev.dump()
        n = _find_first_text(nodes, labels)
        if n is not None:
            break
        time.sleep(0.5)
    if n is None:
        raise UiError(f"设置页找不到 {labels} 行（已轮询 {retries} 次 dump）")
    for click_i in range(2):
        x, y = n.center
        dev.log(f"点击设置行「{n.text}」({x},{y})" + ("（重试）" if click_i else ""))
        dev.tap(x, y)
        if expect_rid is None:
            time.sleep(settle)
            return
        deadline = time.time() + 3.5
        while time.time() < deadline:
            if dev.find_opt(nodes=dev.dump(), rid=expect_rid) is not None:
                return
            time.sleep(0.5)
        dev.log(f"{expect_rid} 未弹出，{'再点一次' if click_i == 0 else '放弃'}")
    raise UiError(f"点击 {labels} 行两次后 {expect_rid} 仍未弹出")


def _auto_time_row(dev: Device, nodes: list[Node]) -> Node | None:
    """在设置页里找「自动时间」那一行的标题节点，兼容中英文文案。"""
    n = _find_first_text(nodes, AUTO_TIME_LABELS)
    if n is not None:
        return n
    for nd in nodes:
        t = nd.text.lower()
        if "auto" in t and ("time" in t or "date" in t):
            return nd
    for nd in nodes:
        if "自动" in nd.text and ("时间" in nd.text or "日期" in nd.text):
            return nd
    return None


def _switch_on_row(dev: Device, label: Node, nodes: list[Node]) -> Node:
    """找到与某个标题同一行的 Switch（rid 在页面里会重复，只能按 y 就近匹配）。"""
    ly = label.center[1]
    cands = [n for n in nodes if n.cls.endswith("Switch") or n.cls.endswith("CheckBox")]
    if not cands:
        raise UiError(f"「{label.text}」行未找到开关控件")
    return min(cands, key=lambda n: abs(n.center[1] - ly))


def _disable_auto_time(dev: Device, r: Runner) -> None:
    """关闭「自动设置时间」。

    优先直接写全局设置（settings put 与拨动开关等价、零界面依赖），写不进去
    再走界面开关兜底。界面查找兼容中英文文案，且不再只等中文「自动」——
    之前英文系统的设置页会因此白等 10s 抛「等待控件超时」。
    """
    if dev.shell("settings get global auto_time").strip() == "0":
        return
    dev.shell("settings put global auto_time 0")
    if dev.shell("settings get global auto_time").strip() == "0":
        r.log("已直接关闭自动时间（settings put global auto_time 0）")
        return
    # 界面兜底：轮询 dump 找自动时间行，每几轮轻滑一次防行在折叠区外
    label = None
    nodes: list[Node] = []
    deadline = time.time() + 12.0
    try_no = 0
    while time.time() < deadline:
        try:
            nodes = dev.dump()
        except UiError:
            nodes = []
        label = _auto_time_row(dev, nodes)
        if label is not None:
            break
        try_no += 1
        if try_no % 3 == 0:
            w, h = dev.screen_size()
            r.log("仍未看到自动时间行，轻滑设置页让行进入可视区…")
            dev.swipe(w // 2, int(h * 0.72), w // 2, int(h * 0.38), 200)
            time.sleep(0.5)
        else:
            time.sleep(0.5)
    if label is None:
        r.shot("设置页")
        raise UiError("设置页找不到「自动时间」行（兼容文案：自动设置时间/自动确定日期和时间/"
                      "Auto-Set Time/Set automatically 等），且 settings put 未能生效，"
                      "请先在手机上手动关闭「自动设置时间」后重试")
    sw = _switch_on_row(dev, label, nodes)
    r.log(f"关闭「{label.text}」自动时间")
    dev.tap_node(sw, 0.5)
    if dev.shell("settings get global auto_time").strip() != "0":
        raise UiError("auto_time 未能置 0，无法手动改日期")


def _month_box(dev: Device, view: list[Node]) -> Node | None:
    """当前可见的日期区控件：月网格优先，其次周条。"""
    return (dev.find_opt(nodes=view, rid="vp_month")
            or dev.find_opt(nodes=view, rid="vp_week"))


def _rtl(dev: Device) -> bool:
    """当前设备界面是不是从右往左（阿拉伯语等）。

    直接读 `settings get system system_locales`，不猜 —— 界面方向跟系统
    语言设置严格一致，而 RTL 下日历的换月滑动方向是**反的**（实测 ar-SA
    下左滑得到上一个月）。读失败按 LTR 处理，宁可多滑几次也不炸。
    """
    try:
        raw = dev.shell("settings get system system_locales").strip()
    except Exception:
        return False
    return lk.is_rtl(raw)


def _swipe_month(dev: Device, r: Runner, box: Node, forward: bool) -> None:
    """在日期区横向滑一页换月，自动处理 RTL 方向翻转。

    实测（X6766 / ar-SA）：
      LTR 左滑 → 下一月；RTL 左滑 → **上一月**。
    所以先把「想往哪个月走」翻译成逻辑方向，再按 RTL 决定手指往哪边划。
    """
    w, _ = dev.screen_size()
    y = box.center[1]
    logical = "left" if forward else "right"       # LTR 下的手指方向
    if _rtl(dev):
        logical = "right" if logical == "left" else "left"
    x1, yy1, x2, yy2 = lk.swipe_points(w, y, logical, half=280)
    dev.swipe(x1, yy1, x2, yy2, 300)
    time.sleep(0.7)


def _flip_week(dev: Device, r: Runner, view: list[Node], target: date,
               shown: str = "") -> None:
    """周条视图（vp_week，无月网格）翻周，直到目标日出现在周条里。

    周条格子 desc 是完整日期（'Wednesday 28 October'），横滑即换一周。
    方向优先按「目标月份 vs 当前显示月份」决定：目标月早 → 向前翻（右滑），
    晚 → 向后翻（左滑），跨过月边界即换月；同月才按周条内日号相对位置。
    """
    wk = dev.find(nodes=view, rid="vp_week")
    nums = []
    for n in view:
        # 阿拉伯语下周条日号是阿拉伯-印度数字（'٢٦ أكتوبر'），
        # 直接用 \d 抓不到，先归一化成 ASCII 再解析。
        m = re.search(r"\d{1,2}", lk.to_ascii_digits(n.desc or ""))
        if m and wk.bounds[0] <= n.center[0] <= wk.bounds[2] \
                and wk.bounds[1] <= n.center[1] <= wk.bounds[3]:
            nums.append(int(m.group()))
    lo, hi = (min(nums), max(nums)) if nums else (0, 0)
    cur_idx = month_title_index(shown)
    if cur_idx and cur_idx != target.month:
        nxt = -1 if target.month < cur_idx else 1      # 跨月优先
    elif nums:
        # 同月按日号。注意跨月周条（如 26-31 + 1）的 min/max 会覆盖整月，
        # 不能直接拿 lo/hi 区间判断，要用「去除 1 后的真实周范围」。
        big = max(x for x in nums if x != 1) if any(x != 1 for x in nums) else 31
        small = min(x for x in nums if x != 1) if any(x != 1 for x in nums) else 1
        if lo == 1 and hi >= 28:                 # 跨月周条：按真实周范围比日号
            nxt = -1 if target.day < small else (1 if target.day > big else 1)
        else:
            nxt = -1 if target.day < lo else (1 if target.day > hi else 1)
    else:
        nxt = 1
    r.log(f"周条范围 {lo}-{hi}（{shown or '?'}），目标 {target.month}月{target.day}日，"
          f"向{'后' if nxt > 0 else '前'}翻周")
    _swipe_month(dev, r, wk, forward=nxt > 0)


def _ensure_calendar_month(dev: Device, r: Runner, target: date,
                           nodes: list[Node] | None = None) -> list[Node]:
    """确保日历停在 target 所在月份，并返回命中时的控件树。

    打开日历就已经是「能直接点日期」的视图，不需要先点什么「月视图」按钮，
    也不需要进「AI 课程表」——换月直接在日期区左右滑动即可（实测：左滑下一月、
    右滑上一月）。所以这里只做两件事：
      1. 清掉挡路的弹窗 / 事件详情页；
      2. 月份不对就在日期区横向滑，月份对了就返回（日号对不上的兜底交给上层）。
    年视图（dateTitle 只有年份）才需要点一下月份格子下钻。
    """
    descs = date_cell_descs(target)
    title_rid = "dateTitle"
    moved = 0
    guard = 0
    no_title = 0
    # 网格月视图一次滑动 = 一个月；周条视图一次滑动 = 一周（约 4~5 周才跨一个月）。
    # 先用当前控件树判断是不是网格，决定「最多滑几次」的预算。
    first = nodes if nodes is not None else dev.dump()
    nodes = first
    max_moves = 24 if dev.find_opt(nodes=first, rid="vp_month") is not None else 140
    while moved < max_moves and guard < max_moves + 20:
        guard += 1
        view = nodes if nodes is not None else dev.dump()
        nodes = None
        # 课程表子页：只按返回键退出，绝不点击任何东西
        if on_timetable(view):
            r.log("停在「AI 课程表」子页，按返回键退出（不会去点它）")
            dev.key(KEY_BACK)
            time.sleep(0.8)
            continue
        if any(dev.find_opt(nodes=view, desc=d) for d in descs):
            return view
        # 事件详情页没有 dateTitle，一直「关弹窗」是空转，按返回键退出。
        # 两种布局：普通事件带 btn_more，重要日详情只有 toolbar_title='Event Info'。
        if dev.find_opt(nodes=view, rid="btn_more") is not None and \
                dev.find_opt(nodes=view, rid="qv_title") is None:
            r.log("停在事件详情页，按返回键回到日历")
            dev.key(KEY_BACK)
            time.sleep(0.7)
            continue
        det = [n for n in view
               if n.rid.endswith("toolbar_title") and (n.text or "").lower() == "event info"]
        if det:
            r.log("停在重要日详情页，按返回键回到日历")
            dev.key(KEY_BACK)
            time.sleep(0.7)
            continue

        title = dev.find_opt(nodes=view, rid=title_rid)
        shown = (title.text or "").strip() if title else ""
        if not shown:
            # 独立计数：以前这个分支只 continue 不涨 moved，会把 guard 预算吃光
            # 然后空转上百次（周条设备预算 140+20），失败信息还只说「滑了 0 次」。
            no_title += 1
            if no_title > 6:
                raise UiError(
                    f"日历里一直看不到月份标题（试了 {no_title} 次），当前窗口是 "
                    f"{dev.focus() or '未知'}、控件 {len(view)} 个。"
                    f" 请手动切到日历月视图后重试。")
            r.log(f"没看到月份标题（第 {no_title} 次，可能被弹窗遮挡），尝试关闭弹窗")
            view = _dismiss_popups(dev, r, view)
            if not view:
                time.sleep(0.6)
                view = dev.dump()
            continue

        year, month = month_title_parts(shown)
        box = _month_box(dev, view)

        # 年视图：标题只有年份，点目标月份格子下钻到月视图
        if month is None and box is None:
            yr = year if year else target.year
            cell = None
            for c in (f"{yr}年{target.month}月", f"{target.month}月",
                      lk.MONTHS_AR[target.month - 1],
                      lk.MONTHS_EN_ABBR[target.month - 1],
                      lk.MONTHS_EN[target.month - 1]):
                cell = dev.find_opt(nodes=view, desc=c)
                if cell:
                    break
            if cell is None:
                raise UiError(f"日历视图无法识别（dateTitle={shown!r}），请手动切到月视图后重试")
            r.log(f"日历停在年视图（{yr}），点 {target.month} 月格子进入月视图")
            dev.tap_node(cell, 1.0)
            continue

        if box is None:
            raise UiError(f"日历里找不到日期区（dateTitle={shown!r}），请手动切到月视图后重试")

        # 月份已经对了：网格视图直接返回（日号兜底交给上层），周条视图继续翻周
        if month == target.month and (year is None or year == target.year):
            if dev.find_opt(nodes=view, rid="vp_month") is not None:
                return view
            _flip_week(dev, r, view, target, shown)
            moved += 1
            continue

        nxt = 1
        if month is not None:
            delta = (target.year - (year if year else target.year)) * 12 + (target.month - month)
            nxt = 1 if delta > 0 else -1
        has_grid = dev.find_opt(nodes=view, rid="vp_month") is not None
        if not has_grid:
            # 周条视图：滑一格只换一周，直接复用 _flip_week 的方向判断
            _flip_week(dev, r, view, target, shown)
            moved += 1
            continue
        r.log(f"当前显示 {shown}，目标 {target.month} 月，向{'后' if nxt > 0 else '前'}滑一页")
        _swipe_month(dev, r, box, forward=nxt > 0)
        moved += 1
    raise UiError(f"滑了 {moved} 次仍未找到日期 {descs}")


def _edit_in_form(nodes: list[Node]) -> Node | None:
    return next((n for n in nodes if n.cls.endswith("EditText")), None)


# 「重复」下拉里「每年」的三种语言写法
_REPEAT_YEARLY_LABELS = ("每年", "Every year", "Every Year", "Yearly",
                         "Repeat yearly", "Repeat every year",
                         "كل عام", "سنويًا", "سنويا")
# 普通日程表单独有的时间行文案（三语）。出现它说明还没切到「重要日」。
_SCHEDULE_TIME_LABELS = ("Start Time", "开始时间", "End Time", "结束时间",
                         "وقت البدء", "وقت الانتهاء", "بدء الوقت", "وقت النهاية")
# 「重要日」表单里姓名框的占位文案（三语 + 小写形式）
_IMPORTANT_PLACEHOLDERS = ("my important day", "我的重要日", "my important date",
                           "يومي المهم", "يوم مهم", "حدثي مهم")


def _type_icon_in_form(nodes: list[Node], edit: Node) -> Node | None:
    """姓名输入框右侧的私有区字形（类型下拉按钮）。

    阿拉伯语（RTL）界面下这个图标跑到输入框**左边**去了（实测
    `center=(124, 790)`，输入框在 `(668, 791)`），所以不能只认右边：
    先按垂直对齐挑出同一行的 PUA 字形，优先取右侧的，没有就取左侧的。
    """
    same_row = [n for n in nodes
                if n.cls.endswith("TextView") and PUA_RE.fullmatch(n.text or "")
                and abs(n.center[1] - edit.center[1]) < 90]
    if not same_row:
        return None
    right = [n for n in same_row if n.center[0] > edit.bounds[2] - 12]
    if right:
        return right[0]
    left = [n for n in same_row if n.center[0] < edit.bounds[0] + 12]
    return left[0] if left else None


def _important_day_form_ready(nodes: list[Node]) -> bool:
    """判断当前是否已经切到「重要日」表单（而不是普通日程表单）。

    两处判据都要三语齐全：切到 ar-SA 时普通日程表单的「开始时间」变成
    `وقت البدء`、「日期」变成 `التاريخ`，只认中英文会把已经切好的表单
    判成「还没切过去」，连点三次后直接抛错（实际踩过）。
    """
    if _find_first_text(nodes, _SCHEDULE_TIME_LABELS) is not None:
        return False
    edit = _edit_in_form(nodes)
    if edit is None:
        return False
    if _find_first_text(nodes, DATE_LABELS) is not None:
        return True
    if _type_icon_in_form(nodes, edit) is not None:
        return True
    ph = (edit.text or "").strip().lower()
    return ph in _IMPORTANT_PLACEHOLDERS


def _switch_important_day(dev: Device, r: Runner) -> list[Node]:
    """点「重要日」标签并确认表单真的切过去了。

    第一次点经常被新建页入场动画/键盘弹窗吞掉；原实现用 _poll_text 看到
    tab 文案就误判成功，随后把姓名框当类型下拉点，触发键盘条款弹窗。
    """
    for attempt in range(1, 4):
        nodes = dev.dump()
        tab = dev.find_opt(nodes=nodes, rid="tab_important_day")
        if tab is None:
            tab = dev.find_opt(nodes=nodes, rid="text_important_day")
        if tab is None:
            tab = _find_first_text(nodes, lk.labels("important_day"))
        if tab is not None:
            r.log(f"点「重要日」标签（第 {attempt} 次） {tab.center}")
            dev.tap_node(tab, 0.8)
        time.sleep(0.9)
        nodes = _dismiss_popups(dev, r)
        if _important_day_form_ready(nodes):
            return nodes
        r.log("还是普通日程表单，再点一次「重要日」标签")
    raise UiError("点「重要日」标签 3 次后仍是日程表单（Date 行/类型按钮未出现）")


def _open_type_dropdown(dev: Device, r: Runner) -> None:
    """点姓名输入框右侧的类型下拉图标（不再依赖 rid=title / 标题行右缘）。"""
    nodes = dev.dump()
    edit = _edit_in_form(nodes)
    if edit is None:
        raise UiError("重要日表单里找不到姓名输入框，无法打开类型下拉")
    icon = _type_icon_in_form(nodes, edit)
    if icon is not None:
        r.log(f"点类型下拉图标 {icon.center}")
        dev.tap_node(icon, 0.5)
        return
    w, _ = dev.screen_size()
    x = (edit.bounds[2] + w) // 2
    y = edit.center[1]
    r.log(f"未识别类型图标字形，点输入框右侧空白 ({x},{y})")
    dev.tap(x, y)
    time.sleep(0.5)


def _confirm_dialog(dev: Device, nodes: list[Node]) -> None:
    """在当前控件树里找「确定/OK」并点掉，然后等对话框真正消失。"""
    btn = dev.find_opt(nodes=nodes, rid="btn_positive")
    if btn is None:
        btn = _find_first_text(nodes, OK_LABELS)
    if btn is None:
        # 兜底：正按钮通常位于对话框右下角
        dev.log("未按 btn_positive/常见文案找到确认按钮，改点右下角按钮兜底")
        btns = [n for n in nodes if n.cls.split(".")[-1] == "Button"]
        if not btns:
            raise UiError("对话框里找不到任何按钮")
        btn = max(btns, key=lambda n: n.bounds[2] + n.bounds[3])
    dev.tap_node(btn, 0.3)
    dev.wait_gone(rid="btn_positive", settle=0.4)


# ─────────────────────────────────────────────────────────────
# 以下为可复用的分段动作：生日策划案场景与生日祝福场景共用。
# 每个动作自己发 r.step()，保持各自的步骤计数。
# ─────────────────────────────────────────────────────────────


def _close_shade(dev: Device) -> None:
    """收起通知栏。解锁上滑手势有时会把状态栏拉下来，残留的通知栏
    （NotificationShade）会挡住后续 wait_focus。焦点不在通知栏则直接跳过。"""
    for _ in range(2):
        focus, _ = dev.window_info()
        if "notification" not in focus.lower():
            return
        dev.key(KEY_BACK)
        time.sleep(0.4)
        focus, _ = dev.window_info()
        if "notification" not in focus.lower():
            return
        w, h = dev.screen_size()
        dev.swipe(w // 2, int(h * 0.97), w // 2, int(h * 0.15), 250)
        time.sleep(0.5)


def _focus_or_close_shade(dev: Device, needle: str, timeout: float = 15.0) -> str:
    """wait_focus 的兜底版：等待窗口期间若焦点变成通知栏，先收起再继续等。"""
    deadline = time.time() + timeout
    while True:
        focus = dev.focus()
        if needle.lower() in focus.lower():
            return focus
        if "popupwindow" in focus.lower():
            dev.log("检测到遮挡 PopupWindow，按返回关闭")
            dev.key(KEY_BACK)
            time.sleep(0.4)
            continue
        if "notification" in focus.lower():
            _close_shade(dev)
            time.sleep(0.3)
            continue
        if time.time() >= deadline:
            raise UiError(f"等待窗口 {needle!r} 超时({timeout}s)，当前 {focus!r}")
        time.sleep(0.25)


def _prepare(dev: Device, r: Runner) -> tuple[int, int]:
    """唤醒屏幕、保持常亮并自动上滑解锁，返回屏幕尺寸。"""
    r.step("准备：唤醒屏幕并自动解锁")
    _unlock_with_retries(dev, r, unlock_retries=3, wake=True)
    _close_shade(dev)   # 解锁手势偶尔拉下通知栏，先收掉
    w, h = dev.screen_size()
    r.ok(f"{dev.serial} {w}x{h}")
    return w, h


def _date_cell_in_grid_by_desc(nodes: list[Node], target: date) -> Node | None:
    """按「月份词 + 精确日号」在月网格/周条范围内兜底匹配 desc。

    针对日历 App 切成英文后的格式 "Monday, November 9"、以及阿拉伯语下的
    "الاثنين، ١٦ نوفمبر"；不扫整页，避免命中网格下方 "Mon, Nov 9, today"
    这类日期头部。
    """
    vp = next((n for n in nodes if n.rid in ("vp_month", "vp_week")), None)
    if vp is None:
        return None
    x0, y0, x1, y1 = vp.bounds
    terms = [
        f"{target.month}月",
        lk.MONTHS_AR[target.month - 1],
        lk.MONTHS_EN[target.month - 1].lower(),
        lk.MONTHS_EN_ABBR[target.month - 1].lower(),
    ]
    # 日号可能是阿拉伯-印度数字，统一用 ASCII 归一化后的文本比
    day_re = re.compile(rf"(?<!\d){target.day}(?!\d)")
    for n in nodes:
        if not n.desc:
            continue
        cx, cy = n.center
        if not (x0 - 4 <= cx <= x1 + 4 and y0 - 4 <= cy <= y1 + 4):
            continue
        d = lk.to_ascii_digits(n.desc).lower()
        if day_re.search(d) and any(t.lower() in d for t in terms):
            return n
    return None


def _day_cell_by_text(nodes: list[Node], target: date) -> Node | None:
    """desc 匹配不上时兜底：找文本等于 day 数字的格子。

    月视图里日号数字在语言无关，跨月灰格只含 1~7 附近的小数字；
    若仍有多个候选（如目标就是小数字），按目标日所在的期望行位置选。
    阿拉伯语下日号文本可能是阿拉伯-印度数字，两种写法都比。
    """
    wanted = {str(target.day),
              "".join(lk._ARABIC_INDIC[int(c)] for c in str(target.day))}
    cands = [n for n in nodes
             if n.cls.endswith("TextView") and (n.text or "").strip() in wanted]
    if len(cands) == 1:
        return cands[0]
    if not cands:
        return None
    vp = next((n for n in nodes if n.rid == "vp_month"), None)
    if vp is None:
        return cands[0]
    first = date(target.year, target.month, 1)
    row = (first.weekday() + target.day - 1) // 7
    _, top, _, bot = vp.bounds
    row_h = (bot - top) / 6
    return min(cands, key=lambda n: abs(n.center[1] - (top + (row + 0.5) * row_h)))


def _day_cell(dev: Device, nodes: list[Node], target: date) -> Node | None:
    """在已收敛到目标月份的视图里定位日期格子（desc → 日号文本逐级兜底）。

    返回 None 时由调用方决定；当前实现覆盖：
      中文月网格格子（'10月23日星期五'）、英文周条/周视图格子（'Friday 23 October'）、
      以及无 desc 网格里 text 为日号的 TextView（_day_cell_by_text）。
    """
    for d in date_cell_descs(target):
        cell = dev.find_opt(nodes=nodes, desc=d)
        if cell:
            return cell
    cell = _date_cell_in_grid_by_desc(nodes, target)
    if cell:
        return cell
    return _day_cell_by_text(nodes, target)


def _select_calendar_day(dev: Device, r: Runner, target: date, note: str,
                         expect: str | None = None) -> None:
    """打开日历，收敛到 target 所在月份并点中该日。

    note 用在校验日志里，expect 是 tv_date 应包含的文案（默认同 note）。
    """
    r.step(f"打开日历并选中 {target.month}月{target.day}日（{note}）")
    # 先强停再启动：避免上次残留的「新建事件/类型下拉/事件详情」把月视图挡住。
    # 只影响 seed 流程；极速更新 fixture 不会打开日历。
    dev.shell(f"am force-stop {CALENDAR_PKG}")
    time.sleep(0.3)
    # 显式组件启动日历月视图，跳过 AI 课程表入口，也不走会被「Open With」截胡的 VIEW
    launch_calendar(dev)
    _focus_or_close_shade(dev, "calendar")
    r.log(f"启动后当前窗口：{dev.focus()}")
    nodes = None
    for attempt in range(6):
        try:
            nodes = dev.wait_nodes(timeout=8, settle=0.8, rid="dateTitle")
            break
        except UiError:
            # 可能残留在事件详情页或别的子页，按返回键回到日历
            r.log(f"没看到日历标题（第 {attempt + 1} 次），当前窗口 {dev.focus()}，按返回键")
            dev.key(KEY_BACK)
            time.sleep(0.7)
    nodes = _dismiss_popups(dev, r, nodes)
    nodes = _ensure_calendar_month(dev, r, target, nodes)
    cell = _day_cell(dev, nodes, target)
    if cell is None:
        raise UiError(f"月视图里找不到日期 {target}（content-desc、日号文本与周条格子都试过）")
    dev.tap_node(cell, 0.3)
    tv = dev.wait_node(timeout=8, settle=0.6, rid="tv_date")
    if not date_text_matches(tv.text or "", target):
        want = expect if expect is not None else note
        r.log(f"警告：tv_date 未显示 {want!r}，实际 {tv.text!r}")
    r.ok(tv.text)
    r.shot("选中日期")


def _add_important_event(dev: Device, r: Runner, name: str, *,
                         ev_value: str, type_cn: str, type_en: str,
                         placeholder: str,
                         type_labels: tuple[str, ...] | None = None) -> None:
    """在日历当前选中的日期上新建一个「重要日」事件（生日/纪念日）并保存。"""
    r.step("点击「添加」进入新建面板")
    dev.tap_by(rid="fab_new_layout", settle=0.4)
    nodes = dev.wait_nodes(timeout=15, settle=0.8, rid="tab_important_day")
    r.ok(dev.focus())

    r.step("切换到「重要日」标签")
    nodes = _switch_important_day(dev, r)
    r.ok("重要日表单已就绪")

    if ev_value == CAL_TYPE_NONE:
        # 重要日提醒卡片：不选类型，直接用默认「重要日」，只填名称
        r.step("重要日提醒：跳过类型下拉，直接填名称")
        edit = dev.wait_node(timeout=8, settle=0.6, cls="EditText")
        r.ok("使用默认类型")
    else:
        r.step(f"打开类型下拉并勾选「{type_cn}」")
        _open_type_dropdown(dev, r)
        # 阿拉伯语界面下下拉项是「عيد الميلاد」，只认中英文会找不到（实测踩过）
        wanted = tuple(type_labels) if type_labels else (type_cn, type_en)
        nodes = dev.wait_nodes(timeout=8, settle=0.6, rid="tv_choice_text")
        opt = _find_first_text(nodes, wanted)
        if opt is None:
            raise UiError(f"类型下拉里找不到 {type_cn}/{type_en}（候选 {wanted}）")
        dev.tap_node(opt, 0.4)
        edit = dev.wait_node(timeout=8, settle=0.6, cls="EditText")
        if edit.text not in (placeholder, "输入姓名", "My important day", "My important date",
                             "Enter name", "Name", "يومي المهم", "حدثي", "حدثي مهم"):
            r.log(f"警告：勾选后输入框占位符为 {edit.text!r}，预期 {placeholder!r}")
        r.ok(f"已选{type_cn}")

    r.step(f"输入名称 {name}")
    dev.tap_node(edit, 0.5)
    time.sleep(0.4)
    # 首次打开输入法可能弹 Emoji Keyboard 的 Terms and Conditions（Agree And Continue），
    # 不关掉的话 input text 会被弹窗吞掉，名称一直是空。
    _dismiss_keyboard_terms(dev, r)
    dev.input_text(name)
    time.sleep(0.3)
    # 关键：用 ENTER 提交输入法 composition；ESC 会把拼音/输入取消，导致输入框为空
    dev.key(66)
    time.sleep(0.5)
    got = dev.find(cls="EditText").text
    if not got.strip():
        r.log("名称输入框为空，重试一次（点击输入框 → input text → ENTER）")
        dev.tap_node(edit, 0.4)
        time.sleep(0.3)
        _dismiss_keyboard_terms(dev, r)
        dev.input_text(name)
        dev.key(66)
        time.sleep(0.5)
        got = dev.find(cls="EditText").text
    if not got.strip():
        raise UiError(f"名称写入失败：输入框为空，期望写入 {name!r}")
    if got != name:
        # 输入法自动纠正可能导致内容与期望不一致（如 Bday→B答应），
        # 只要输入框里有文字就不阻断，仅告警
        r.log(f"警告：输入框内容 {got!r} 与期望 {name!r} 不一致，继续执行")
    r.ok(got)

    r.step("校验提醒规则并保存")
    nodes = dev.dump()
    rep = _find_first_text(nodes, _REPEAT_YEARLY_LABELS)
    if rep is None and ev_value not in (CAL_TYPE_EXAM, CAL_TYPE_PERFORMANCE, CAL_TYPE_NONE):
        raise UiError(f"「重复」未自动变为『每年』，{type_cn} 类型可能没选上")
    if rep is None:
        # 考试/观演日/不选类型实测默认重复为 Never（不每年），属设备真实行为，不拦截
        r.log(f"{type_cn} 类型重复行为 {ev_value!r}（默认不每年），跳过『每年』校验")
    rem_txt = ""
    for n in nodes:
        if n.short_id == "lil_subtitle" and ("天前" in n.text
                                             or "days before" in n.text.lower()
                                             or "يوم" in n.text
                                             or "قبل" in n.text):
            rem_txt = n.text
    rem_low = rem_txt.lower()
    if not (f"{REMIND_DAYS_BEFORE} 天前" in rem_txt
            or f"{REMIND_DAYS_BEFORE} days before" in rem_low
            or f"{REMIND_DAYS_BEFORE} days prior" in rem_low
            or lk.to_ascii_digits(rem_txt).startswith(f"{REMIND_DAYS_BEFORE}")
            or f"{REMIND_DAYS_BEFORE}" in lk.to_ascii_digits(rem_txt)):
        r.log(f"警告：提醒时间未包含『{REMIND_DAYS_BEFORE} 天前』，实际 {rem_txt!r}")
    r.log(f"重复=每年，提醒时间={rem_txt!r}")
    save = dev.find_opt(nodes=nodes, rid="img_right")
    if save is None:
        # X6878 英文界面保存图标无 rid：按标题栏最右图标兜底
        top = [n for n in nodes if n.bounds[1] >= 340 and n.bounds[3] <= 520
               and n.bounds[0] > 900
               and n.cls.split(".")[-1] in ("TextView", "ImageView", "View")]
        if not top:
            raise UiError("找不到保存按钮（img_right 或右上角图标）")
        save = max(top, key=lambda n: n.bounds[2])
        r.log(f"未识别 img_right，改点右上角图标 ({save.center[0]:.0f},{save.center[1]:.0f})")
    dev.tap_node(save, 0.4)   # 复用上面这份 dump
    dev.wait_nodes(timeout=15, settle=0.8, rid="fab_new_layout")
    r.ok("事件已保存，已回到日历主页")
    r.shot("保存后")


def _poll_text(dev: Device, labels: tuple[str, ...], timeout: float = 10) -> Node:
    """轮询 dump 直到命中 labels 任一文案（中英适配），返回该节点。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        n = _find_first_text(dev.dump(), labels)
        if n is not None:
            return n
        time.sleep(0.3)
    raise UiError(f"等待文本 {labels} 超时")


def _ensure_datetime_page(dev: Device, r: Runner) -> None:
    """确保设置界面停在「日期与时间」页，再交给 _settings_row_tap 点具体行。

    Transsion 上显式启动 DateTimeSettingsActivity 也时常被路由回设置主页，
    这里逐级下钻：主页 → System/系统 → Date & time/日期和时间 → 出现 Date 行。
    """
    for _ in range(5):
        nodes = dev.dump()
        # 精确匹配 Date/日期 行才算是日期时间页（避免 System 子页里
        # 「Date & time」入口行被包含匹配误判为已就绪）
        if any(n.text in DATE_LABELS for n in nodes):
            return
        ent = _find_first_text(nodes, ("Date & time", "Date and time",
                                       "日期和时间", "日期与时间"))
        if ent is not None:
            r.log("点「Date & time」进入日期时间页")
            dev.tap_node(ent, 0.8)
            continue
        # System 行必须精确匹配：包含匹配会把「System App Update」误判为 System
        sysrow = next((n for n in nodes if n.text == "System"), None)
        if sysrow is None:
            sysrow = next((n for n in nodes if n.text == "系统"), None)
        if sysrow is not None:
            r.log("停在设置主页，点「System」进入")
            dev.tap_node(sysrow, 0.8)
            continue
        # 无关子页（如 My Phone 关于页）：先返回键回设置主页再下钻，
        # 否则会空转 5 次直接报错
        r.log("当前不在设置主页/日期时间页，按返回键回上一层")
        dev.key(KEY_BACK)
        time.sleep(0.7)
    raise UiError("设置页找不到日期行，也未找到 System / Date & time 入口")


def _to_hm(hour, minute) -> tuple[int, int]:
    """把 (hour, minute) 归一化成整数。外部脚本可能传 "9:30" 这种整串，
    也可能传 "9"/"30"；"9:30" 时忽略 minute 参数、直接拆串。"""
    if isinstance(hour, str) and ":" in hour:
        h, m = hour.split(":", 1)
        return int(h), int(m)
    return int(hour), int(minute)


def set_system_datetime(dev: Device, r: Runner, target: date,
                        hour: int, minute: int) -> str:
    """关闭自动时间，把系统日期设为 target、时间设为 hour:minute。

    优先走极速路径：shell 有 SET_TIME 时直接 `cmd alarm set-time`，约几十毫秒；
    不行再回退到设置页滚轮（兼容老设备）。返回日期标题。

    hour / minute 统一转 int：调用方可能传字符串（Web 端固定传数字，但命令行
    或外部脚本传 "9:30" 时会被拆成 "9"/"30"），一旦是字符串，下面 f-string 里的
    :02d 就会抛 ValueError: Unknown format code 'd' for object of type 'str'。
    """
    hour, minute = _to_hm(hour, minute)
    r.step(f"系统日期改为 {target}、时间 {hour:02d}:{minute:02d}")
    title = f"{target.year}年{target.month}月{target.day}日"
    if fast_clock.set_datetime(dev, target, hour, minute, log=r.log):
        r.ok(f"{title} {hour:02d}:{minute:02d}（极速直设）")
        return title

    r.log("直设系统时间不可用，回退到设置界面")
    # 先回桌面清掉可能残留的设置任务栈：Transsion 上 DATE_SETTINGS 会被
    # 已存在的 Settings 实例截胡（intent 只把旧页面带到前台），
    # 必须显式指定 DateTimeSettingsActivity 组件再启动。
    dev.key(KEY_HOME)
    time.sleep(0.3)
    # 显式组件名里的 $ 会被设备端 shell 当变量展开成空（DateTimeSettingsActivity
    # 丢失 → 只启动到 Settings 主页），必须转义成 \$ 让 am 收到完整组件名。
    cmp_esc = DATE_SETTINGS_CMP.replace("$", "\\$")
    dev.shell(f"am start -f 0x10000000 -n {cmp_esc}")
    _focus_or_close_shade(dev, "settings")
    if dev.shell("settings get global auto_time").strip() != "0":
        _disable_auto_time(dev, r)

    _ensure_datetime_page(dev, r)
    _settings_row_tap(dev, DATE_LABELS, expect_rid="dayWheel")
    nodes = dev.wait_nodes(timeout=10, settle=0.8, rid="dayWheel")
    # 三个滚轮一次 dump 读全部、批量收敛：比逐个 set_wheel 省一大半 dump
    nodes = dev.set_wheels({"yearWheel": target.year,
                            "monthWheel": target.month,
                            "dayWheel": target.day}, nodes=nodes)
    title = dev.find(nodes=nodes, rid="text_title")   # 复用收敛后的树，不额外 dump
    if not _title_matches_date(title.text, target):
        raise UiError(f"日期滚轮未到位：标题 {title.text!r}，目标 {target}")
    _confirm_dialog(dev, nodes)
    r.log(f"日期已设为 {title.text}")

    _settings_row_tap(dev, TIME_LABELS, expect_rid="hourWheel")
    nodes = dev.wait_nodes(timeout=10, settle=0.8, rid="hourWheel")
    nodes = dev.set_wheels({"hourWheel": hour, "minWheel": minute}, nodes=nodes)
    ttitle = dev.find(nodes=nodes, rid="text_title").text
    if not _time_matches_title(ttitle, hour, minute):
        raise UiError(f"时间滚轮未到位：标题 {ttitle!r}，目标 {hour:02d}:{minute:02d}")
    _confirm_dialog(dev, nodes)
    r.ok(f"{title.text} {ttitle}")
    return title.text


def _second_off_on_unlock(dev: Device, r: Runner, off_sec: float,
                          unlock_retries: int = 3) -> str:
    """「马上息屏 -> 马上亮屏 -> 上滑解锁」这一步，追星日卡片专用。

    追星日（Show Day）卡片第一次亮屏解锁后并不会立刻出现在桌面上，
    要再走一次息屏/亮屏才会渲染出来。所以这里补一步：
      息屏 off_sec 秒（默认 2 秒，就是「马上」）-> 亮屏 -> 上滑解锁 -> 回首页。
    返回最后一次解锁后的设备时间。
    """
    r.step(f"再次息屏 {off_sec:g} 秒后马上亮屏，上滑解锁")
    dev.stayon(False)
    time.sleep(0.3)
    dev.key(223)                         # KEYCODE_SLEEP
    if not _wait_screen_on(dev, False, timeout=1.2):
        r.log("警告：第二次息屏后屏幕仍为亮起状态")
    # 「马上亮屏」：等够 off_sec 就立刻唤醒，不做多余的停留
    remain = off_sec
    while remain > 0:
        r.check()
        step = min(0.2, remain)
        time.sleep(step)
        remain -= step
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    dev.stayon(True)
    time.sleep(1.5)                      # 给锁屏一次渲染机会（不设 3.5s，保持「马上」）
    r.shot("第二次亮屏")
    _unlock_with_retries(dev, r, unlock_retries)
    dev.stayon(True)
    time.sleep(0.8)
    ensure_home_before_confirm(dev, r)
    r.shot("第二次解锁后")
    now_hms = dev.shell("date '+%H:%M:%S'").strip()
    r.ok(f"设备时间 {now_hms}")
    return now_hms


def screen_off_wait_unlock(dev: Device, r: Runner, wait_sec: int,
                           unlock_retries: int = 3,
                           desktop_wait_sec: int = 0,
                           second_off_sec: float = 0.0) -> str:
    """息屏等待 wait_sec 秒，再亮屏上滑解锁。返回解锁后的设备时间字符串。

    desktop_wait_sec > 0 时走纪念日类卡片的二次触发流程：
      息屏等待 -> 亮屏第一次解锁 -> 回桌面等 desktop_wait_sec 秒
      -> 再息屏（停留数秒）-> 亮屏等几秒让锁屏卡片渲染出来 -> 解锁。

    second_off_sec > 0 时（追星日卡片用）额外加一次「马上息屏 -> 马上亮屏」：
      前面完全照旧（含 desktop_wait_sec 那套），最后再补一步
      息屏 second_off_sec 秒 -> 亮屏 -> 上滑解锁。
    """
    r.step(f"息屏等待 {wait_sec} 秒后亮屏上滑解锁")
    dev.key(KEY_HOME)
    time.sleep(0.5)
    dev.stayon(False)
    time.sleep(0.3)
    dev.key(223)                         # KEYCODE_SLEEP，比 POWER 更确定
    if not _wait_screen_on(dev, False, timeout=1.2):
        r.log("警告：息屏后屏幕仍为亮起状态")
    for remain in range(wait_sec, 0, -1):
        r.check()
        if remain % 5 == 0 or remain == 1:
            r.tick(remain)
        time.sleep(1)
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    dev.stayon(True)                     # 先保持亮屏，让用户/截图能看清锁屏卡片
    if desktop_wait_sec <= 0:
        # 单次流程：先截锁屏、确认，再解锁；这样卡片不会被滑走
        time.sleep(3.5)                  # AOD → 锁屏动画
        now_hms = dev.shell("date '+%H:%M:%S'").strip()
        # 先拍锁屏卡片作为证据，再自动上滑到桌面，最后才让用户确认卡片
        r.shot("锁屏卡片")
        # 锁屏卡片只在解锁前这一瞬间可见。把当时的控件树文案记进 Runner，
        # 之后自动识别（已回桌面）才有依据判断这张卡到底出来没有。
        r.note_lockscreen(dev)
        _unlock_with_retries(dev, r, unlock_retries)
        dev.stayon(True)
        time.sleep(0.8)
        ensure_home_before_confirm(dev, r)
        r.shot("解锁后")
        # 追星日卡片多一步：亮屏解锁之后马上再息屏、马上再亮屏解锁
        if second_off_sec > 0:
            now_hms = _second_off_on_unlock(dev, r, second_off_sec, unlock_retries)
        r.step("确认卡片是否已触发（已自动解锁到桌面）")
        r.confirm()
        r.ok()
        r.ok(f"设备时间 {now_hms}")
        return now_hms

    # 纪念日类：先解锁回桌面等待，再二次息屏亮屏
    _unlock_with_retries(dev, r, unlock_retries)
    dev.stayon(True)
    now_hms = dev.shell("date '+%H:%M:%S'").strip()
    r.ok(f"设备时间 {now_hms}")

    # ---- 纪念日类卡片二次触发：解锁后回桌面再等，然后息屏亮屏看卡片 ----
    r.step(f"第一次解锁完成，回桌面等待 {desktop_wait_sec} 秒")
    dev.key(KEY_HOME)
    time.sleep(0.5)
    for remain in range(desktop_wait_sec, 0, -1):
        r.check()
        if remain % 5 == 0 or remain == 1:
            r.tick(remain)
        time.sleep(1)
    now_hms = dev.shell("date '+%H:%M:%S'").strip()
    r.ok(f"设备时间 {now_hms}")

    r.step("再次息屏后亮屏，等待锁屏卡片出现")
    dev.stayon(False)
    time.sleep(0.3)
    dev.key(223)
    if not _wait_screen_on(dev, False, timeout=1.2):
        r.log("警告：第二次息屏后屏幕仍为亮起状态")
    time.sleep(3)                       # 息屏停留几秒，给系统刷新锁屏卡片的机会
    dev.key(KEY_WAKEUP)
    _wait_screen_on(dev, True, timeout=3.0)
    dev.stayon(True)
    # 亮屏后要等够 LOCK_RENDER_SEC 秒让锁屏卡片渲染完（AOD→锁屏动画慢），
    # 早截一秒就会拍到还没出卡的空锁屏
    time.sleep(LOCK_RENDER_SEC)
    now_hms = dev.shell("date '+%H:%M:%S'").strip()
    # 同样：先拍锁屏，再自动解锁到桌面，最后确认
    r.shot("锁屏卡片")
    r.note_lockscreen(dev)
    _unlock_with_retries(dev, r, unlock_retries)
    dev.stayon(True)
    time.sleep(0.8)                     # 等桌面渲染完再截，避免截到锁屏残影
    ensure_home_before_confirm(dev, r)
    r.shot("解锁后")
    # 追星日卡片多一步：亮屏解锁之后马上再息屏、马上再亮屏解锁
    if second_off_sec > 0:
        now_hms = _second_off_on_unlock(dev, r, second_off_sec, unlock_retries)
    r.step("确认卡片是否已触发（已自动解锁到桌面）")
    r.confirm()
    r.ok()
    r.ok(f"设备时间 {now_hms}")
    return now_hms


def _shift_months(d: date, n: int) -> date:
    """日期平移 n 个月；超出月份的天数收敛到月末（1/31 +1月 → 2/28 或 2/29）。"""
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, min(d.day, _calendar.monthrange(y, m)[1]))


def run(dev: Device | None = None, emit=None, *, offset_days: int = 4,
        hour: int = 9, minute: int = 30, name: str | None = None,
        wait_sec: int = 60, unlock_retries: int = 3,
        offset_months: int = 0, desktop_wait_sec: int = 0,
        second_off_sec: float = 0,
        ev_value: str = CAL_TYPE_BIRTHDAY, ev_display: str = "生日",
        control: dict | None = None, confirm_fn=None, ask_fn=None) -> dict:
    dev = dev or Device()
    # Web 端固定传数字；命令行/外部脚本可能传 "9"/"30" 甚至 "9:30" 字符串，
    # 这里统一归一化，否则后面 f-string 的 :02d 会抛 Unknown format code 'd'
    hour, minute = _to_hm(hour, minute)
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    today = device_date(dev)
    bday = today + timedelta(days=offset_days)
    # 重新触发：卡片本月已触发过，把目标日期整体平移 n 个月再试
    if offset_months:
        bday = _shift_months(bday, offset_months)
        r.log(f"重新触发：{ev_display}日期平移 +{offset_months} 月 → {bday}")
    sysdate = bday - timedelta(days=REMIND_DAYS_BEFORE)
    name = name or gen_name(today)
    # 策划案卡片的标题也带这个随机名字（「xx·生日 · 3 天后」），
    # 登记给自动识别当判据
    r.card_hint = name
    result = {"device_today": today.isoformat(), "birthday": bday.isoformat(),
              "sysdate": sysdate.isoformat(), "name": name}

    et = _EV_TYPES.get(ev_value, _EV_TYPES[CAL_TYPE_BIRTHDAY])
    fx = fixtures.get(dev, ev_value)
    fx_row = fixtures.get_event(dev, int(fx["event_id"])) if fx else None
    fast_mode = fx_row is not None
    if fast_mode and not fixtures.event_has_type(dev, int(fx_row["_id"]), ev_value):
        r.log(f"fixture #{fx_row['_id']} 已不是「{ev_display}」重要日事件"
              f"（类型标记丢失或被普通事件复用），清除后重新走一次日历 seed")
        fixtures.clear(dev, ev_value)
        fx_row = None
        fast_mode = False

    def _seed_event() -> None:
        """首次运行：走一遍原日历 UI 建一个 fixture 事件。"""
        _select_calendar_day(dev, r, bday, f"今天+{offset_days}", f"{offset_days}天后")
        _add_important_event(dev, r, name, ev_value=ev_value,
                             type_cn=et["cn"], type_en=et["en"], placeholder=et["ph"],
                             type_labels=et.get("labels"))

    if fast_mode:
        r.log(f"极速模式：fixture #{fx_row['_id']} 已登记，跳过解锁/日历准备")
    else:
        _prepare(dev, r)

    created = False
    if fast_mode:
        r.step("极速模式：更新 fixture 事件（不打开日历）")
        if fixtures.update_event(dev, fx_row, name, bday):
            fx = fx_row
            r.ok(f"事件 #{fx_row['_id']} → {name} / {bday}")
        else:
            r.log("fixture 更新失败，回退到 UI 重建（仅这一次）")
            fixtures.clear(dev, ev_value)
            _prepare(dev, r)
            _seed_event()
            fx = fixtures.find_latest(dev, ev_value, name)
            if not fx:
                raise UiError("回退重建 fixture 后仍找不到事件")
            fixtures.register(dev, ev_value, fx)
            created = True
            r.ok(f"已重新登记 fixture #{fx['_id']}")
    else:
        before = fixtures.newest_event_id(dev)
        _seed_event()
        # 新种子事件的标题和计划标题不一定完全一致（输入被截断时更明显），
        # 所以先按「本次新建的、比建库时更新的那条」找，再退回按标题/类型找。
        fx = fixtures.find_by_title(dev, name)
        if fx is None or int(fx["_id"]) <= before:
            fx = fixtures.newest_event(dev, newer_than=before)
        if not fx:
            fx = fixtures.find_latest(dev, ev_value, name)
        if not fx:
            raise UiError("首次创建后仍未在 CalendarProvider 中找到 fixture 事件")
        got_title = (fx.get("title") or "").strip()
        if got_title != name:
            r.log(f"日历里保存的名称是「{got_title}」，与计划名称「{name}」不同，沿用日历里的写法")
        fixtures.register(dev, ev_value, fx)
        created = True
        r.log(f"已登记 fixture #{fx['_id']}，下次开始走极速更新，不再进日历 UI")
        if not fixtures.update_event(dev, fx, name, bday):
            r.log("警告：fixture 首次更新失败，沿用刚创建的 UI 事件")

    result["fixture_event_id"] = int(fx["_id"])
    result["fixture_created"] = created
    set_system_datetime(dev, r, sysdate, hour, minute)

    # 直设时间后不再启动日历/等待焦点；日历只读 Provider，锁屏卡片会自己刷新。
    raw = dev.shell("date '+%Y-%m-%d %H:%M:%S'").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", raw)
    if not m:
        raise UiError(f"无法解析设备时间：{raw!r}")
    cur = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    cur_hour = int(m.group(4))
    if cur != sysdate:
        raise UiError(f"系统日期 {cur} 与预期 {sysdate} 不一致")
    if (bday - cur).days != REMIND_DAYS_BEFORE:
        raise UiError(f"间隔 {(bday - cur).days} 天，应为 {REMIND_DAYS_BEFORE} 天")
    if cur_hour < 8:
        raise UiError(f"当前 {cur_hour} 点，未满足『8点后』的要求")
    result["device_time"] = raw
    r.ok(f"设备时间 {raw}，距{ev_display} {(bday - cur).days} 天")

    result["device_time_after"] = screen_off_wait_unlock(
        dev, r, wait_sec, unlock_retries, desktop_wait_sec=desktop_wait_sec,
        second_off_sec=second_off_sec)
    result["steps"] = r._no
    result["ok"] = True
    result["summary"] = (f"完成。{ev_display} {bday}，系统日期 {sysdate}，名称 {name}。"
                         f"锁屏应出现「{name}·{ev_display} · {REMIND_DAYS_BEFORE} 天后」策划案卡片。")
    return result


def _cli_emit(e: dict) -> None:
    t = e["t"]
    if t == "step":
        if e.get("state") == "start":
            print(f"\n[{e['no']:>2}] {e['title']}", flush=True)
        else:
            detail = e.get("detail", "")
            print(f"      OK {e.get('ms', 0)}ms {detail}", flush=True)
    elif t == "log":
        print(f"      - {e['msg']}", flush=True)
    elif t == "tick":
        print(f"      ... 息屏倒计时 {e['remain']}s  ", end="\r", flush=True)
    elif t == "shot":
        print(f"      [shot] 截图 {e.get('tag', '')}", flush=True)


if __name__ == "__main__":
    import sys

    kwargs = {}
    if len(sys.argv) > 1:
        kwargs["wait_sec"] = int(sys.argv[1])
    try:
        out = run(emit=_cli_emit, **kwargs)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

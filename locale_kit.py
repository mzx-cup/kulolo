"""多语言（中文 / 英文 / 阿拉伯语）UI 文案与日期解析工具。

为什么需要这个模块：手机系统语言一变，界面上的月份名、星期名、按钮文案
全都会本地化，而且阿拉伯语下还有两个额外陷阱——

1. **阿拉伯-印度数字**：'١٦ نوفمبر'、'٠٩:٤٦'。所有基于 `\\d` 的日期/时间
   解析都会直接失效，必须先转成 ASCII 再匹配。注意 `adb shell date` 的输出
   仍然是 ASCII，只有 UI 上的文本才会本地化。
2. **RTL 翻转**：日历月网格在 RTL 下左滑得到的是**上一个月**，右滑才是下一
   个月。水平滑动换月必须按方向翻转，否则永远翻不到目标月份。

这里只放"纯数据 + 纯函数"，不碰 adb，方便单测。
"""
from __future__ import annotations

import datetime as dt
import re

# ── 语言与区域设置 ────────────────────────────────────────────

LOCALE_ZH = "zh-Hans-CN"
LOCALE_EN = "en-US"
LOCALE_AR = "ar-SA"

#: 前端「触发语言」下拉用的三档。value 直接写进
#: `settings put system system_locales`，所以必须是合法的 BCP-47。
TRIGGER_LOCALES: tuple[tuple[str, str], ...] = (
    (LOCALE_ZH, "中文"),
    (LOCALE_EN, "英语"),
    (LOCALE_AR, "阿拉伯语"),
)
DEFAULT_LOCALE = LOCALE_ZH

#: 阿拉伯语 / 波斯语 / 乌尔都语等从右往左书写的语言前缀。
_RTL_PREFIXES = ("ar", "fa", "he", "iw", "ur", "yi", "ps", "sd", "ug", "dv")


def normalize_locale(raw: str) -> str:
    """把设备返回的 system_locales 归一化。

    实测 `settings get system system_locales` 可能返回 'ar-SA'、'ar_SA'、
    'ar-SA,en-US'（多语言偏好列表）、'zh-Hans-CN'（带文字子系统标签）。
    只取第一个，语言码小写、国家码大写，**保留 Hans/Hant 这类中间段**
    ——截掉它就变成 'zh-HANS'，与 'zh-Hans-CN' 永远比不相等，语言切换会
    每次都白重启一遍（实际踩过）。
    """
    text = (raw or "").strip()
    if not text or text == "null":
        return ""
    first = re.split(r"[,\s]+", text)[0]
    first = first.replace("_", "-")
    parts = [p for p in first.split("-") if p]
    if not parts:
        return ""
    out = [parts[0].lower()]
    for p in parts[1:]:
        if len(p) == 4:
            out.append(p.title())          # Hans / Hant
        elif len(p) == 2:
            out.append(p.upper())          # CN / SA / US
        else:
            out.append(p)
    return "-".join(out)


def is_rtl(raw_locale: str) -> bool:
    """该区域设置是否从右往左书写。"""
    norm = normalize_locale(raw_locale)
    if not norm:
        return False
    return norm.split("-")[0] in _RTL_PREFIXES


def locale_family(raw_locale: str) -> str:
    """'ar-SA' -> 'ar'；'zh-Hans-CN' -> 'zh'；认不出返回 ''。"""
    norm = normalize_locale(raw_locale)
    return norm.split("-")[0] if norm else ""


def label_for_locale(locale: str) -> str:
    """给前端/日志用的人类可读名字。

    设备上真正生效的 tag 常常和选项里的不一样（X6766 没有 ar-SA，
    会被解析成 ar-EG），所以这里按「语言族」兜一层，阿拉伯语 / 英语 /
    中文都能拿到对应的中文名，而不是回落成裸 tag。
    """
    for value, name in TRIGGER_LOCALES:
        if same_locale(value, locale):
            return name
    family = locale_family(locale)
    for value, name in TRIGGER_LOCALES:
        if locale_family(value) == family:
            return name
    return locale or "未知"


def same_locale(a: str, b: str) -> bool:
    """两个 locale 是否算「同一种界面语言」，用于跳过重复重启。

    不能直接比字符串：设备有时把中文读成 'zh-CN'、有时读成 'zh-Hans-CN'，
    英文可能只有 'en'。这里按「语言码相同 + 区域码不冲突」判：
    'zh-Hans-CN' 与 'zh-CN' 算同一种（只是省了文字子系统标签），
    'zh-Hans-CN' 与 'zh-Hant-TW' 不算（简繁是两种界面）。
    """
    na, nb = normalize_locale(a), normalize_locale(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    pa, pb = na.split("-"), nb.split("-")
    if pa[0] != pb[0]:
        return False
    ra = {p.upper() for p in pa[1:] if len(p) == 2}
    rb = {p.upper() for p in pb[1:] if len(p) == 2}
    if ra and rb and not (ra & rb):
        return False          # zh-Hans-CN vs zh-Hant-TW 这类区域不同，仍算同一界面
    return True


# ── 阿拉伯-印度数字 ──────────────────────────────────────────
#
# 实测设备（X6766 / Android 17 / ar-SA）用的是 U+0660..U+0669 这一组
# （Arabic-Indic）。波斯语用 U+06F0..U+06F9（Extended Arabic-Indic），
# 顺手一起转，成本为零。

_ARABIC_INDIC = "٠١٢٣٤٥٦٧٨٩"
_EXT_ARABIC_INDIC = "۰۱۲۳۴۵۶۷۸۹"
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate(_ARABIC_INDIC)}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate(_EXT_ARABIC_INDIC)})
#: 阿拉伯语里当小数点/千分位用的字符，UI 文本里可能混进来
_DIGIT_MAP[ord("٫")] = "."      # U+066B ARABIC DECIMAL SEPARATOR
_DIGIT_MAP[ord("٬")] = ""       # U+066C ARABIC THOUSANDS SEPARATOR
_DIGIT_MAP[ord("\u200f")] = ""  # RLM
_DIGIT_MAP[ord("\u200e")] = ""  # LRM

_DIGIT_RE = re.compile(r"[٠-٩۰-۹]")


def to_ascii_digits(text: str) -> str:
    """把阿拉伯-印度数字（以及 RLM/LRM 这类方向标记）转成 ASCII。

    非数字文本原样保留，所以可以无脑对任何 UI 文本调用。
    """
    if not text:
        return ""
    return text.translate(_DIGIT_MAP)


def has_arabic_digits(text: str) -> bool:
    return bool(_DIGIT_RE.search(text or ""))


# ── 月份 / 星期名 ────────────────────────────────────────────

MONTHS_ZH = ["一月", "二月", "三月", "四月", "五月", "六月",
             "七月", "八月", "九月", "十月", "十一月", "十二月"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"]
MONTHS_EN_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
#: 阿拉伯语月份名（实测自 ar-SA 日历 dateTitle，索引 0 = 一月）
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
             "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

WEEK_ZH = "一二三四五六日"          # 周一..周日
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday",
               "Friday", "Saturday", "Sunday"]
WEEKDAYS_EN_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
#: 阿拉伯语星期名（实测，索引 0 = 周一）
WEEKDAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس",
               "الجمعة", "السبت", "الأحد"]

#: 阿拉伯语日期格里的分隔符是 U+060C ARABIC COMMA
AR_COMMA = "،"


def month_names_all() -> list[tuple[int, str]]:
    """(1..12, 名称) 的所有语言写法，供子串匹配用。

    长的排前面：阿拉伯语月份名之间没有包含关系，但中文「十一月」包含
    「一月」，所以中文必须从十二月往一月倒着试。
    """
    pairs: list[tuple[int, str]] = []
    for i in range(12, 0, -1):
        pairs.append((i, MONTHS_ZH[i - 1]))
    for i in range(1, 13):
        pairs.append((i, MONTHS_AR[i - 1]))
    for i in range(1, 13):
        pairs.append((i, MONTHS_EN_ABBR[i - 1]))
    for i in range(1, 13):
        pairs.append((i, MONTHS_EN[i - 1]))
    return pairs


_MONTH_LOOKUP = month_names_all()


def month_index_in(text: str) -> int | None:
    """从任意语言的文本里认出月份（1..12）。认不出返回 None。"""
    raw = text or ""
    if not raw.strip():
        return None
    for idx, name in _MONTH_LOOKUP:
        if name in raw:
            return idx
    # 纯数字月：'12月' / '12月25日' / '2026-11'
    norm = to_ascii_digits(raw)
    m = re.search(r"(\d{1,2})\s*月", norm)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(1))
    m = re.search(r"\b(\d{4})[-/.](\d{1,2})\b", norm)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(2))
    return None


def weekday_index_in(text: str) -> int | None:
    """从任意语言文本里认出星期（0=周一 .. 6=周日）。"""
    raw = text or ""
    for i, name in enumerate(WEEKDAYS_AR):
        if name in raw:
            return i
    for i, name in enumerate(WEEKDAYS_EN_ABBR):
        if name in raw:
            return i
    for i, name in enumerate(WEEKDAYS_EN):
        if name.lower() in raw.lower():
            return i
    for i, ch in enumerate(WEEK_ZH):
        if f"星期{ch}" in raw or f"周{ch}" in raw:
            return i
    return None


def year_in(text: str) -> int | None:
    """从标题里取四位年份。用 ASCII 归一化后再找，阿拉伯语下也能认。"""
    norm = to_ascii_digits(text or "")
    m = re.search(r"(\d{4})\s*(?:年|[-/.]\s*\d)", norm)
    if m:
        return int(m.group(1))
    m = re.search(r"(?<!\d)(20\d{2})(?!\d)", norm)
    return int(m.group(1)) if m else None


# ── 日期格子的 content-desc 候选 ─────────────────────────────

def date_cell_descs(target: dt.date) -> list[str]:
    """日期格子的 content-desc 候选（中/英/阿三语，月网格/周条/周视图通用）。

    实测格式：
      中文月网格：      '10月23日星期五'
      英文月视图：      'Monday, November 9'
      英文周条：        'Friday 23 October'
      阿拉伯语月网格：  'الاثنين، ١٦ نوفمبر'   ← 星期 + '، ' + 日号 + 空格 + 月名
    阿拉伯语里的日号是阿拉伯-印度数字，所以候选里同时给出阿拉伯数字和
    ASCII 数字两种写法（部分系统会把数字显示成 ASCII）。
    """
    mon_zh = target.month
    day = target.day
    wk_zh = WEEK_ZH[target.weekday()]
    ab = MONTHS_EN_ABBR[target.month - 1]
    en = MONTHS_EN[target.month - 1]
    wd = WEEKDAYS_EN[target.weekday()]
    ar_mon = MONTHS_AR[target.month - 1]
    ar_wd = WEEKDAYS_AR[target.weekday()]

    out: list[str] = [
        # 中文 / 英文（原有行为，不能删）
        f"{mon_zh}月{day}日星期{wk_zh}",
        f"{mon_zh}月{day}日周{wk_zh}",
        f"{wd} {day} {en}",
        f"{wd}, {en} {day}",
        f"{wd}, {en} {day}, {target.year}",
        f"{wd}, {ab} {day}",
        f"{wd}, {ab} {day}, {target.year}",
        f"{wd} {en} {day}",
        f"{wd}, {day} {en}",
        f"{day} {ab} {target.year}",
        f"{ab} {day}, {target.year}", f"{ab} {day}",
        f"{day} {en}", f"{en} {day}",
        f"{en} {day}, {target.year}", f"{day} {en} {target.year}",
        f"{target.year}年{mon_zh}月{day}日",
        f"{target.year}-{target.month:02d}-{day:02d}",
        f"{target.year}/{target.month}/{day}",
    ]
    # 阿拉伯语：日号同时给阿拉伯-印度数字与 ASCII 两种
    day_variants = [str(day)]
    ar_day = "".join(_ARABIC_INDIC[int(c)] for c in str(day))
    if ar_day != str(day):
        day_variants.append(ar_day)
    for dv in day_variants:
        out.append(f"{ar_wd}{AR_COMMA} {dv} {ar_mon}")
        out.append(f"{ar_wd}{AR_COMMA} {dv} {ar_mon} {target.year}")
        out.append(f"{dv} {ar_mon}")
    return out


# ── 界面文案表 ──────────────────────────────────────────────
#
# 按"语义"给标签，各场景直接取 *_LABELS 丢给 _find_first_text，不再各自
# 硬写中英文。新增语言只需往这里加一项。

UI_LABELS: dict[str, tuple[str, ...]] = {
    "auto_time": (
        "自动设置时间", "自动确定日期和时间", "自动日期和时间",
        "自动更新时间", "自动获取时间和日期",
        "Auto-Set Time", "Set automatically",
        "Automatic date & time", "Auto date & time",
        # ar-SA 实测
        "تعيين الوقت تلقائيًا", "ضبط الوقت تلقائيًا",
        "الوقت والتاريخ تلقائيًا", "التاريخ والوقت تلقائيًا",
    ),
    "date": (
        "日期", "Date", "Set date", "设置日期", "选择日期",
        "التاريخ", "تعيين التاريخ",
    ),
    "time": (
        "时间", "Time", "Set time", "设置时间",
        "الوقت", "تعيين الوقت",
    ),
    "ok": (
        "确定", "OK", "Done", "Set", "Save", "完成", "好",
        "موافق", "حسنًا", "حسنا", "تعيين", "حفظ", "تم",
    ),
    "date_time_entry": (
        "Date & time", "Date and time", "日期和时间", "日期与时间",
        "التاريخ والوقت",
    ),
    "system": ("System", "系统", "النظام"),
    "dialog_buttons": (
        "确定", "OK", "Done", "Save", "Set", "完成", "好",
        "关闭", "知道了", "取消", "Cancel", "Import", "导入",
        "暂不", "以后再说", "Not now", "Later", "Got it", "Dismiss",
        "Agree And Continue", "Agree & Continue", "同意并继续",
        "Agree", "同意", "Continue",
        "موافق", "حسنًا", "حسنا", "إلغاء", "تم", "لاحقًا", "ليس الآن",
    ),
    "important_day": (
        "重要日", "Important day", "يوم مهم",
    ),
    "birthday": ("生日", "Birthday", "عيد الميلاد"),
    "anniversary": ("纪念日", "Anniversary", "الذكرى السنوية"),
    "exam": ("考试", "Exam Day", "يوم الاختبار", "يوم الامتحان"),
    "performance": ("观演日", "Show Day", "يوم العرض"),
    "add": ("添加", "Add", "إضافة"),
}


def labels(key: str) -> tuple[str, ...]:
    """取某组语义标签；未知 key 返回空元组（调用方会当"没配"处理）。"""
    return UI_LABELS.get(key, ())


def merge_labels(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """把多组标签合并去重（保序）。"""
    out: list[str] = []
    seen: set[str] = set()
    for grp in groups:
        for item in grp:
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return tuple(out)


# ── 方向 ────────────────────────────────────────────────────

def forward_swipe(is_rtl_layout: bool) -> str:
    """换到下一个月该往哪边滑。

    LTR：左滑下一月（手指从右往左）；RTL：**右滑**才下一月——实测 ar-SA
    下左滑得到的是上一个月。返回 'left' / 'right'。
    """
    return "right" if is_rtl_layout else "left"


def swipe_points(width: int, y: int, direction: str,
                 half: int = 300) -> tuple[int, int, int, int]:
    """把方向变成 swipe 的 (x1, y1, x2, y2)。"""
    mid = width // 2
    if direction == "left":
        return mid + half, y, mid - half, y
    return mid - half, y, mid + half, y

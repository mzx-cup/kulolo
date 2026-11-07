"""自动找出目标卡片：滑智慧建议轮播 + 认控件树，不需要人来点「已触发」。

为什么需要这个模块
------------------
以前每个场景跑完都会 `r.confirm()` —— 弹个「卡片出来了吗？」让人肉眼确认。
问题是：卡片可能
  * 在锁屏上（要亮屏上滑才看得见）；
  * 在桌面「智慧建议」小部件里，而小部件是**轮播**的，当前显示第几张没准；
  * 被优先级更高的卡（早安卡 / Premier League）挡住，根本不在第一屏；
  * **被顶部展开的「灵动岛」黑色卡片压住**（它会盖住小部件上半截）。
人肉确认既慢又容易点错。这里把它变成可编程的：

  1. `dismiss_dynamic_island` —— 把展开的灵动岛收起来，别挡着卡片；
  2. `find_widget`            —— 从控件树里定位智慧建议小部件的屏幕区域；
  3. `swipe_carousel`         —— 在这个区域里竖滑，一屏一屏地翻；
  4. `match_any`              —— 拿场景给的关键词去比控件树的 text/desc；
  5. `probe_home` / `probe_lock` —— 串成「桌面找一轮」「锁屏看一眼」；
  6. `capture`                —— 找到就截图，作为证据交给场景/前端。

真实轮播行为（X6766 / XOS 17 实测）
-----------------------------------
桌面首页的智慧建议小部件，**竖滑**会翻到下一条建议（横滑是翻桌面分页，
会把整个桌面滑走）。轮播条数实测 4 条左右，翻一圈会回到第一张，所以
轮播检测靠「连续两条都见过」来判断翻满一轮，而不是硬等固定次数。

灵动岛（DynamicBar）实测
------------------------
展开时是一个叫 `DynamicBarCard` 的 SystemUI 窗口，frame≈[0,10][1208,733]，
屏幕顶部 y≈148~216 会出现一大片纯黑（实测 1074px 宽），正好压住小部件
卡片的上半截 —— 截出来的卡片图顶上带一条黑边，很难看。

收起办法：**从灵动岛卡片内部向上滑**（实测 `input swipe 604 360 604 90 160ms`
3/3 成功，焦点仍在桌面）。注意：
  * 点岛中心会打开日历事件详情页，破坏当前场景；
  * 点岛外空白处 / 按 BACK / 按 HOME 都不稳定（实测有的能收有的不能）；
  * 只有上滑手势可靠且不切 App。
判断「是否展开」靠 `dumpsys window windows` 里有没有 `DynamicBarCard` 窗口，
比看像素稳；窗口是 SystemUI 的，launcher 的 uiautomator dump 里看不到它。

控件树实测（1208x2644）
-----------------------
    x55              desc="AI اقتراحات" / text=""     小部件整体 (611,213)-(1153,801)
    TextView                    text="智慧建议"          标题 (639,727)-(1125,801)
    ...              ← 轮播中的卡片本体（文字因卡而异）
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from phone_ctl import Device, Node, UiError

# 小部件标题在三种系统语言下的写法（和 phone_ctl.HOME_PAGE_TEXTS 同源）
WIDGET_TEXTS = (
    "智慧建议", "Smart suggestions", "Smart Suggestions",
    "AI suggestions", "AI اقتراحات", "اقتراحات ذكية",
)
# 小部件容器的 content-desc 也带这几个词，用它兜底定位
WIDGET_DESC_HINTS = WIDGET_TEXTS

# 锁屏上「灵动岛/原子卡片」的控件 id（实测 com.android.systemui:id/atomic_title）
LOCK_CARD_RIDS = ("atomic_title", "atomic_subTitle")

# 轮播最多滑几次。实测一圈 4 张，留一倍余量；再多就是异常了。
MAX_SWIPES = 10
# 每次滑动后等卡片换过来。实测 1.5 秒够，给到 1.8 稳一点。
SWIPE_SETTLE = 1.8
# 滑动时长：太快会被当成 fling 甩过头，太慢会被当成拖拽，300ms 实测最稳
SWIPE_MS = 300

# 灵动岛：SystemUI 窗口名 + 收起手势坐标（屏幕 1208x2644 实测）
ISLAND_WINDOW = "DynamicBarCard"
ISLAND_SWIPE = (604, 360, 604, 90, 160)   # (x1, y1, x2, y2, ms)
ISLAND_SETTLE = 1.4                        # 收起动画要等久一点，1.0s 偶尔还在
ISLAND_MAX_TRIES = 3


@dataclass
class CardHit:
    """一次命中：在哪儿看到的、命中的是哪条文案、截图存哪。"""
    where: str                  # "home" / "lock"
    text: str                   # 控件树里命中的那条文案
    keyword: str                # 命中的是哪个关键词
    index: int = 0              # 桌面轮播翻到第几张时命中的（0 起）
    texts: list[str] = field(default_factory=list)   # 当时整块区域的文案，排障用
    shot: str = ""              # 截图文件路径（相对 workspace），没截就是空
    box: tuple[int, int, int, int] | None = None     # 卡片屏幕区域，用于裁实拍图

    def as_dict(self) -> dict:
        return {
            "where": self.where,
            "text": self.text,
            "keyword": self.keyword,
            "index": self.index,
            "texts": self.texts,
            "shot": self.shot,
            "box": self.box,
        }


# ── 顶部灵动岛 ───────────────────────────────────────────────────

def island_expanded(dev: Device) -> bool:
    """顶部「灵动岛」是不是展开成一张黑色大卡片（会挡住智慧建议卡片）。

    靠 `dumpsys window windows` 里有没有 `DynamicBarCard` 窗口判断，不看像素：
    这个窗口属于 SystemUI，launcher 的 uiautomator dump 里根本没有它，
    而「窗口在不在」比「屏幕黑不黑」稳定得多（壁纸本身也可能很暗）。
    """
    try:
        out = dev.shell("dumpsys window windows")
    except Exception:  # noqa: BLE001
        return False
    return ISLAND_WINDOW in out


def dismiss_dynamic_island(dev: Device, *, log=None,
                           max_tries: int = ISLAND_MAX_TRIES) -> bool:
    """把展开的灵动岛收起来，返回是否成功（本来就没展开也算成功）。

    为什么用「从岛内上滑」：实测点岛中心会打开日历事件详情页（破坏场景），
    点岛外 / BACK / HOME 都时灵时不灵，只有上滑 3/3 稳定收起且焦点仍在桌面。

    收不下去也不抛错：最多试 max_tries 次，之后照样继续识别 —— 顶多是
    截图上方带一条黑边，不该因此把整轮场景判失败。
    """
    say = log or (lambda _m: None)
    for i in range(1, max_tries + 1):
        if not island_expanded(dev):
            if i > 1:
                say(f"灵动岛已收起（第 {i - 1} 次上滑生效）")
            return True
        x1, y1, x2, y2, ms = ISLAND_SWIPE
        dev.swipe(x1, y1, x2, y2, ms)
        time.sleep(ISLAND_SETTLE)
    ok = not island_expanded(dev)
    say("灵动岛已收起" if ok else "警告：灵动岛没收起来，截图顶部可能带黑边")
    return ok


# ── 定位小部件 ───────────────────────────────────────────────────

def find_widget(nodes: list[Node]) -> tuple[int, int, int, int] | None:
    """在小部件标题的**上方**找卡片区域，返回 (left, top, right, bottom)。

    为什么不用标题节点本身的 bounds：实测标题 "智慧建议" 在 (639,727)-(1125,801)，
    而卡片本体在它**上面**（y 213~727）。真正包住整块的是那个带
    content-desc="AI اقتراحات" 的容器。所以优先用它；找不到就按标题
    的宽度和「上面一块差不多高的方形区」推算。
    """
    # 1) 优先：带多语言 desc 的容器，通常就是整块小部件
    for n in nodes:
        if (n.desc or "").strip() in WIDGET_DESC_HINTS and n.bounds != (0, 0, 0, 0):
            x1, y1, x2, y2 = n.bounds
            if x2 - x1 > 100 and y2 - y1 > 100:
                return (x1, y1, x2, y2)

    # 2) 退一步：找标题节点，往上方取一块方形区域
    for n in nodes:
        if (n.text or "").strip() in WIDGET_TEXTS:
            x1, y1, x2, y2 = n.bounds
            side = x2 - x1
            if side < 100:
                continue
            top = max(0, y1 - side)
            return (x1, top, x2, y1)
    return None


def card_box(nodes: list[Node], widget: tuple[int, int, int, int] | None = None
             ) -> tuple[int, int, int, int] | None:
    """量「卡片本体」的屏幕框（抠图用），比小部件整体框更紧。

    小部件整体框 (611,213)-(1153,801) 里，标题「智慧建议」占了下沿
    (639,727)-(1125,801)，真正的卡片是上面那块 486x486 的正方形
    （logcat 里 `getCardView cardView:... 0,0-486,486` 也印证了这个尺寸）。
    所以直接用「整体框上沿 + 486x486」比什么都准，也不用猜圆角。

    实测（1208x2644）：
        widget (611,213)-(1153,801)
        card   (639,241)-(1125,727)   ← 486x486
    """
    if widget is None:
        widget = find_widget(nodes)
    if widget is None:
        return None
    x1, y1, x2, y2 = widget
    # 标题节点能给出更准的左边界；没有就按左右各内缩 28px（实测量到）
    for n in nodes:
        if (n.text or "").strip() in WIDGET_TEXTS:
            tx1, ty1, tx2, _ = n.bounds
            if tx2 - tx1 > 100:
                x1, x2 = tx1, tx2
                break
    side = x2 - x1
    # 卡片顶沿：整体框上沿 + 28px（实测 213 → 241）。
    # 不用「居中」算法：整体框下沿还含 74px 的标题，居中会往下偏 23px。
    top = y1 + 28
    return (x1, top, x1 + side, top + side)


def card_area_texts(nodes: list[Node], box: tuple[int, int, int, int]) -> list[str]:
    """取小部件区域内的全部文案（text 优先，没 text 用 desc）。

    区域判定按「控件中心落在框内」，因为卡片里的 TextView 常常比区域还宽
    几个像素（实测卡片本体 486x486 比标题区更宽），按 bounds 完全包含会漏。
    """
    x1, y1, x2, y2 = box
    out: list[str] = []
    for n in nodes:
        cx, cy = n.center
        if not (x1 - 8 <= cx <= x2 + 8 and y1 - 8 <= cy <= y2 + 8):
            continue
        t = (n.text or "").strip() or (n.desc or "").strip()
        if not t:
            continue
        # 小部件自己的名字不算卡片内容
        if t in WIDGET_TEXTS:
            continue
        if t and t not in out:
            out.append(t)
    return out


# ── 文案匹配 ─────────────────────────────────────────────────────

def match_any(texts: list[str], keywords) -> tuple[str, str] | None:
    """在文案列表里找关键词，返回 (命中的整条文案, 命中的关键词)。

    关键词按传入顺序试 —— 调用方应该把**最具体**的放前面（比如先试卡片标题
    「今天是Bday」，再退到更泛的「抽取你的幸运四叶草」）。
    英文关键词按不区分大小写比。
    """
    if isinstance(keywords, str):
        keywords = (keywords,)
    lows = [(t, t.lower()) for t in texts]
    for kw in keywords:
        if not kw:
            continue
        kw_low = kw.lower()
        for raw, low in lows:
            if kw_low in low:
                return raw, kw
    return None


# ── 截图 ─────────────────────────────────────────────────────────

def _slug(text: str, limit: int = 40) -> str:
    """把文案变成安全的文件名片段：只留字母数字和中文，其余折成下划线。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text, flags=re.UNICODE).strip("_")
    return s[:limit] or "card"


def save_shot(dev: Device, dest_dir, stem: str) -> str:
    """截一张图存到 dest_dir，返回绝对路径字符串；失败返回空串。

    截图失败不该让整条流程失败 —— 卡片已经认出来了才是关键证据，
    图只是「顺手存一份」，前端看不到图也还能靠文本知道结果。
    """
    try:
        png = dev.screenshot_png()
    except Exception:  # noqa: BLE001
        return ""
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        p = dest_dir / f"{_slug(stem)}.png"
        p.write_bytes(png)
        return str(p)
    except OSError:
        return ""


# ── 桌面：滑轮播找卡 ──────────────────────────────────────────────

def _plate_of(nodes: list[Node], box) -> list[str]:
    """把这个小部件区域在截图里的「指纹」，用来判断轮播有没有换张。

    不需要真看像素 —— 区域内的文案集合变了就是换张了。文案完全一样的
    两张卡（几乎不会）会被当成没换，代价只是少翻一屏。
    """
    return card_area_texts(nodes, box) if box else []


def probe_home(dev: Device, keywords, *, swipes: int = MAX_SWIPES,
               log=None, tag: str = "") -> CardHit | None:
    """在桌面首页里翻智慧建议轮播，找包含关键词的那张卡。

    先看当前这一屏（省掉一次无谓的滑动），没命中再一张一张翻；
    翻到「连续两次遇到已经见过的内容」就判定转了一圈，提前收工。

    返回 CardHit（where="home"）；没找到返回 None。
    全程只 dump，不点任何东西 —— 点卡片会把 App 拉起来，破坏当前场景。
    """
    say = log or (lambda _m: None)

    try:
        nodes = dev.dump()
    except UiError as exc:
        say(f"控件树读取失败，跳过桌面识别：{exc}")
        return None

    box = find_widget(nodes)
    if box is None:
        say("没在控件树里找到智慧建议小部件（可能不在首页或小部件被移除）")
        return None
    say(f"智慧建议小部件区域 {box}")

    seen: set[tuple[str, ...]] = set()
    index = 0
    for i in range(swipes + 1):
        texts = _plate_of(nodes, box)
        fingerprint = tuple(sorted(texts))
        hit = match_any(texts, keywords)
        if hit:
            raw, kw = hit
            say(f"第 {i} 屏命中「{raw}」（关键词 {kw}）")
            # 抠图用：卡片本体的紧框（不是整个小部件区域）
            return CardHit(where="home", text=raw, keyword=kw,
                           index=index, texts=texts, shot=tag,
                           box=card_box(nodes, box))
        if not texts:
            say(f"第 {i} 屏在小部件区域里读不到任何文案（卡片可能还没渲染）")
        else:
            say(f"第 {i} 屏不是目标卡：{' / '.join(texts[:4])}")

        # 转满一圈了：这一屏的内容之前见过
        if fingerprint in seen:
            say("轮播已经转了一圈，没有找到目标卡片")
            return None
        seen.add(fingerprint)

        if i == swipes:
            break

        # 在区域中心竖滑一次翻到下一条。横滑会翻桌面分页，千万别用。
        x1, y1, x2, y2 = box
        cx = (x1 + x2) // 2
        lo, hi = y1 + (y2 - y1) // 5, y2 - (y2 - y1) // 5
        dev.swipe(cx, hi, cx, lo, SWIPE_MS)
        time.sleep(SWIPE_SETTLE)
        index += 1
        try:
            nodes = dev.dump()
        except UiError as exc:
            say(f"第 {i + 1} 屏控件树读取失败：{exc}")
            return None
        # 区域位置理论上不变，但卡片尺寸可能略有差异，重算一次更保险
        box = find_widget(nodes) or box

    say(f"翻了 {swipes} 屏仍未找到目标卡片")
    return None


# ── 锁屏：看一眼原子卡片 ─────────────────────────────────────────

def lock_card_box(nodes: list[Node]) -> tuple[int, int, int, int] | None:
    """量锁屏原子卡片的屏幕框（抠图用）。

    实测（1208x2644，锁屏卡片出现时）：
        Chronometer  rid=atomic_title     b=(254,1903,739,1966)  text='今天是Bday110792'
        Chronometer  rid=atomic_subTitle  b=(254,1979,739,2036)  text='祝你顺利'
    两行文字只占卡片中间一小条，卡片本体是上面一整块圆角矩形（大概
    190~250px 高、跟文字同宽）。所以按文字 bounds 左右各留 32px、往上
    扩 150px、往下留 90px，围出整张卡。

    这些位置是 X6766 上量出来的常量；换机型会偏，但 `cutout_png` 里还有
    top-hat 描边兜底，偏一点不影响「四角透明」这个结果。
    """
    title = sub = None
    for n in nodes:
        if n.short_id == "atomic_title" and title is None:
            title = n.bounds
        elif n.short_id == "atomic_subTitle" and sub is None:
            sub = n.bounds
    if title is None:
        return None
    x1, y1, x2, y2 = title
    if sub is not None:
        x1, x2 = min(x1, sub[0]), max(x2, sub[2])
        y2 = max(y2, sub[3])
    pad_x = 32
    top, bottom = y1 - 150, y2 + 90
    return (max(0, x1 - pad_x), max(0, top),
            x2 + pad_x, bottom)


def probe_lock(dev: Device, keywords, *, log=None) -> CardHit | None:
    """在**当前**界面上找锁屏原子卡片（不动屏幕，调用方负责亮屏）。

    锁屏卡片的标题挂在 com.android.systemui:id/atomic_title，
    副标题是 atomic_subTitle。两者都在系统 UI 的控件树里，
    只要屏幕亮着就能读到。命中时把整张卡的区域也记下来，供后端裁切+抠图。
    """
    say = log or (lambda _m: None)
    try:
        nodes = dev.dump()
    except UiError as exc:
        say(f"锁屏控件树读取失败：{exc}")
        return None

    texts: list[str] = []
    for n in nodes:
        if n.short_id in LOCK_CARD_RIDS:
            t = (n.text or "").strip() or (n.desc or "").strip()
            if t and t not in texts:
                texts.append(t)
    if not texts:
        say("当前界面没有锁屏原子卡片")
        return None

    say(f"锁屏卡片文案：{' / '.join(texts)}")
    hit = match_any(texts, keywords)
    if hit:
        raw, kw = hit
        return CardHit(where="lock", text=raw, keyword=kw,
                       texts=texts, box=lock_card_box(nodes))
    return None


# ── 组合：桌面翻一轮 + 锁屏看一眼 ────────────────────────────────

def find_card(dev: Device, keywords, *, also_lock: bool = True,
              log=None) -> CardHit | None:
    """先找锁屏（如果现在正好在锁屏），再回桌面翻轮播。

    顺序有讲究：调用方通常刚「亮屏」完，屏幕可能还停在锁屏 —— 这时候直接
    按 HOME 会跳过去，白白错过锁屏上的卡片。所以先看锁屏，再看桌面。

    注意：本函数**不会**自己解锁或按 HOME，界面状态由调用方保证。想让它
    自己收尾，用下面带 `home_lock` 前缀的包装。
    """
    say = log or (lambda _m: None)
    if also_lock:
        hit = probe_lock(dev, keywords, log=say)
        if hit:
            return hit
    return probe_home(dev, keywords, log=say)


def find_card_anywhere(dev: Device, keywords, *, log=None) -> CardHit | None:
    """只找桌面首页的**智慧建议**卡片；不再把锁屏原子卡片算作命中。

    这是场景侧最常用的入口。`also_lock` 参数不再使用：锁屏上的
    `atomic_title` 与桌面智慧建议是两种不同 UI，之前混用导致生日策划案、
    考试考前提醒、追星提醒、重要日提醒被存成了灵动岛截图。
    """
    from scenario_birthday import ensure_home_before_confirm

    say = log or (lambda _m: None)

    class _R:
        """ensure_home_before_confirm 只要一个能 log 的对象。"""
        def log(self, msg):
            say(msg)

    ensure_home_before_confirm(dev, _R())
    # 顶部展开的灵动岛会压住智慧建议小部件的上半截，先收起再识别/截图。
    dismiss_dynamic_island(dev, log=say)
    return probe_home(dev, keywords, log=say)

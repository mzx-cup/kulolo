"""个人知识库授权卡片（蓝色底图 / 规则 10061 / 隐私合规类）。

触发链路（真机验证过，见 README）：
  1. 装 DemoHost（包名 com.example.tpk.client）→ 进「调试功能」→ 勾
     「测试环境」+「感知服务Flag」→ 点「更新TCSCONFIG」+「触发TCS更新云端数据」
     （不做这步云端配置，规则 10061 根本不会被评估）。
  2. 设置 / 系统 / 增强服务 / 个人知识库服务 → 关闭（必须点确认弹层的
     「关闭」按钮，否则 atomic_personal_knowledge_state 不落盘）。
  3. 关闭当天记为 T0，把系统时间拨到 T0 + N 天 12:35
     （N 只能是 1 / 4 / 6 / 36 / 72 / 108，规则 ability 2 的时间窗
     12:30~23:59；其它天不出卡，实测 D+2 blue=0.033 vs 节点日 0.728）。
  4. 息屏 → 亮屏 → 上滑解锁 → 回桌面，智慧建议轮播里出现蓝色底图卡片。

判定为什么不能用控件树文字：
  这张卡是 TPK serviceId=66071 的**自绘 View**，uiautomator 里没有文字。
  桌面上同时会有另一张白底「玩机技巧卡片」（文案「开启个人知识库，让服务
  更懂你。/ 立即开启」），按文本匹配会认错卡。所以这里用两个独立信号：
    * 截图像素：智慧建议卡片区蓝色占比 > 0.5（节点日 0.728 / 非节点日 0.033）
    * logcat：`Aitips_AITIPS_Knowledge_Authorization` 派发记录
  视觉证据（多帧采样取最大蓝色占比）或系统派发日志任一成立即算出卡 —— 蓝卡
  常落在轮播非首位，单帧可能采不到，但 logcat 里 onCardTrigger 一定在。
  因此 main.py 里这个场景**故意不声明 card_keywords**，
  自动识别会直接跳过（按已触发处理），由本模块自己判定并 emit 一条 card 事件。

多语言：所有点击都走 resource-id 或固定坐标，不用中文文案；确认弹层用
rid=btn_negative（不是中文「关闭」），三种语言都通用。
"""
from __future__ import annotations

import base64
import io
import re
import time
from datetime import date, timedelta

from PIL import Image

import fast_clock
from phone_ctl import (
    Device, KEY_HOME, KEY_POWER, KEY_WAKEUP, UiError,
)
from scenario_birthday import (
    Runner, _cli_emit, _prepare, device_date,
    ensure_home_before_confirm,
)

# ── 常量 ────────────────────────────────────────────────────────────────
RULE_ID = "10061"
INTENT = "transsion.intent.aitips.AITIPS_Knowledge_Authorization"
ATHENA = "Aitips_AITIPS_Knowledge_Authorization"
SERVICE_ID = "66071"

DEMO_PKG = "com.example.tpk.client"
DEMO_MAIN = f"{DEMO_PKG}/.MainActivity"
PK_ACT = ("com.transsion.atomiccore/"
          "com.transsion.atomiccore.settings.impl.activity."
          "PersonalKnowledgeActivity")
PK_STATE_KEY = "atomic_personal_knowledge_state"

# DemoHost 调试页里要点开的 4 个控件（全部按 rid，跨语言通用）
DEMO_RIDS = (
    "rb_test",                      # 测试环境
    "switch_percept_service_flag",  # 感知服务Flag
    "btn_update_tcs_config",        # 更新TCSCONFIG
    "btn_update_tcs_cloud_data",    # 触发TCS更新云端数据
)

# 主开关：里面的 Switch 节点不出现在控件树、也不可点；整行容器
# toggle_switch 本身 clickable=True，点它的中心最稳 —— 中文界面开关在右侧
# (x≈901~1101)，阿拉伯语 RTL 界面会翻到左侧 (x≈107~307)，硬编码坐标会在
# 阿语下点空，所以运行期从控件树取 toggle_switch.center。
# PK_TOGGLE_XY 仅作为控件树取不到时的兜底（中文布局）。
PK_TOGGLE_XY = (1028, 477)

# 关闭后允许出卡的 6 个节点日（规则 ability 15 = 总共最多 6 次，
# ability 22 = 每天 1 次；门控只在关闭后这 6 天放行）
NODE_DAYS = (1, 4, 6, 36, 72, 108)
DEFAULT_HOUR, DEFAULT_MINUTE = 12, 35

# 智慧建议卡片区（1208x2644 基准坐标；截图时按实际尺寸缩放）
CARD_BOX = (611, 213, 1153, 801)
BLUE_THRESHOLD = 0.5

OFF_SEC = 8
WAIT_CARD_SEC = 8
UNLOCK_SWIPE = (604, 2400, 604, 900, 260)


# ── 通用小工具 ──────────────────────────────────────────────────────────
def _dump_retry(dev: Device, tries: int = 8):
    """uiautomator 偶发空树 / could not get idle state，重试并清残留进程。"""
    for _ in range(tries):
        try:
            ns = dev.dump()
            if ns:
                return ns
        except Exception:
            pass
        try:
            dev.shell("pkill -9 -f uiautomator")
        except Exception:
            pass
        time.sleep(0.8)
    return []


def _by_rid(ns, suffix):
    return next((n for n in ns if (n.rid or "").endswith(suffix)), None)


def _pk_state(dev: Device) -> str:
    return (dev.shell(f"settings get global {PK_STATE_KEY}") or "").strip()


def _logcat_hits(dev: Device) -> tuple[int, int]:
    """返回 (athena 命中数, onCardTrigger 里含 Knowledge 的次数)。"""
    try:
        out = dev.shell("logcat -d") or ""
    except Exception:
        return 0, 0
    athena = len(re.findall(re.escape(ATHENA), out))
    trig = sum(1 for ln in out.splitlines()
               if "TpkServiceCard onCardTrigger" in ln and "Knowledge" in ln)
    return athena, trig


def _blue_ratio(png: bytes) -> float:
    """智慧建议卡片区里「蓝色像素」占比。

    判据 b > r+45 且 b > g+25 且 b > 120：节点日约 0.728，
    非节点日（白底玩机技巧卡）约 0.033，区分度极大。
    """
    if not png:
        return 0.0
    try:
        im = Image.open(io.BytesIO(png)).convert("RGB")
    except Exception:
        return 0.0
    w, h = im.size
    sx, sy = w / 1208.0, h / 2644.0
    x1, y1, x2, y2 = CARD_BOX
    box = (int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy))
    crop = im.crop(box).resize((60, 60))
    blue = 0
    for r, g, b in crop.getdata():
        if b > r + 45 and b > g + 25 and b > 120:
            blue += 1
    return round(blue / 3600.0, 3)


def _sample_blue(dev: Device, r: Runner, samples: int = 5,
                 gap: float = 3.5) -> tuple[float, bytes]:
    """连采几帧截图，返回「最大蓝色占比」和那一帧的 PNG。

    蓝卡是 TPK 自绘卡，派发后可能落在智慧建议轮播的非首位（被早安卡挤到
    index 3），单帧截图采到的会是别的白底卡；小部件自己会轮播，多采几帧
    就能覆盖到它。采到足够蓝就提前收手，正常节点日只花一帧。
    """
    best, best_png = 0.0, b""
    for i in range(samples):
        png = dev.screenshot_png()
        blue = _blue_ratio(png)
        if blue > best:
            best, best_png = blue, png
        if best > BLUE_THRESHOLD:
            break
        if i < samples - 1:
            time.sleep(gap)
    if samples > 1 and best <= BLUE_THRESHOLD:
        r.log(f"连采 {samples} 帧，蓝色占比最高只有 {best}")
    return best, best_png


# ── 三大步 ──────────────────────────────────────────────────────────────
def _configure_demo(dev: Device, r: Runner) -> None:
    """DemoHost 云端配置：测试环境 + 感知服务Flag + 更新 TCS 配置/云端数据。"""
    r.step("DemoHost 调试功能：测试环境 + 感知服务Flag + 更新云端配置")
    dev.shell(f"am force-stop {DEMO_PKG}")
    dev.shell(f"am start -n {DEMO_MAIN}")
    time.sleep(4.0)
    ns = _dump_retry(dev)
    btn = _by_rid(ns, "client_cloud_demo")
    if btn is None:
        raise UiError("DemoHost 主页找不到「调试功能」(client_cloud_demo)，"
                      "确认 com.example.tpk.client 已安装")
    dev.tap_node(btn)
    time.sleep(3.5)
    ns = _dump_retry(dev)
    for rid in DEMO_RIDS:
        node = _by_rid(ns, rid)
        if node is None:
            raise UiError(f"DemoHost 调试页找不到 {rid}")
        dev.tap_node(node)
        # 两个「更新」按钮会触发云端拉取，多给一点时间
        time.sleep(3.0 if rid.startswith("btn_update") else 1.2)
        ns = _dump_retry(dev) if rid.startswith("btn_update") else ns
    r.ok("云端配置已下发（TCSCONFIG + 云端数据）")


def _close_personal_knowledge(dev: Device, r: Runner) -> None:
    """关掉个人知识库服务，必须点确认弹层的 btn_negative 才会落盘。"""
    r.step("关闭个人知识库服务（含确认弹层）")
    dev.shell(f"am start -n {PK_ACT}")
    time.sleep(2.8)
    ns = _dump_retry(dev)
    toggle = _by_rid(ns, "toggle_switch")
    if toggle is None:
        raise UiError("没进到个人知识库服务设置页（找不到 toggle_switch）")
    # 取容器中心点：RTL 下开关翻到左边，只有控件树 bounds 是语言无关的
    xy = toggle.center or PK_TOGGLE_XY
    r.log(f"个人知识库主开关中心 {xy}（RTL 自适应）")

    # 关→开没有确认弹层，开→关才有；先确保是「开」，再走一次完整关闭。
    if _pk_state(dev) != "1":
        dev.tap(*xy)
        time.sleep(2.2)
        if _pk_state(dev) != "1":
            raise UiError("个人知识库服务没能重新打开，无法执行关闭动作")

    dev.tap(*xy)
    time.sleep(1.8)
    ns = _dump_retry(dev)
    neg = _by_rid(ns, "btn_negative")
    if neg is None:
        raise UiError("关闭时没弹出确认弹层（找不到 btn_negative）")
    dev.tap_node(neg)
    time.sleep(3.0)
    state = _pk_state(dev)
    if state != "0":
        raise UiError(f"点完「关闭」后 {PK_STATE_KEY} 仍是 {state!r}，关闭没生效")
    r.ok(f"{PK_STATE_KEY}=0（已落盘，退出重进仍为 0）")


def _trigger_one_day(dev: Device, r: Runner, t0: date, day: int,
                     hour: int, minute: int, off_sec: int,
                     wait_sec: int) -> dict:
    """拨到关闭后第 day 天 → 息屏 → 亮屏解锁 → 判定蓝卡。"""
    target = t0 + timedelta(days=day)
    r.step(f"系统时间设为关闭后第 {day} 天 "
           f"{target} {hour:02d}:{minute:02d}")
    dev.shell("settings put global auto_time 0")
    if not fast_clock.set_datetime(dev, target, hour, minute, log=r.log):
        raise UiError(f"没法把系统时间设到 {target} {hour:02d}:{minute:02d}")
    r.ok(f"设备时间 {dev.shell('date').strip()}")

    dev.key(KEY_HOME)
    time.sleep(1.2)
    dev.shell("logcat -c")

    r.step(f"息屏 {off_sec} 秒后亮屏、上滑解锁")
    dev.key(KEY_POWER)
    time.sleep(off_sec)
    dev.key(KEY_WAKEUP)
    time.sleep(1.3)
    dev.swipe(*UNLOCK_SWIPE)
    time.sleep(2.0)
    dev.key(KEY_HOME)
    time.sleep(wait_sec)
    r.ok("已回到桌面")

    # 蓝卡是 TPK 自绘卡，派发后可能落在智慧建议轮播的非首位（被早安卡挤到
    # index 3）。单帧截图那一刻采到的可能是别的白底卡，所以连采几帧取最大
    # 蓝色占比；正常节点日第一帧就够，只有轮播没转过来时才多花几秒。
    blue, png = _sample_blue(dev, r, samples=8, gap=3.0)
    athena, trig = _logcat_hits(dev)
    r.log(f"蓝色占比 {blue} / athena {athena} / onCardTrigger(Knowledge) {trig}")

    # 两条独立证据任一成立即算出卡：
    #   ① 截到了纯蓝底（视觉证据，最硬）；
    #   ② 系统自己打印了完整的派发链（athena>=2 且 onCardTrigger 命中）——
    #      轮播没转到蓝卡那帧时靠它兜底，与智能路况卡「判定走 logcat」同源。
    # 非节点日已被参数校验挡在门外，这里不用担心 1 次残留 onHide 的噪声。
    hit = blue > BLUE_THRESHOLD or (athena >= 2 and trig >= 1)
    if blue > BLUE_THRESHOLD and png:
        # 直接把「采到蓝卡的那一帧」发给前端，而不是重新截一张（轮播可能
        # 已经转到别的卡了）。
        r.emit({"t": "shot", "no": r._no, "tag": f"蓝色卡片 D+{day}",
                "png_b64": base64.b64encode(png).decode()})
    return {
        "day": day, "date": str(target), "blue": blue,
        "athena": athena, "trig": trig, "hit": hit,
    }


# ── 主入口 ──────────────────────────────────────────────────────────────
def run(dev: Device | None = None, emit=None, *,
        days: str | int | None = None,
        hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE,
        off_sec: int = OFF_SEC, wait_sec: int = WAIT_CARD_SEC,
        control: dict | None = None, confirm_fn=None, ask_fn=None) -> dict:
    """跑个人知识库授权卡片。

    days: 要验证的节点日，逗号分隔（如 "1,4,6,36,72,108"）或单个数字；
          留空则跑全部 6 个。非节点日（如 2）会被拒绝，因为规则门控不放行。
    """
    dev = dev or Device()
    r = Runner(dev, emit, control=control, confirm_fn=confirm_fn, ask_fn=ask_fn)
    dev.log = r.log

    # 参数校验
    try:
        hour, minute = int(hour), int(minute)
    except (TypeError, ValueError):
        raise UiError(f"系统时间 {hour!r}:{minute!r} 不是合法时分")
    if not (12 <= hour <= 23):
        raise UiError(f"规则 {RULE_ID} 的时间窗是 12:30~23:59，"
                      f"hour 必须在 12~23，收到 {hour}")
    if hour == 12 and minute < 30:
        raise UiError(f"规则 {RULE_ID} 的时间窗是 12:30~23:59，"
                      f"12 点必须 >= 30 分，收到 12:{minute:02d}")
    if not (3 <= off_sec <= 60):
        raise UiError("off_sec（息屏时长）必须在 3~60 秒之间")
    if not (3 <= wait_sec <= 60):
        raise UiError("wait_sec（解锁后等卡片）必须在 3~60 秒之间")

    if days is None or str(days).strip() == "":
        days_list = list(NODE_DAYS)
    else:
        try:
            days_list = [int(x) for x in str(days).replace("，", ",").split(",") if x.strip()]
        except ValueError:
            raise UiError(f"days={days!r} 不是合法的逗号分隔数字")
    bad = [d for d in days_list if d not in NODE_DAYS]
    if bad:
        raise UiError(f"关闭后第 {bad} 天不会出卡；只允许 {list(NODE_DAYS)}")

    result = {
        "rule_id": RULE_ID, "intent": INTENT, "service_id": SERVICE_ID,
        "days": days_list, "hour": hour, "minute": minute,
    }

    try:
        _prepare(dev, r)   # 唤醒 + 常亮 + 自动解锁
        dev.shell("settings put system screen_off_timeout 1800000")

        # 规则 10061 的 ability 15「总共最多 6 次」是持久计数：上一轮验证
        # 把 6 个节点日全跑过后，额度已经用满，再触发会被频控直接挡掉
        # （logcat 里 10061 完全不评估）。个人知识库的关闭基准时间也存在
        # atomiccore / atomicbrain 的私有存储里，pm clear 会一并重置。
        # 因此每次开跑前必须清一次原子服务，保证场景可重复执行；
        # 顺序上要放在 DemoHost 云端配置之前（cloud config 也落在被清的
        # 包里，清完必须重新下发）。
        r.step("清空原子服务缓存（重置 10061 的 6 次额度与关闭基准时间）")
        dev.clear_atomic_services()
        time.sleep(3.0)
        _prepare(dev, r)   # pm clear 后桌面/原子服务重启，重新唤醒解锁
        r.ok("额度已重置，原子服务已重新启动")

        _configure_demo(dev, r)
        _close_personal_knowledge(dev, r)

        # 关闭当天 = T0（此时设备时间还没被拨过）
        t0 = device_date(dev)
        r.log(f"关闭日 T0 = {t0}")
        result["close_date"] = str(t0)

        checks = []
        for day in days_list:
            checks.append(_trigger_one_day(dev, r, t0, day, hour, minute,
                                           off_sec, wait_sec))
            r.check()   # 允许前端「结束」打断
        result["checks"] = checks
        result["triggered_days"] = [c["date"] for c in checks if c["hit"]]

        # 收口：回桌面首页，再判定
        ensure_home_before_confirm(dev, r)
        r.shot("桌面")

        r.step("确认蓝色底图个人知识库卡片")
        hit = all(c["hit"] for c in checks)
        # 自己 emit 一条 card 事件：前端据此显示「自动识别」结果。
        # 不声明 card_keywords，main.py 的 _confirm_fn 会直接通过，
        # 真正的判定以这里的结果为准。
        if emit:
            emit({
                "t": "card", "no": r._no, "ok": hit,
                "scenario": "personal_knowledge",
                "text": (f"蓝色底图卡片（blue={checks[-1]['blue']}，"
                         f"派发 {checks[-1]['athena']} 次）"),
                "keyword": ATHENA, "where": "智慧建议轮播",
                "has_shot": False,
            })
        if not hit:
            missed = [c["date"] for c in checks if not c["hit"]]
            raise UiError(
                f"节点日 {missed} 没等到蓝色底图卡片。常见原因："
                "①DemoHost 云端配置没下发（规则 10061 不评估）；"
                "②关闭时没点确认弹层的「关闭」，状态没落盘；"
                "③当天额度已用掉（ability 22 每天 1 次 / 15 总共 6 次）；"
                "④系统时间没落在 12:30~23:59。")
        r.ok(f"已确认 {len(checks)} 个节点日全部出现蓝色底图卡片")
    finally:
        try:
            dev.stayon(True)
        except Exception:
            pass

    result["device_time_after"] = dev.shell(
        "date '+%Y-%m-%d %H:%M:%S %Z'").strip()
    result["steps"] = r._no
    result["ok"] = True
    result["triggered"] = True
    day_str = "/".join(str(c["day"]) for c in checks)
    blue_str = "/".join(f"{c['blue']:.3f}" for c in checks)
    result["summary"] = (
        f"完成。DemoHost 云端配置 → 关闭个人知识库服务（T0={t0}）→ "
        f"依次拨到关闭后第 {day_str} 天 {hour:02d}:{minute:02d} → "
        f"息屏亮屏解锁，{len(result['triggered_days'])}/{len(checks)} 天在"
        f"智慧建议轮播出现蓝色底图卡片（blue={blue_str}，规则 {RULE_ID} / "
        f"serviceId {SERVICE_ID}）。")
    return result


if __name__ == "__main__":
    import sys

    d = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        out = run(emit=_cli_emit, days=d)
        print("\n完成：", out)
    except UiError as exc:
        print(f"\n失败：{exc}", file=sys.stderr)
        sys.exit(1)

<script lang="ts">
import { computed, defineComponent, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { state } from "@/stores/core";
import type { ScenarioView } from "@/types/api";
import { currentVisible, trySelect, isFavorite, toggleFavorite, isBusy } from "@/actions/catalog";
import { iconBody } from "@/lib/icons";
import { pad2 } from "@/lib/format";
import { artFor } from "@/actions/cards";
import { specValue as specVal } from "@/actions/params";
import { oobeBlockReason, oobeBlockLabel } from "@/actions/oobe";
import { runScenario, pauseOrResume } from "@/actions/run";
import { toast } from "@/actions/toast";

/**
 * 沉浸式场景卡片轮播（中央舞台 / coverflow）。
 *
 * 视觉核心是「拖动驱动的连续 coverflow」：中央一张大卡，左右各露出相邻卡，
 * 往外还有更小、更透明的卡。拖拽时三张（以及更外侧）卡片随手指一起滑动、
 * 缩放、淡入淡出——中间的卡变小滑向一侧，另一侧的卡放大顶进中央；持续拖
 * 动可以连续前进多张。松手后按最近卡位落位。
 *
 * 交互入口：
 *   - 鼠标/触摸横向拖拽（跟手，松手按阈值 + 甩动速度落位）
 *   - 滚轮在轮播区内切换
 *   - 键盘 ← / →（由 App 层转发进来）
 *   - 点击两侧卡片把它切到中央
 *   - 圆点 + 位置指示器
 *
 * 数据源是「当前筛选 + 搜索」命中的可见列表；分类/搜索变化时，
 * 通过 watch 把索引重置到「当前选中项」对应的位置。
 */

/** 相邻卡槽横向间距（px），即一张卡滑进中央要走的路程 */
const UNIT = 300;
const FLICK_VEL = 0.45;  // 甩动速度阈值（px/ms）
const DRAG_SOFT = 320;   // 超过后开始「橡皮筋」阻尼
const DRAG_MAX = 560;    // 单次拖拽的硬上限
const SETTLE_MS = 580;   // 松手/切换落位动画时长（需覆盖 .54s 的卡片形变过渡，避免中途被打断）

/** 一个卡位在 coverflow 里的描述 */
interface DeckItem {
  key: string;
  card: ScenarioView;
  /** 该卡在环形列表里的绝对下标（可为负 / 越界，cardAt 会回绕） */
  slot: number;
  /** 相对视觉中心的偏移（卡位单位） */
  d: number;
  style: Record<string, string>;
}

export default defineComponent({
  name: "ScenarioStage",
  setup() {
    const list = computed<ScenarioView[]>(() => currentVisible());

    /** 已「提交」的中心卡下标（相对 list）。拖拽时不改，松手落位后才更新。 */
    const index = ref(0);
    /** 拖拽横向位移（px）。和 index 一起决定视觉中心。 */
    const dragX = ref(0);
    const dragging = ref(false);
    /** 落位/切换动画进行中：忽略新的拖拽与按键，避免打断动画。 */
    const settling = ref(false);
    const stageEl = ref<HTMLElement | null>(null);

    let dragStartX = 0;
    let dragStartY = 0;
    /** 本次拖拽的位移基准（px）：正常情况下是 0；若在落位动画途中按下，
     *  则是卡片当时的真实位移，拖拽从这个位置继续累加，不会瞬移。 */
    let dragBaseX = 0;
    let dragActive = false;
    let pointerId: number | null = null;
    let horizLocked = false;
    const velSamples: { x: number; t: number }[] = [];
    let releaseVel = 0;
    let settleTimer: number | null = null;
    /** 本次 pointerdown 是否落在侧卡上（用于「点一下切换」与「拖拽」的区分） */
    let downWasSide = false;
    /** pointerdown 落在侧卡时的卡位 slot */
    let downSlot: number | null = null;
    /** 是否发生了真正的横向拖拽（移动超过阈值才算，用于抑制点击） */
    let dragMoved = false;

    const count = computed(() => list.value.length);
    const pos = computed(() => (count.value ? `${pad2(index.value + 1)} / ${pad2(count.value)}` : "0 / 0"));
    const center = computed<ScenarioView | null>(() => list.value[index.value] ?? null);

    /** 环形取第 slot 张卡（slot 可为负 / 越界）。 */
    function cardAt(slot: number): ScenarioView | null {
      const n = count.value;
      if (n === 0) return null;
      return list.value[((slot % n) + n) % n] ?? null;
    }

    /** 视觉中心（连续值，卡位单位）。拖拽往左 → 值增大 → 后一张卡进中央。 */
    const visualC = computed(() => index.value - dragX.value / UNIT);

    /** 由「距视觉中心的偏移 d」算出卡片的位移/缩放/透明度/层级。
     *  形变分三个轴向，构成完整的「堆叠态切换」：
     *    --scx  横向缩放（1 中央 → 0.78 侧卡，卡变窄）
     *    --scy  纵向缩放（1 中央 → 0.70 侧卡，卡变短 —— 侧卡「长度」更短）
     *    --txop 文字不透明度：经过中央时渐显、滑开时渐隐（每张卡都套）
     *    --rich 富内容不透明度（一键运行按钮/规格/状态行）：只在中央附近显现，
     *           卡被顶替掉时随 |d| 增大渐隐，形成「按钮文字跟随拖动渐出」
     *    --gly  UI 图竖向位移（px）：中央 0 → 侧边下沉到接近顶部，图标不透明度
     *           单独控制，让它「松手后缓慢移到顶部」而不是突然消失 */
    function slotStyle(d: number): Record<string, string> {
      const x = d * UNIT;
      const ad = Math.abs(d);
      const scx = Math.max(0.6, 1 - ad * 0.22);
      const scy = Math.max(0.6, 1 - ad * 0.30);
      /* 透明度：|d|≤1 保持原来的线性（中央 1 → 侧卡 0.5，外观不变）；
         超过 1 之后加速衰减，到 |d|=1.5 正好归零。
         为什么要这样分段：deck 只渲染 3 张（base-1..base+1），base 在视觉中心
         越过 .5 时会整体前移一格，此时最外侧那张卡的 |d| 恰好是 1.5。
         若按原来的 1-|d|*0.5 算，它在被移除的瞬间还有 0.25 的不透明度 ——
         肉眼就是「一张半透明的卡忽然凭空消失」，这也是切换时卡顿感的来源之一。
         现在归零后再移除，交接完全无缝。 */
      const opacity = ad <= 1 ? 1 - ad * 0.5 : Math.max(0, 0.5 - (ad - 1));
      const zi = Math.max(1, 5 - Math.round(ad * 2));
      /* 文字随 |d| 渐入渐出：中央全显，侧边降到底限 0.25（仍能看到标题） */
      const txop = Math.max(0.25, Math.min(1, 1 - ad * 0.75));
      /* 富内容：|d|≤0.5 之间线性 0→1，超出就完全隐掉（只属于中央卡） */
      const rich = Math.max(0, Math.min(1, (0.5 - ad) / 0.5));
      /* UI 图：侧卡时（|d|→1）抬到更靠上、保持可见；中央（d=0）落回原位。
         移动方向：拖拽换卡时图标随卡片往侧边移动并缓慢上移。 */
      const glyY = (ad * 26).toFixed(1);
      /* 侧位补偿的生效进度（0 = 中央，1 = 完全侧位）。
         和 --txop 用同一条 |d| 曲线，卡片滑向侧边时文字**平滑下移**到居中位置，
         而不是到位后突然跳一下。 */
      const sl = Math.min(1, ad);
      return {
        "--so": `${x.toFixed(1)}px`,
        "--scx": scx.toFixed(3),
        "--scy": scy.toFixed(3),
        "--op": opacity.toFixed(3),
        "--txop": txop.toFixed(3),
        "--rich": rich.toFixed(3),
        "--gly": `${glyY}px`,
        "--sl": sl.toFixed(3),
        "--zi": String(zi),
      };
    }

    /** 当前要渲染的卡位：中心 1 张 + 两侧各 2 张（最多 5 张，边缘的透明）。 */
    const deck = computed<DeckItem[]>(() => {
      const n = count.value;
      if (n === 0) return [];
      if (n === 1) {
        const card = list.value[0];
        return [{ key: card.id, card, slot: 0, d: 0, style: slotStyle(0) }];
      }
      const base = Math.round(visualC.value);
      const items: DeckItem[] = [];
      /* 上限三张：中央 1 张 + 左右各 1 张。base 随视觉中心滑动重定向，
         离开的卡位和进来的卡位在边缘（|d|≈1.5，近透明）无缝交接，
         所以持续拖也能连续换卡、不会有第四张残留。 */
      for (let k = -1; k <= 1; k++) {
        const slot = base + k;
        const card = cardAt(slot);
        if (!card) continue;
        const d = slot - visualC.value;
        /* key 只用 card.id（稳定），不用 slot —— 否则卡片绕环到另一端时
           key 变了会被 Vue 卸载重建，又出现「内容瞬间消失再显现」的闪烁。 */
        items.push({ key: card.id, card, slot, d, style: slotStyle(d) });
      }
      return items;
    });

    /** 分组强调色 */
    const tone = computed(() => {
      if (!center.value) return "var(--tone-amber)";
      const g = state.groups.find((x) => x.name === center.value?._group);
      return g?.tone ?? "var(--tone-amber)";
    });

    const paramCount = computed(() => center.value?.params?.length ?? 0);
    const favorited = computed(() => (center.value ? isFavorite(center.value.id) : false));
    const runningThis = computed(() => state.running && state.selected?.id === center.value?.id);
    const runLabel = computed(() => (runningThis.value ? "运行中" : state.runLabel));

    function sideTone(card: ScenarioView | null): string {
      if (!card) return "var(--tone-amber)";
      const g = state.groups.find((x) => x.name === card._group);
      return g?.tone ?? "var(--tone-amber)";
    }

    function deckStyle(it: DeckItem): Record<string, string> {
      return {
        ...it.style,
        "--g-tone": sideTone(it.card),
        /* 该卡在侧位时需要下移多少 px 才能让可见文字居中（逐卡实测，见 measureSideLift） */
        "--slift": `${sideLift[it.card.id] ?? 0}px`,
      };
    }
    function isCenterSlot(it: DeckItem): boolean {
      return it.slot === index.value;
    }

    /** 同步 state.selected 到轮播索引（外部点分类/最近/搜索都走这里）。
     *  拖拽 / 落位动画期间不碰 dragX，否则会把「松手回弹」动画打断。 */
    function syncIndex(): void {
      const cur = state.selected?.id;
      const i = cur ? list.value.findIndex((s) => s.id === cur) : -1;
      if (i !== -1) {
        index.value = i;
      } else if (list.value.length) {
        index.value = 0;
        const first = list.value[0];
        if (first && first.id !== state.selected?.id && !state.running && !state.starting) {
          trySelect(first.id);
        }
      }
      if (!dragging.value && !settling.value) dragX.value = 0;
    }

    watch(
      () => [state.activeFilter, state.query, state.selected?.id] as const,
      () => syncIndex(),
    );
    watch(list, () => syncIndex());

    function resist(v: number): number {
      const sign = v < 0 ? -1 : 1;
      const abs = Math.abs(v);
      if (abs <= DRAG_SOFT) return v;
      const extra = (abs - DRAG_SOFT) * 0.35;
      return sign * Math.min(DRAG_MAX, DRAG_SOFT + extra);
    }

    function onPointerDown(e: PointerEvent): void {
      if (count.value < 2) return;
      /* 落位动画进行中也允许按下开始拖：手落下去的瞬间卡片正滑到一半，
         这里把它「接住」—— 记下当前肉眼位置作为拖拽起点（dragBaseX），
         后面所有位移都从这个位置累加，卡片不会瞬移回原位。
         不再直接 return 锁死：那会让「点了侧卡想马上拖」感觉被卡住。 */
      const wasSettling = settling.value;
      /* 运行中禁止拖动切卡：左侧目录的 trySelect 已经拦住了，但拖拽这里
         如果不拦，卡片照样会滑走、index 也会变，只是最后选择被拒 ——
         表现就是「左侧点不动、中间却还能切」。这里和目录保持同一道门禁。 */
      if (isBusy()) return;
      if (e.button !== 0) return;
      const t = e.target as HTMLElement | null;
      /* 侧卡也是可拖拽的：允许在侧卡上按下开始拖拽。
         但卡内的按钮/链接仍照常响应点击，不拦截。
         `.stage-desc-more`（展开/收起）必须在这里拦下来：一旦放过去，按下就会
         setPointerCapture 到视口上，手抖超过 4px 指针就被判成拖拽，pointerup 不再
         落在按钮上 —— 按钮的 click 直接被吞掉，表现就是「点了没反应」。 */
      if (t && t.closest("a, input, select, textarea, .stage-actions, .stage-desc-more")) return;

      const sideEl = t?.closest<HTMLElement>(".stage-card.is-side") ?? null;
      downWasSide = !!sideEl;
      downSlot = sideEl ? Number(sideEl.dataset.slot ?? NaN) : null;
      if (downWasSide && !Number.isFinite(downSlot)) downSlot = null;
      dragMoved = false;

      /* 接住未完成的落位动画：解除锁定、停掉计时器，并记住卡片当前的真实位移。 */
      dragBaseX = wasSettling ? currentOffsetPx() : 0;
      if (wasSettling) {
        if (settleTimer !== null) {
          clearTimeout(settleTimer);
          settleTimer = null;
        }
        settling.value = false;
      }

      dragActive = true;
      horizLocked = false;
      dragging.value = true;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      dragX.value = dragBaseX;
      releaseVel = 0;
      velSamples.length = 0;
      velSamples.push({ x: e.clientX, t: performance.now() });
      pointerId = e.pointerId;
      const el = e.currentTarget as HTMLElement;
      /* setPointerCapture 在指针已失效时会抛 NotFoundError（例如合成事件、
         或按下的同一帧指针被系统取消）。它抛在 dragging=true 之后，一旦冒出去
         整个轮播就永远停在「拖拽中」—— 再也切不了卡。这里吞掉异常即可：
         拿不到指针捕获只影响「手指移出视口后是否继续跟手」，不影响拖拽本身。 */
      try {
        el.setPointerCapture?.(e.pointerId);
      } catch {
        /* 忽略：无捕获也能正常拖拽，松手由 window pointerup 兜底 */
      }
      el.classList.add("dragging");
    }

    function onPointerMove(e: PointerEvent): void {
      if (!dragActive) return;
      if (pointerId !== null && e.pointerId !== pointerId) return;
      const dx = e.clientX - dragStartX;
      const dy = e.clientY - dragStartY;
      if (!horizLocked) {
        if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
        if (Math.abs(dy) > Math.abs(dx) * 1.2) {
          dragActive = false;
          dragging.value = false;
          dragX.value = dragBaseX;
          (e.currentTarget as HTMLElement).classList.remove("dragging");
          return;
        }
        horizLocked = true;
      }
      if (Math.abs(dx) >= 4) dragMoved = true;
      /* 位移 = 拖拽基准 + 本次手指位移（带阻尼）。
         基准通常为 0；若是在落位动画途中按下接管的，基准就是卡片当时
         的真实位置 —— 于是卡片从「现在的位置」继续跟手，不会瞬移。 */
      dragX.value = dragBaseX + resist(dx);
      const now = performance.now();
      velSamples.push({ x: e.clientX, t: now });
      if (velSamples.length > 5) velSamples.shift();
    }

    function finishDrag(): void {
      if (!dragActive) return;
      dragActive = false;
      horizLocked = false;
      dragging.value = false;
      const dx = dragX.value;
      const pid = pointerId;
      const wasSide = downWasSide;
      const startSlot = downSlot;
      pointerId = null;
      const el = stageEl.value;
      el?.classList.remove("dragging");
      if (pid !== null) el?.releasePointerCapture?.(pid);

      if (velSamples.length >= 2) {
        const first = velSamples[0];
        const last = velSamples[velSamples.length - 1];
        const dt = last.t - first.t;
        releaseVel = dt > 0 ? (last.x - first.x) / dt : 0;
      }

      const absVel = Math.abs(releaseVel);

      /* 侧卡上按下但没拖：当作「点一下切换」，落到被点的侧卡位。 */
      if (wasSide && !dragMoved && startSlot !== null && startSlot !== undefined) {
        animateTo(startSlot - index.value, dx);
        return;
      }

      /* 真正的拖拽：视觉中心 = index - dx/UNIT，与按下位置无关。
         （往右拖 dx>0 → 视觉中心减小 → 前一张进中央。） */
      const target = Math.round(index.value - dx / UNIT);
      let steps = target - index.value;

      const flick = absVel >= FLICK_VEL ? (releaseVel < 0 ? 1 : -1) : 0;
      if (steps === 0 && flick !== 0) steps = flick;

      animateTo(steps, dx);
    }

    function onPointerUp(e: PointerEvent): void {
      if (!dragActive) return;
      if (pointerId !== null && e.pointerId !== pointerId) return;
      finishDrag();
    }

    function onGlobalPointerUp(): void {
      if (!dragActive) return;
      finishDrag();
    }

    /** 读当前**实际**渲染出来的横向位移（px），用于动画途中被打断时的接续。
     *
     *  dragX 只是个目标值：落位动画一开始它就立刻被设成 0，真正的位置由 CSS
     *  在 .42s 内插值出来。此时若直接按 dragX(=0) 接续下一次切换，卡片会从
     *  「屏幕上现在的位置」瞬移到「理论上的原位」再开始滑 —— 就是连点时那种
     *  「咯噔一下」。所以这里读 computed translate，拿到肉眼看到的真实偏移。 */
    function currentOffsetPx(): number {
      if (!stageEl.value) return 0;
      const el = stageEl.value.querySelector<HTMLElement>(
        `.stage-card[data-slot="${index.value}"]`,
      );
      if (!el) return 0;
      const t = getComputedStyle(el).translate;
      const x = parseFloat(t);
      return Number.isFinite(x) ? x : 0;
    }

    /** 结束一次落位动画：解锁 + 补量一次台面高度 + 消化排队中的滚轮输入。 */
    function endSettle(): void {
      settling.value = false;
      /* 动画期间 measureDescs 故意不量中央卡（会量到过渡中的中间高度），
         所以等它真正结束后必须补量一次，否则高个子的卡片撑不开台面，
         底部「最近使用」会被压住。 */
      window.setTimeout(measureAll, 30);
      flushWheel();
    }

    /** 动画切换 |steps| 张（steps 为 0 表示回弹原位），并让 deck 平滑滑到新中心。
     *
     *  视觉中心 visualC = index - dragX / UNIT。落位时先把 index 跳到目标、
     *  同时把 dragX 设成「steps*UNIT + 当前残余位移 fromDx」，这样 visualC 在
     *  提交的瞬间**保持不变**（无跳变）；随后把 dragX 过渡回 0，deck 就从
     *  当前位置连续滑到新中心，不再有「先弹回去、再加载」的突兀感。
     *
     *  @param steps   目标中心相对当前 index 的偏移（卡位单位）
     *  @param fromDx  松手时的残余拖拽位移（px）；程序化切换传 0 */
    function animateTo(steps: number, fromDx = 0): void {
      const n = count.value;
      if (n === 0) return;
      /* 上一次落位动画还没结束就被再次触发（连点 / 快速滚轮）：
         此时卡片正处在「滑到一半」的位置，必须从它**肉眼所在的位置**接着滑，
         否则会先瞬移回原位再启动 —— 就是连点时的「咯噔一下」。
         读真实 translate 作为残余位移，视觉中心就能保持连续。 */
      const wasSettling = settling.value;
      if (settleTimer !== null) {
        clearTimeout(settleTimer);
        settleTimer = null;
      }
      if (wasSettling && steps !== 0 && fromDx === 0) fromDx = currentOffsetPx();
      const target = (index.value + steps + n * 100000) % n;
      settling.value = true;

      if (steps === 0) {
        /* 松手回弹：index 不变，只需把 dragX 过渡回 0。
           过渡已武装（finishDrag 里关掉了 dragging）。 */
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            dragX.value = 0;
            if (settleTimer !== null) clearTimeout(settleTimer);
            settleTimer = window.setTimeout(endSettle, SETTLE_MS);
          });
        });
        return;
      }

      /* 有位移：提交瞬间保持 visualC 连续。 */
      dragging.value = true;
      dragX.value = steps * UNIT + fromDx;
      index.value = target;
      const s = list.value[target];
      if (s && s.id !== state.selected?.id) trySelect(s.id);

      requestAnimationFrame(() => {
        dragging.value = false;
        requestAnimationFrame(() => {
          dragX.value = 0;
          if (settleTimer !== null) clearTimeout(settleTimer);
          settleTimer = window.setTimeout(endSettle, SETTLE_MS);
        });
      });
    }

    function stepTo(dir: number): void {
      if (count.value < 2) return;
      /* 只挡住「正在拖拽」（手指还按着，此时不该被程序改位置）。
         落位动画进行中**允许**再次切换：animateTo 会从卡片当前肉眼位置
         接着滑，连点/快速滚轮的手感是连续的，而不是被锁 580ms 干等。 */
      if (dragging.value) return;
      /* 运行中不许切卡（和拖拽、左侧目录同一道门禁） */
      if (isBusy()) return;
      animateTo(dir);
    }

    function onKey(dir: number): void {
      stepTo(dir);
    }

    function onDotClick(targetIndex: number): void {
      if (dragging.value) return;
      if (isBusy()) return;
      const steps = targetIndex - index.value;
      if (steps === 0) return;
      animateTo(steps);
    }

    /* 滚轮节流 + 排队：避免「快速滚动时第二次被 settling 锁挡掉」。
       wheel 事件是连续触发的（尤其触控板惯性滚动），一次滚动会来十几个
       deltaY。如果每次都在 settling 窗口里被丢弃，就会「滑不动」。
       这里把滚轮输入节流到 260ms 一次，落位动画期间记住最后方向，
       动画一结束立刻补上一次切换，手感连贯。 */
    let wheelThrottle = 0;
    let wheelPendingDir = 0;

    /* 滚轮切换的核心逻辑（被局部 @wheel 和全局 wheel 监听共用） */
    function handleWheelDir(dir: number): void {
      if (count.value < 2) return;
      /* 手指还按着时不动（拖拽优先），其余情况都允许立刻切换 ——
         落位动画进行中会从卡片当前位置接续，不再排队干等。 */
      if (dragging.value) {
        wheelPendingDir = dir;
        return;
      }
      const now = performance.now();
      if (now - wheelThrottle < 260) return;
      wheelThrottle = now;
      wheelPendingDir = 0;
      stepTo(dir);
    }

    /* 滚轮切换卡片**只**发生在中央舞台（.stage-viewport 的 @wheel）。
     *
     *  不做全局滚轮监听：鼠标在左侧分类、右侧日志、页面上下文中滚轮
     *  一律是正常的上下滚动，绝不劫持。这样「滚轮切卡片」和
     *  「滚轮滚动页面」的边界清晰，不会互相干扰。 */
    function onWheel(e: WheelEvent): void {
      /* 运行中卡片不能切，滚轮就别劫持了 —— 让它正常滚动页面 */
      if (isBusy()) return;
      const t = e.target as HTMLElement | null;
      /* 状态行一直 overflow-y:auto，内容超出时让它自己滚；不阻止默认行为，
         用户还能靠滚轮把整页挪下去看右侧日志。 */
      if (t && t.closest(".stage-runstate")) return;

      const delta = Math.abs(e.deltaX) >= Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (Math.abs(delta) < 4) return;   // 触控板小幅抖动忽略

      /* 描述区 / 「展开完整说明」按钮：既不切卡，也不让整页跟着跳。
       *
       * 只不切卡是不够的。之前这里直接 return，等于放弃 preventDefault，
       * 滚轮就落到页面上 —— 实测滚一下整页窜 215px，舞台连同标题一起上移，
       * 观感比切卡还糟。所以除非描述区真的能内部滚（长过 DESC_MAX 才加
       * .scrolls），否则把这一下滚轮吞掉。 */
      const inner = t && t.closest<HTMLElement>(".stage-card-desc, .stage-desc-more");
      if (inner) {
        const scrollsInside = inner.classList.contains("expanded") && inner.classList.contains("scrolls");
        if (!scrollsInside) e.preventDefault();
        return;
      }

      e.preventDefault();
      handleWheelDir(delta > 0 ? 1 : -1);
    }

    /* 落位动画结束后，如果期间有滚轮输入排队，补一次切换 */
    function flushWheel(): void {
      if (wheelPendingDir !== 0 && !settling.value && !dragging.value) {
        const dir = wheelPendingDir;
        wheelPendingDir = 0;
        stepTo(dir);
      }
    }

    function onFav(): void {
      if (!center.value) return;
      toggleFavorite(center.value.id);
    }

    /* 打开参数浮层：顺手把这个按钮的视口矩形记进 state，浮层 Teleport 到
     * body 之后要按它算位置（挂卡片里会被 .stage-card 的 overflow 裁掉）。
     * 同一个按钮再点一次就收起，行为跟下拉菜单一致。 */
    function openParams(e?: MouseEvent): void {
      if (!center.value) return;
      if (state.paramsOpen && state.paramsAnchorId === center.value.id) {
        state.paramsOpen = false;
        return;
      }
      const el = (e?.currentTarget as HTMLElement | null) ?? null;
      const r = el?.getBoundingClientRect();
      state.paramsAnchor = r
        ? { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }
        : null;
      state.paramsAnchorId = center.value.id;
      state.paramsOpen = true;
    }

    /* ── 描述展开 / 收起 ───────────────────────────────────────────
     * 卡片描述常常很长（触发方式那一大段），默认 4 行截断会以「…」结尾。
     *
     * 这里**只记「当前展开的是哪张卡」一个 id**，而不是一张 key→bool 的表。
     * 为什么换成这样：之前用 reactive<Record<id,bool>>，切卡后旧值仍留着，
     * 于是点「展开」时状态可能已经是 true —— 表现为「点了没反应 / 展开和收起
     * 高度一样」。单一 id 语义天然互斥：要么这张卡展开，要么没展开。
     * 切卡时由 watch 自动清空，保证每张卡都从收起态开始。 */
    const expandedDescId = ref<string>("");

    function isDescExpanded(id: string): boolean {
      return expandedDescId.value === id;
    }

    function toggleDesc(id: string): void {
      expandedDescId.value = expandedDescId.value === id ? "" : id;
    }

    /* 切换选中卡 → 收起上一张的展开态，避免状态串到新卡上 */
    watch(
      () => state.selected?.id,
      () => { expandedDescId.value = ""; },
    );

    /** 这段描述是否**真的**被截断了（需要「展开」按钮）。
     *
     *  不能按字符数猜：实测 90 字左右的中文在 410px 宽的卡里正好 4 行，按字数
     *  给按钮会出现「点了没变化」（内容本来就没超）。这里改成量 DOM：
     *  渲染后比较 scrollHeight 与 clientHeight，超出才显示按钮。
     *  用 ResizeObserver 跟随窗口尺寸变化重算。 */
    const descClamp: Record<string, boolean> = reactive({});
    /* 展开态该长到多高（px）：直接量内容真实高度，不给一个「足够大」的固定上限。
       给固定大值（原来是 60vh ≈ 540px）会有两个毛病：高度在动画前 15% 就冲过内容
       高度、后 85% 什么也不动，观感是「顿一下再窜出去」；而且 540px 会把下面的
       「最近使用」整条压掉。 */
    const descFull: Record<string, number> = reactive({});
    /* 当前展开让舞台台面多高（px）。台面跟着一起长高，「最近使用」被**推下去**
       而不是被盖住 —— 卡片在台面里垂直居中，台面长高多少、卡片就长高多少，
       上下边距始终是 42px，两边都不会顶到标题或最近使用。 */
    const stageGrow = ref(0);
    let descObserver: ResizeObserver | null = null;

    /* 收起态高度，与 _stage.scss 里 .stage-card-desc 的 max-height 保持一致 */
    const DESC_LINE = 100;
    /* 描述区最多长到多高；再长的内容在框内滚动 */
    const DESC_MAX = 300;

    /* 侧卡「可见文字块」居中补偿（px，逐卡）。
     *
     * 问题：侧卡是固定高度 + flex 垂直居中的，但卡里那些「在侧位已淡出」的
     * 元素（图标 glyph、一键运行操作区、状态行、规格行）**仍然占着布局空间**。
     * 于是被居中排版的是「整列内容」，而用户肉眼只看得到中间的标题+描述 ——
     * 可见文字块就整体偏上（实测偏 33~101px，随内容而变，所以写死常量修不了）。
     *
     * 做法：算出「侧位布局下，可见文字块的中心」与「卡片中心」的差，把这个差
     * 用 translate 补回去。补偿量随 --sl（|d| 0→1）连续生效，所以卡片从中央
     * 滑向侧边时文字是平滑下移的，不是到位后突然跳一下。
     *
     * 为什么能在「中央态」就把侧位的值算出来：可见块的内部几何（crumbs 位置、
     * 描述高度）与卡片处于中央还是侧位无关；唯一变化的 bodyTop 也能由各子元素
     * 高度 + 侧卡固定高度解析推出（实测 29 张卡误差 0px）。 */
    const sideLift: Record<string, number> = reactive({});

    function measureDescs(): void {
      if (!stageEl.value) return;
      let grow = 0;
      for (const el of stageEl.value.querySelectorAll<HTMLElement>(".stage-card-desc")) {
        const id = el.dataset.descId;
        if (!id) continue;
        const expanded = isDescExpanded(id);
        /* overflow:hidden 时 scrollHeight 仍然是整段文字的高度（内容没被删掉），
           所以收起态能拿它判断「是否被截断」，展开态也能拿它当真高。 */
        const full = Math.round(el.scrollHeight);
        const capped = Math.max(DESC_LINE, Math.min(DESC_MAX, full));
        descFull[id] = capped;
        el.style.setProperty("--desc-full", `${capped}px`);
        el.classList.toggle("scrolls", full > capped + 2);
        /* 展开态下 scrollHeight == clientHeight，不能据此清掉按钮，
           所以已展开的卡保持 true（仍需「收起」按钮）。 */
        const cut = full > DESC_LINE + 2;
        descClamp[id] = expanded || cut;
        /* 收起且确实被截断时，给最后一行加淡出遮罩 —— 4 行硬切会把半句话直接剁掉，
           看不出「下面还有」。 */
        el.classList.toggle("clipped", cut && !expanded);
        if (expanded) grow = capped - DESC_LINE;
      }

      /* 台面本身也得兜住那些「内容本来就高」的卡（最近音乐 542px，比台面还高）。
       * 卡片用 inset:0 + margin:auto，高出台面时溢出上下均分；台面网格到「最近使用」
       * 只有 22px 缝，溢出超过 12px 就会压到它头上。这里只补真正压住的那几像素，
       * 常见高度的卡（≤504）一点都不动，避免切卡时整页跟着抖。
       *
       * 注意 stageEl 的 ref 就挂在 .stage-viewport 上，所以这里**直接用它**，
       * querySelector(".stage-viewport") 只查后代、永远返回 null（踩过一次）。 */
      /* ⚠ 落位动画期间不要量中央卡高度。
         卡片高度现在是「从侧卡长度缓慢长成中央卡长度」的过渡态（.54s），
         动画途中 offsetHeight 只有中间值，量出来会把台面 --stage-grow 算小；
         等动画结束再量又是另一个值 —— 台面高度跟着抖两下，观感比卡顿还糟。
         所以动画期间沿用上一次的 grow，等 settling 结束后再补量一次。 */
      const centerCard = settling.value
        ? null
        : stageEl.value.querySelector<HTMLElement>(".stage-card.is-center");
      if (centerCard) {
        const cs = getComputedStyle(stageEl.value);
        const baseH =
          parseFloat(cs.getPropertyValue("--stage-card-h")) +
          parseFloat(cs.getPropertyValue("--stage-viewport-pad"));
        /* 必须用 offsetHeight 而不是 getBoundingClientRect：
           侧滑/落位时卡片带 scale(--scx/--scy)，rect 会量到被缩小的尺寸，
           于是「这张卡比台面高多少」被算小甚至算成 0，台面纹丝不动。 */
        const cardH = centerCard.offsetHeight;
        if (baseH > 0) grow = Math.max(grow, Math.round(cardH - baseH - 24));
      }

      if (stageGrow.value !== grow) stageGrow.value = Math.max(0, grow);
    }

    function descIsLong(id: string): boolean {
      return Boolean(descClamp[id]) || isDescExpanded(id);
    }

    /** 量出每张卡「在侧位时」可见文字块相对卡片中心的偏移，写入 sideLift。
     *
     *  侧卡高度固定（--stage-side-h）、内容 flex 垂直居中，但淡出元素仍占位，
     *  所以被居中的是整列内容、肉眼可见的标题+描述整体偏上。这里解析算出：
     *      bodyTop = padTop + free/2 + body 之前各子元素的高度和
     *      lift    = sideH/2 - (bodyTop + 可见块中心)
     *  其中「可见块」取 crumbs 顶 → desc 底（中间只有标题和描述是真可见的）。
     *
     *  关键：这些量（子元素高度、crumbs/desc 在 body 内的位置）都与卡片当前
     *  处于中央还是侧位**无关**，所以中央态就能算出侧位所需补偿，卡片滑过去
     *  之前补偿已经就绪，不会出现「到位后才突然对齐」的跳动。 */
    function measureSideLift(): void {
      const root = stageEl.value;
      if (!root) return;
      /* 侧卡高度用 CSS 变量解析算出，不能读 .stage-card.is-side 的 offsetHeight：
         卡片高度正处在「中央 max-content ↔ 侧卡固定高」的 .54s 过渡中，
         量到的是中间值（实测 400/413 这种），算出来的补偿会偏小。
         --stage-side-h 本身是 calc(396px + 24px)，parseFloat 拿不到值，
         所以拆成 --stage-card-h + --stage-side-extra 两个纯 px 变量相加。 */
      const cs = getComputedStyle(root);
      const baseH = parseFloat(cs.getPropertyValue("--stage-card-h"));
      const extraH = parseFloat(cs.getPropertyValue("--stage-side-extra"));
      const sideH = baseH + extraH;
      if (!(sideH > 0)) return;
      for (const card of root.querySelectorAll<HTMLElement>(".stage-card.is-deck")) {
        const id = card.dataset.cardId;
        if (!id) continue;
        const body = card.querySelector<HTMLElement>(".stage-card-body");
        const crumbs = card.querySelector<HTMLElement>(".stage-card-crumbs");
        const desc = card.querySelector<HTMLElement>(".stage-card-desc");
        if (!body || !crumbs || !desc) continue;

        /* 解析推算这张卡在侧位时会被摆到哪里 —— 不必等它真的滑过去。
           前提是「子元素高度与卡片处于中央还是侧位无关」，这一点由
           `.stage-card-glyph { flex: none }` 保证（否则图标会被压到 50px，
           推导整体偏 7~16px）。只累加两种卡态都存在的流式子元素：
           光晕 / 顶线是 v-if 只给中央卡的装饰，侧位没有，算进去会多 2px。 */
        const ccs = getComputedStyle(card);
        const padTop = parseFloat(ccs.paddingTop) || 0;
        const padBot = parseFloat(ccs.paddingBottom) || 0;
        const kids = (Array.from(card.children) as HTMLElement[]).filter((ch) => {
          const cls = ch.className;
          if (cls.includes("stage-card-glow") || cls.includes("stage-card-topline")) return false;
          return getComputedStyle(ch).position !== "absolute";
        });
        let stack = 0;
        for (const ch of kids) {
          stack += (parseFloat(getComputedStyle(ch).marginTop) || 0) + ch.offsetHeight;
        }
        /* 侧卡是 justify-content:center 的 flex 列，内容比固定高度高时
           free 为负、上下同时溢出，所以起点是 padTop + free/2。 */
        const free = sideH - (padTop + stack + padBot);
        let acc = padTop + free / 2;
        let bodyTop = NaN;
        for (const ch of kids) {
          acc += parseFloat(getComputedStyle(ch).marginTop) || 0;
          if (ch === body) { bodyTop = acc; break; }
          acc += ch.offsetHeight;
        }
        if (!Number.isFinite(bodyTop)) continue;

        /* crumbs / desc 的 offsetTop 是相对 body 的，和 bodyTop（相对卡片）
           相加得到可见块在卡片坐标系里的位置。 */
        const visTop = crumbs.offsetTop;
        const visBot = desc.offsetTop + desc.offsetHeight;
        const lift = sideH / 2 - (bodyTop + (visTop + visBot) / 2);
        /* 只留一位小数，且 1px 内的抖动直接归零 —— 避免 ResizeObserver
           反复触发时把整列文字来回挪半个像素。 */
        const v = Math.abs(lift) < 1 ? 0 : Math.round(lift * 10) / 10;
        if (sideLift[id] !== v) sideLift[id] = v;
      }
    }

    /** 一次把「描述高度」和「侧位补偿」都量好（两者都依赖同样的 DOM 变化） */
    function measureAll(): void {
      measureDescs();
      measureSideLift();
    }

    onMounted(() => {
      descObserver = new ResizeObserver(() => measureAll());
      if (stageEl.value) descObserver.observe(stageEl.value);
      window.setTimeout(measureAll, 60);
    });
    onBeforeUnmount(() => {
      descObserver?.disconnect();
      descObserver = null;
    });
    /* 卡片内容变化（切卡 / 打字改参数）后重算一次 */
    watch(
      () => [state.selected?.id, index.value, expandedDescId.value],
      () => { window.setTimeout(measureAll, 40); },
    );

    /** 设备前置条件门禁：节日卡要 OOBE=中国、停电卡要 root。
     *  判断逻辑集中在 actions/oobe.ts，这里只取当前居中场景的原因/短文案。 */
    const oobeBlock = computed(() => oobeBlockReason(center.value));
    const oobeBlockTxt = computed(() => oobeBlockLabel(center.value));

    function onRun(): void {
      if (!center.value) return;
      if (state.runDisabled) return;
      if (center.value.unsupported_note) {
        toast(center.value.unsupported_note, true);
        return;
      }
      if (oobeBlock.value) {
        toast(oobeBlock.value, true);
        return;
      }
      void runScenario();
    }

    /** 运行中才露出「暂停 / 取消」：只有正在跑的这场才有可暂停/可结束的东西。
     *  暂停态取 state.paused（poll 每轮同步，pause/resume 事件也会即时改）。 */
    const runningNow = computed(() => state.running || state.starting);

    function onPause(): void {
      if (!runningNow.value) return;
      void pauseOrResume();
    }

    function onStop(): void {
      if (!runningNow.value) return;
      state.stopOpen = true;   // ModalStop 挂在 App.vue，确认后走 stopRun()
    }

    onMounted(() => {
      syncIndex();
      window.addEventListener("pointerup", onGlobalPointerUp);
      window.addEventListener("blur", onGlobalPointerUp);
    });
    onBeforeUnmount(() => {
      dragActive = false;
      dragging.value = false;
      if (settleTimer !== null) clearTimeout(settleTimer);
      window.removeEventListener("pointerup", onGlobalPointerUp);
      window.removeEventListener("blur", onGlobalPointerUp);
    });

    return {
      state,
      list,
      index,
      count,
      pos,
      center,
      tone,
      paramCount,
      favorited,
      runningThis,
      runLabel,
      dragging,
      settling,
      stageEl,
      deck,
      deckStyle,
      isCenterSlot,
      sideTone,
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onWheel,
      onKey,
      onDotClick,
      onFav,
      openParams,
      onRun,
      runningNow,
      onPause,
      onStop,
      oobeBlock,
      oobeBlockTxt,
      isDescExpanded,
      toggleDesc,
      descIsLong,
      stageGrow,
      iconBody,
      artFor,
      specVal,
      pad2,
    };
  },
});
</script>

<template>
  <section
    class="stage reveal"
    :style="{ '--g-tone': tone }"
    aria-label="场景卡片轮播"
  >
    <!-- 头部：标题 + 位置指示器 -->
    <div class="stage-head">
      <div class="stage-title">
        <span class="stage-kicker">{{ center ? center._group : "SCENARIO" }}</span>
        <h2 class="stage-name">{{ center ? center.title : "正在载入场景…" }}</h2>
      </div>
      <div class="stage-pos" role="status" aria-live="polite">
        <span class="stage-pos-num">{{ pos }}</span>
        <span class="stage-dots" aria-hidden="true">
          <i
            v-for="n in count"
            :key="n"
            class="dot"
            :class="{ on: n - 1 === index }"
            @click="onDotClick(n - 1)"
          />
        </span>
      </div>
    </div>

    <!-- 轮播舞台 -->
    <div
      ref="stageEl"
      class="stage-viewport"
      :class="{ dragging, settling }"
      :style="{ '--stage-grow': `${stageGrow}px` }"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @wheel="onWheel"
    >
      <!-- 空状态 -->
      <div v-if="count === 0" class="stage-empty">
        <span class="stage-empty-glyph" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
            <circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.2 4.2M8.5 11h5" />
          </svg>
        </span>
        <p>没有匹配的场景</p>
        <span>换个关键词，或看看别的分类</span>
      </div>

      <template v-else>
        <!-- 统一卡元素：中央卡和侧卡用同一个 <article>，只是 class 不同。
             这样切换时 Vue 复用节点，内容不卸载、只靠 opacity/transform 渐隐渐显，
             彻底消除「松手瞬间内容突然消失再加载」的跳变。 -->
        <article
          v-for="it in deck"
          :key="it.key"
          class="stage-card is-deck glow-target"
          :class="{ 'is-center': isCenterSlot(it), 'is-side': !isCenterSlot(it) }"
          :data-slot="it.slot"
          :data-card-id="it.card.id"
          :style="deckStyle(it)"
        >
          <span v-if="isCenterSlot(it)" class="stage-card-glow" aria-hidden="true" />
          <span v-if="isCenterSlot(it)" class="stage-card-topline" aria-hidden="true" />
          <span class="stage-card-glyph" aria-hidden="true">
            <img v-if="artFor(it.card.id)" :src="artFor(it.card.id)" alt="" loading="lazy" decoding="async" />
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" :stroke-width="isCenterSlot(it) ? 1.6 : 1.5" stroke-linecap="round" stroke-linejoin="round" v-html="iconBody(it.card)" />
          </span>

          <div class="stage-card-body">
            <div class="stage-card-crumbs">
              <span class="crumb-group">{{ it.card._group }}</span>
              <span class="crumb-dot" aria-hidden="true" />
              <span class="crumb-no">SCENARIO {{ pad2(it.card._no) }}</span>
            </div>
            <h3 class="stage-card-title">{{ it.card.title }}</h3>
            <p
              class="stage-card-desc"
              :class="{ expanded: isDescExpanded(it.card.id) }"
              :data-desc-id="it.card.id"
            >{{ it.card.desc || "—" }}</p>
            <button
              v-if="descIsLong(it.card.id)"
              class="stage-desc-more"
              type="button"
              :disabled="!isCenterSlot(it)"
              :aria-expanded="isDescExpanded(it.card.id)"
              :tabindex="isCenterSlot(it) ? undefined : -1"
              @click.stop="isCenterSlot(it) && toggleDesc(it.card.id)"
            >
              <span>{{ isDescExpanded(it.card.id) ? "收起" : "展开完整说明" }}</span>
              <svg
                class="caret"
                :class="{ up: isDescExpanded(it.card.id) }"
                viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>

            <div v-if="it.card.specs && it.card.specs.length" class="stage-card-specs">
              <span
                v-for="sp in it.card.specs"
                :key="sp.k"
                class="stage-spec"
                :class="{ live: Boolean(sp.from) }"
              >
                <i>{{ sp.k }}</i>
                <b>{{ specVal(sp, it.card) }}</b>
              </span>
            </div>

            <div v-if="it.card.unsupported_note" class="stage-unsupported">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M12 8.5v5M12 17.2v.1" /><path d="M10.3 4.4 3.5 16.2A1.9 1.9 0 0 0 5.2 19h13.6a1.9 1.9 0 0 0 1.7-2.8L13.7 4.4a1.9 1.9 0 0 0-3.4 0z" />
              </svg>
              {{ it.card.unsupported_note }}
            </div>
          </div>

          <!-- 操作区：中央卡可交互，侧卡只保留视觉（富内容随 --rich 淡出） -->
          <div class="stage-actions">
            <button
              class="commit stage-run"
              :class="{ busy: state.runBusy }"
              type="button"
              :disabled="!isCenterSlot(it) || state.runDisabled || Boolean(it.card.unsupported_note) || Boolean(isCenterSlot(it) && oobeBlock)"
              :title="isCenterSlot(it) && oobeBlock ? oobeBlock : undefined"
              :tabindex="isCenterSlot(it) ? undefined : -1"
              @click="isCenterSlot(it) && onRun()"
            >
              <svg class="play" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M8.5 5.8c0-.8.9-1.3 1.6-.9l8.2 5.9c.6.4.6 1.3 0 1.7l-8.2 5.9c-.7.4-1.6-.1-1.6-.9z" />
              </svg>
              <span class="lbl">{{ it.card.unsupported_note ? "此机型不支持" : (isCenterSlot(it) && oobeBlock ? oobeBlockTxt : (runningThis ? "运行中" : state.runLabel)) }}</span>
              <span class="spin" aria-hidden="true" />
            </button>

            <!-- 运行中才出现：暂停/继续 + 取消执行。只在中央卡露出，取消走 ModalStop 二次确认。 -->
            <button
              v-if="runningNow && isCenterSlot(it)"
              class="stage-icbtn"
              :class="{ on: state.paused }"
              type="button"
              :title="state.paused ? '继续执行' : '暂停执行'"
              :tabindex="isCenterSlot(it) ? undefined : -1"
              @click="isCenterSlot(it) && onPause()"
            >
              <svg v-if="state.paused" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M8.5 5.8c0-.8.9-1.3 1.6-.9l8.2 5.9c.6.4.6 1.3 0 1.7l-8.2 5.9c-.7.4-1.6-.1-1.6-.9z" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <rect x="7" y="5" width="3.6" height="14" rx="1.2" />
                <rect x="13.4" y="5" width="3.6" height="14" rx="1.2" />
              </svg>
            </button>

            <button
              v-if="runningNow && isCenterSlot(it)"
              class="stage-icbtn danger"
              type="button"
              title="取消执行"
              :tabindex="isCenterSlot(it) ? undefined : -1"
              @click="isCenterSlot(it) && onStop()"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true">
                <path d="M6.4 6.4l11.2 11.2M17.6 6.4L6.4 17.6" />
              </svg>
            </button>

            <button
              class="stage-icbtn"
              :class="{ on: favorited }"
              type="button"
              :aria-pressed="favorited"
              :title="favorited ? '取消收藏' : '收藏'"
              :tabindex="isCenterSlot(it) ? undefined : -1"
              @click="isCenterSlot(it) && onFav()"
            >
              <svg v-if="favorited" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 20.4S4.6 16 4.6 10.9A4.1 4.1 0 0 1 12 8.2a4.1 4.1 0 0 1 7.4 2.7c0 5.1-7.4 9.5-7.4 9.5z" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M12 20.4S4.6 16 4.6 10.9A4.1 4.1 0 0 1 12 8.2a4.1 4.1 0 0 1 7.4 2.7c0 5.1-7.4 9.5-7.4 9.5z" />
              </svg>
            </button>

            <button
              class="stage-icbtn params-btn"
              :class="{ on: state.paramsOpen && state.paramsAnchorId === it.card.id }"
              type="button"
              data-params-anchor
              :aria-haspopup="'dialog'"
              :aria-expanded="state.paramsOpen && state.paramsAnchorId === it.card.id ? 'true' : 'false'"
              :title="paramCount ? `调整参数（${paramCount} 项）` : '无参数'"
              :tabindex="isCenterSlot(it) ? undefined : -1"
              @click="isCenterSlot(it) && openParams($event)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h7M15 18h5" />
                <circle cx="16" cy="6" r="2" /><circle cx="8" cy="12" r="2" /><circle cx="13" cy="18" r="2" />
              </svg>
              <span v-if="paramCount" class="stage-icbadge">{{ paramCount }}</span>
            </button>
          </div>

          <div class="stage-progress" v-if="runningThis || state.progress > 0">
            <div class="progress" aria-hidden="true">
              <div
                class="bar"
                :class="{ ok: state.runTone === 'ok', fail: state.runTone === 'fail' }"
                :style="{ width: Math.round(state.progress * 100) + '%' }"
              />
            </div>
            <span class="elapsed">{{ state.elapsedText }}</span>
          </div>

          <div class="stage-runstate" :class="state.runTone" role="status" aria-live="polite">
            {{ state.runStateText }}
          </div>
        </article>
      </template>
    </div>
  </section>
</template>

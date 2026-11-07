<script lang="ts">
import { computed, defineComponent, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { state } from "@/stores/core";
import type { ScenarioView } from "@/types/api";
import { currentVisible, trySelect, isFavorite, toggleFavorite } from "@/actions/catalog";
import { iconBody } from "@/lib/icons";
import { pad2 } from "@/lib/format";
import { artFor } from "@/actions/cards";
import { runScenario } from "@/actions/run";
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
const SETTLE_MS = 520;   // 松手/切换落位动画时长

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
      const scx = Math.max(0.6, 1 - Math.abs(d) * 0.22);
      const scy = Math.max(0.6, 1 - Math.abs(d) * 0.30);
      const opacity = Math.max(0, Math.min(1, 1 - Math.abs(d) * 0.5));
      const zi = Math.max(1, 5 - Math.round(Math.abs(d) * 2));
      /* 文字随 |d| 渐入渐出：中央全显，侧边降到底限 0.25（仍能看到标题） */
      const txop = Math.max(0.25, Math.min(1, 1 - Math.abs(d) * 0.75));
      /* 富内容：|d|≤0.5 之间线性 0→1，超出就完全隐掉（只属于中央卡） */
      const rich = Math.max(0, Math.min(1, (0.5 - Math.abs(d)) / 0.5));
      /* UI 图：侧卡时（|d|→1）抬到更靠上、保持可见；中央（d=0）落回原位。
         移动方向：拖拽换卡时图标随卡片往侧边移动并缓慢上移。 */
      const glyY = (Math.abs(d) * 26).toFixed(1);
      return {
        "--so": `${x.toFixed(1)}px`,
        "--scx": scx.toFixed(3),
        "--scy": scy.toFixed(3),
        "--op": opacity.toFixed(3),
        "--txop": txop.toFixed(3),
        "--rich": rich.toFixed(3),
        "--gly": `${glyY}px`,
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
      return { ...it.style, "--g-tone": sideTone(it.card) };
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
      if (settling.value) return;
      if (e.button !== 0) return;
      const t = e.target as HTMLElement | null;
      /* 侧卡也是可拖拽的：允许在侧卡上按下开始拖拽。
         但卡内的按钮/链接仍照常响应点击，不拦截。 */
      if (t && t.closest("a, input, select, textarea, .stage-actions")) return;

      const sideEl = t?.closest<HTMLElement>(".stage-card.is-side") ?? null;
      downWasSide = !!sideEl;
      downSlot = sideEl ? Number(sideEl.dataset.slot ?? NaN) : null;
      if (downWasSide && !Number.isFinite(downSlot)) downSlot = null;
      dragMoved = false;

      dragActive = true;
      horizLocked = false;
      dragging.value = true;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      dragX.value = 0;
      releaseVel = 0;
      velSamples.length = 0;
      velSamples.push({ x: e.clientX, t: performance.now() });
      pointerId = e.pointerId;
      const el = e.currentTarget as HTMLElement;
      el.setPointerCapture?.(e.pointerId);
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
          dragX.value = 0;
          (e.currentTarget as HTMLElement).classList.remove("dragging");
          return;
        }
        horizLocked = true;
      }
      if (Math.abs(dx) >= 4) dragMoved = true;
      dragX.value = resist(dx);
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
      const target = (index.value + steps + n * 100000) % n;
      settling.value = true;

      if (steps === 0) {
        /* 松手回弹：index 不变，只需把 dragX 过渡回 0。
           过渡已武装（finishDrag 里关掉了 dragging）。 */
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            dragX.value = 0;
            if (settleTimer !== null) clearTimeout(settleTimer);
            settleTimer = window.setTimeout(() => {
              settling.value = false;
              flushWheel();
            }, SETTLE_MS);
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
          settleTimer = window.setTimeout(() => {
            settling.value = false;
            flushWheel();
          }, SETTLE_MS);
        });
      });
    }

    function stepTo(dir: number): void {
      if (count.value < 2) return;
      if (settling.value || dragging.value) return;
      animateTo(dir);
    }

    function onKey(dir: number): void {
      stepTo(dir);
    }

    function onDotClick(targetIndex: number): void {
      if (settling.value || dragging.value) return;
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
      const now = performance.now();
      if (settling.value || dragging.value) {
        wheelPendingDir = dir;
        return;
      }
      if (now - wheelThrottle < 260) {
        wheelPendingDir = dir;
        return;
      }
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
      const delta = Math.abs(e.deltaX) >= Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (Math.abs(delta) < 4) return;   // 触控板小幅抖动忽略
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

    function openParams(): void {
      if (!center.value) return;
      state.paramsOpen = true;
    }

    function onRun(): void {
      if (!center.value) return;
      if (state.runDisabled) return;
      if (center.value.unsupported_note) {
        toast(center.value.unsupported_note, true);
        return;
      }
      void runScenario();
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
      iconBody,
      artFor,
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
      :class="{ dragging }"
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
            <p class="stage-card-desc">{{ it.card.desc || "—" }}</p>

            <div v-if="it.card.specs && it.card.specs.length" class="stage-card-specs">
              <span v-for="sp in it.card.specs" :key="sp.k" class="stage-spec">
                <i>{{ sp.k }}</i>
                <b>{{ sp.v ?? (sp.from ? "—" : "") }}</b>
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
              :disabled="!isCenterSlot(it) || state.runDisabled || Boolean(it.card.unsupported_note)"
              :tabindex="isCenterSlot(it) ? undefined : -1"
              @click="isCenterSlot(it) && onRun()"
            >
              <svg class="play" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M8.5 5.8c0-.8.9-1.3 1.6-.9l8.2 5.9c.6.4.6 1.3 0 1.7l-8.2 5.9c-.7.4-1.6-.1-1.6-.9z" />
              </svg>
              <span class="lbl">{{ it.card.unsupported_note ? "此机型不支持" : (runningThis ? "运行中" : state.runLabel) }}</span>
              <span class="spin" aria-hidden="true" />
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
              class="stage-icbtn"
              type="button"
              :title="paramCount ? `调整参数（${paramCount} 项）` : '无参数'"
              :tabindex="isCenterSlot(it) ? undefined : -1"
              @click="isCenterSlot(it) && openParams()"
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

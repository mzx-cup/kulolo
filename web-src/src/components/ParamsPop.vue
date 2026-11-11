<script lang="ts">
import {
  computed,
  defineComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { state } from "@/stores/core";
import type { ScenarioParam } from "@/types/api";
import { resetParams, setParam } from "@/actions/params";
import { resetRunUi } from "@/actions/session";
import { toast } from "@/actions/toast";
import { replayClass } from "@/lib/dom";
import SelectMenu from "@/components/SelectMenu.vue";

/** 浮层与锚点按钮之间的间距（px） */
const GAP = 12;
/** 浮层与视口边缘至少留出的空白 */
const EDGE = 12;
/** 期望宽度：够放「标签 + 输入框」，又不至于糊住半张卡 */
const WIDTH = 344;
/** 最高多少，超出在内部滚 */
const MAX_H = 430;

/**
 * 运行参数浮层。
 *
 * 交互形态是「贴着按钮的下拉菜单」：点中间卡右侧那几个滑块图标，
 * 面板从**按钮右方**展开、向右生长，顶端与按钮对齐；不像原来的抽屉
 * 那样占满整屏高、还带一层盖住整页的遮罩。
 *
 * 为什么必须 Teleport 到 body + position: fixed：
 * 卡片（.stage-card）与舞台视口都带 overflow，浮层挂在卡片里会先被裁掉
 * ——裁剪发生在层叠之前，调 z-index 没用（SelectMenu 里踩过同一个坑）。
 * 代价是要按按钮矩形自己算坐标，并在滚动 / 缩放 / 布局变化时重算。
 */
export default defineComponent({
  name: "ParamsPop",
  components: { SelectMenu },
  setup() {
    const sel = computed(() => state.selected);
    const params = computed<ScenarioParam[]>(() => sel.value?.params ?? []);

    const panel = ref<HTMLElement | null>(null);
    const style = ref<Record<string, string>>({});
    /** 面板朝哪边展开：right=按钮右侧（默认），left=空间不够时翻到左侧 */
    const side = ref<"right" | "left">("right");

    /** 锚点按钮当前的视口矩形。
     *  state 里那份是点击瞬间的快照，页面滚动或布局变化后就过期了，
     *  所以每次都优先回 DOM 里量一次；量不到（按钮被销毁）才退回快照。 */
    function anchorRect(): { left: number; top: number; right: number; bottom: number; width: number; height: number } | null {
      const el = document.querySelector<HTMLElement>(".stage-card.is-center [data-params-anchor]");
      if (el) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
          return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
        }
      }
      return state.paramsAnchor;
    }

    /** 按锚点按钮的视口矩形算出面板位置；右边放不下就翻到左边 */
    function place(): void {
      const a = anchorRect();
      if (!a) return;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const width = Math.min(WIDTH, vw - EDGE * 2);

      let nextSide: "right" | "left" = "right";
      let left = a.right + GAP;
      if (left + width > vw - EDGE) {
        const flipped = a.left - GAP - width;
        if (flipped >= EDGE) {
          left = flipped;
          nextSide = "left";
        } else {
          /* 两侧都放不下：夹在视口里，优先靠右 */
          left = Math.max(EDGE, vw - width - EDGE);
        }
      }
      side.value = nextSide;

      /* 垂直方向：面板顶端对齐按钮顶端，再往下夹回视口内。
       * 先按「按钮下方还有多少空间」限高，避免面板探出屏幕却在内部空白。 */
      const roomBelow = vh - a.top - EDGE;
      const maxH = Math.max(200, Math.min(MAX_H, roomBelow));
      const h = Math.min(panel.value?.offsetHeight ?? maxH, maxH);
      let top = a.top;
      if (top + h > vh - EDGE) top = vh - EDGE - h;
      if (top < EDGE) top = EDGE;

      /* 连接处的琥珀色短线始终对准按钮中心 */
      const accentY = Math.max(10, a.top + a.height / 2 - top - 10);

      style.value = {
        left: `${Math.round(left)}px`,
        top: `${Math.round(top)}px`,
        width: `${Math.round(width)}px`,
        maxHeight: `${Math.round(maxH)}px`,
        "--arrow-y": `${Math.round(accentY)}px`,
      };
    }

    function close(): void {
      state.paramsOpen = false;
    }

    function onReset(): void {
      if (!sel.value) return;
      resetParams();
      resetRunUi();
      toast("已恢复默认参数");
    }

    function onInput(p: ScenarioParam, e: Event): void {
      const el = e.target as HTMLInputElement;
      setParam(p.key, el.value);
      replayClass(el, "pop", 220);
    }

    function onTimePart(p: ScenarioParam, part: "h" | "m", e: Event): void {
      const el = e.target as HTMLInputElement;
      setParam(`${p.key}.${part}`, el.value);
      replayClass(el, "pop", 220);
    }

    function onSelect(p: ScenarioParam, value: string): void {
      setParam(p.key, value);
    }

    function timeH(p: ScenarioParam): string {
      return state.params[`${p.key}.h`] ?? String(p.h ?? 9);
    }
    function timeM(p: ScenarioParam): string {
      return state.params[`${p.key}.m`] ?? String(p.m ?? 30);
    }

    /** 点外面关掉。锚点按钮、面板自身、面板里 SelectMenu 的浮层（也挂在 body 上）都要放行 */
    function onDocClick(e: MouseEvent): void {
      if (!state.paramsOpen) return;
      const t = e.target as HTMLElement | null;
      if (!t) return;
      if (panel.value?.contains(t)) return;
      if (t.closest("[data-params-anchor]")) return;
      if (t.closest(".sel-menu")) return;
      state.paramsOpen = false;
    }

    /** fixed 定位不会跟着页面滚，滚动 / 缩放时重算 */
    function onViewportChange(): void {
      if (state.paramsOpen) place();
    }

    /* 切卡就把面板收起来：面板里的字段属于上一张卡，留着会张冠李戴。
       内容变化导致面板高度变了，也要重新夹一次视口。 */
    watch(
      () => state.selected?.id,
      () => { state.paramsOpen = false; },
    );
    watch(
      () => state.paramsOpen,
      (open) => {
        if (!open) return;
        place();
        void nextTick(() => { place(); void nextTick(place); });
      },
    );
    watch(params, () => {
      if (state.paramsOpen) void nextTick(place);
    });

    onMounted(() => {
      document.addEventListener("click", onDocClick, true);
      window.addEventListener("scroll", onViewportChange, true);
      window.addEventListener("resize", onViewportChange);
    });
    onBeforeUnmount(() => {
      document.removeEventListener("click", onDocClick, true);
      window.removeEventListener("scroll", onViewportChange, true);
      window.removeEventListener("resize", onViewportChange);
    });

    return {
      state, sel, params, panel, style, side,
      onReset, onInput, onTimePart, onSelect, timeH, timeM, close,
    };
  },
});
</script>

<template>
  <Teleport to="body">
    <transition name="ppop">
      <div
        v-if="state.paramsOpen"
        ref="panel"
        class="params-pop"
        :class="`side-${side}`"
        role="dialog"
        aria-label="运行参数"
        :style="style"
      >
        <div class="ppop-head">
          <div class="ppop-title">
            <span class="ppop-kicker">运行参数 <em>parameters</em></span>
            <h4>{{ sel ? sel.title : "参数配置" }}</h4>
          </div>
          <button class="icon-btn sm" type="button" aria-label="关闭参数浮层" @click="close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>

        <div class="ppop-body">
          <div class="params">
            <span v-if="!params.length" class="no-params">这个场景没有可调参数，直接点「一键运行」即可。</span>

            <label v-for="(p, i) in params" :key="p.key" class="field" :class="{ grow: p.type === 'text' }" :style="{ '--i': String(i) }">
              <span class="lbl">{{ p.label }}</span>

              <template v-if="p.type === 'time'">
                <input :id="`pp-${p.key}-hour`" class="w2" type="number" inputmode="numeric" min="0" max="23" :value="timeH(p)" :aria-label="`${p.label} · 时`" @input="onTimePart(p, 'h', $event)" />
                <span class="sep">:</span>
                <input :id="`pp-${p.key}-min`" class="w2" type="number" inputmode="numeric" min="0" max="59" :value="timeM(p)" :aria-label="`${p.label} · 分`" @input="onTimePart(p, 'm', $event)" />
              </template>

              <template v-else-if="p.type === 'select'">
                <SelectMenu
                  :id="`pp-${p.key}`"
                  :label="p.label"
                  :options="(p.options ?? []).map((o) => ({ v: String(o.v), t: o.t }))"
                  :model-value="state.params[p.key] ?? String(p.value ?? '')"
                  @update:model-value="(v: string) => onSelect(p, v)"
                />
              </template>

              <template v-else>
                <input
                  :id="`pp-${p.key}`"
                  :type="p.type === 'number' ? 'number' : 'text'"
                  :inputmode="p.type === 'number' ? 'numeric' : undefined"
                  :min="p.type === 'number' ? p.min : undefined"
                  :max="p.type === 'number' ? p.max : undefined"
                  :placeholder="p.type === 'text' ? (p.placeholder ?? '') : undefined"
                  :autocomplete="p.type === 'text' ? 'off' : undefined"
                  :spellcheck="p.type === 'text' ? false : undefined"
                  :value="state.params[p.key] ?? ''"
                  @input="onInput(p, $event)"
                />
                <span v-if="p.unit" class="unit">{{ p.unit }}</span>
              </template>
            </label>
          </div>
        </div>

        <div class="ppop-foot">
          <button class="link-btn" type="button" :hidden="params.length === 0" @click="onReset">重置默认</button>
          <button class="btn ghost" type="button" @click="close">完成</button>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

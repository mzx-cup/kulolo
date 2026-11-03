<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import type { ScenarioParam, ScenarioSpec } from "@/types/api";
import { collectParams, resetParams, setParam, specValue } from "@/actions/params";
import { runScenario, pauseOrResume } from "@/actions/run";
import { resetRunUi } from "@/actions/session";
import { toast } from "@/actions/toast";
import { refs } from "@/lib/refs";
import { pad2 } from "@/lib/format";
import { replayClass } from "@/lib/dom";
import SelectMenu from "@/components/SelectMenu.vue";

/** 主面板。class 名与原 web/index.html + web/style.css 严格一致，
 *  改动这里的任何 class 都会让样式表里的选择器落空。 */
export default defineComponent({
  name: "HeroPanel",
  components: { SelectMenu },
  setup() {
    const sel = computed(() => state.selected);
    const params = computed<ScenarioParam[]>(() => sel.value?.params ?? []);

    /** 分组强调色，驱动 .crumb-group 与 .hero 的 --g-tone */
    const groupTone = computed(() => {
      const g = state.groups.find((x) => x.name === sel.value?._group);
      return g?.tone ?? "var(--tone-amber)";
    });

    /** 面包屑右侧的编号，原实现是 "SCENARIO 01" */
    const eyebrow = computed(() =>
      sel.value ? `SCENARIO ${pad2(sel.value._no)}` : "SCENARIO",
    );

    const progressPct = computed(() => state.progress * 100);

    /** 进度条色调：跑完变绿、失败变红，其余保持琥珀 */
    const barClass = computed(() => {
      if (state.runTone === "ok") return "bar ok";
      if (state.runTone === "fail") return "bar fail";
      return "bar";
    });

    function onRun(): void {
      if (state.runDisabled) return;
      void runScenario();
    }

    function onReset(): void {
      if (!sel.value) return;
      resetParams();
      resetRunUi();
      toast("已恢复默认参数");
    }

    /* ── 参数表单 ─────────────────────────────────────────────────── */

    /** 数字/文本输入：写 store，规格行靠 computed 跟随；
     *  顺手给自己补一次 .pop 缩放动效（原实现同样做在 input 上） */
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

    /** 规格行的显示值；from 指向某参数时取那个参数的当前值，
     *  prefix / suffix 也要一起带上（旧实现是 `${prefix||""}${val}${suffix||""}`） */
    function specVal(sp: ScenarioSpec): string {
      return specValue(sp);
    }

    /** from 型规格行带 .pop，表示这是「跟着输入实时变」的活值 */
    const hasLiveSpec = computed(() => (sel.value?.specs ?? []).some((sp) => sp.from));

    return {
      state,
      sel,
      params,
      groupTone,
      eyebrow,
      progressPct,
      barClass,
      hasLiveSpec,
      onRun,
      onReset,
      onInput,
      onTimePart,
      onSelect,
      timeH,
      timeM,
      specVal,
      collectParams,
      pauseOrResume,
      pad2,
    };
  },
  mounted() {
    refs.heroMainEl = (this.$refs.main as HTMLElement | undefined) ?? null;
  },
});
</script>

<template>
  <section
    id="hero"
    class="panel hero reveal"
    :style="{ '--i': '0', '--g-tone': groupTone }"
  >
    <div class="hero-main" ref="main">
      <div class="crumbs">
        <span id="sc-group" class="crumb-group">{{ sel ? sel._group : "—" }}</span>
        <span class="crumb-dot" aria-hidden="true" />
        <span id="sc-eyebrow" class="crumb-no">{{ eyebrow }}</span>
      </div>
      <h2 id="sc-title">{{ sel ? sel.title : "—" }}</h2>
      <p id="sc-desc" class="lede">{{ sel ? sel.desc : "正在载入场景…" }}</p>
      <ul id="spec" class="spec">
        <li v-for="sp in sel ? sel.specs : []" :key="sp.k">
          <span class="k">{{ sp.k }}</span>
          <span class="v" :class="{ pop: sp.from ? true : false }">{{ specVal(sp) }}</span>
        </li>
      </ul>
    </div>

    <div class="hero-act">
      <button
        id="btn-run"
        class="commit"
        :class="{ busy: state.runBusy }"
        type="button"
        :disabled="state.runDisabled"
        @click="onRun"
      >
        <svg class="play" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M8.5 5.8c0-.8.9-1.3 1.6-.9l8.2 5.9c.6.4.6 1.3 0 1.7l-8.2 5.9c-.7.4-1.6-.1-1.6-.9z" />
        </svg>
        <span class="lbl">{{ state.runLabel }}</span>
        <span class="spin" aria-hidden="true" />
        <span class="kbd">Ctrl ↑</span>
      </button>

      <span id="ctrl-btns" class="ctrl-btns" :hidden="!(state.running || state.starting)">
        <button id="btn-pause" class="btn ghost" type="button" @click="pauseOrResume">
          {{ state.paused ? "继续" : "暂停" }}
        </button>
        <button
          id="btn-stop"
          class="btn ghost danger"
          type="button"
          @click="state.stopOpen = true"
        >
          结束
        </button>
      </span>

      <p id="runstate" class="runstate" :class="state.runTone" role="status" aria-live="polite">
        {{ state.runStateText }}
      </p>
    </div>

    <div class="progress-row">
      <span class="progress-label">进度 <em id="prog-pct">{{ Math.round(progressPct) }}%</em></span>
      <div class="progress" aria-hidden="true">
        <div id="prog" :class="barClass" :style="{ width: progressPct.toFixed(1) + '%' }" />
      </div>
      <span id="elapsed" class="elapsed">{{ state.elapsedText }}</span>
    </div>

    <div class="params-wrap">
      <div class="params-head">
        <span class="params-kicker">运行参数 <em>parameters</em></span>
        <button
          id="btn-reset"
          class="link-btn"
          type="button"
          :hidden="params.length === 0"
          @click="onReset"
        >
          重置默认
        </button>
      </div>

      <div id="params" class="params">
        <span v-if="!params.length" class="no-params">
          这个场景没有可调参数，直接点「一键运行」即可。
        </span>

        <label
          v-for="(p, i) in params"
          :key="p.key"
          class="field"
          :class="{ grow: p.type === 'text' }"
          :style="{ '--i': String(i) }"
        >
          <span class="lbl">{{ p.label }}</span>

          <template v-if="p.type === 'time'">
            <input
              :id="`p-${p.key}-hour`"
              class="w2"
              type="number"
              inputmode="numeric"
              min="0"
              max="23"
              :value="timeH(p)"
              :aria-label="`${p.label} · 时`"
              @input="onTimePart(p, 'h', $event)"
            />
            <span class="sep">:</span>
            <input
              :id="`p-${p.key}-min`"
              class="w2"
              type="number"
              inputmode="numeric"
              min="0"
              max="59"
              :value="timeM(p)"
              :aria-label="`${p.label} · 分`"
              @input="onTimePart(p, 'm', $event)"
            />
          </template>

          <template v-else-if="p.type === 'select'">
            <SelectMenu
              :id="`p-${p.key}`"
              :label="p.label"
              :options="(p.options ?? []).map((o) => ({ v: String(o.v), t: o.t }))"
              :model-value="state.params[p.key] ?? String(p.value ?? '')"
              @update:model-value="(v: string) => onSelect(p, v)"
            />
          </template>

          <template v-else>
            <input
              :id="`p-${p.key}`"
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
  </section>
</template>

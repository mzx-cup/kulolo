<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import type { ScenarioParam } from "@/types/api";
import { resetParams, setParam } from "@/actions/params";
import { resetRunUi } from "@/actions/session";
import { toast } from "@/actions/toast";
import { replayClass } from "@/lib/dom";
import SelectMenu from "@/components/SelectMenu.vue";

/**
 * 参数配置抽屉：从右侧滑入，展示当前选中场景的参数表单。
 * 复用 HeroPanel 里的参数交互逻辑，避免参数一直堆积在主界面。
 */
export default defineComponent({
  name: "ParamsDrawer",
  components: { SelectMenu },
  setup() {
    const sel = computed(() => state.selected);
    const params = computed<ScenarioParam[]>(() => sel.value?.params ?? []);

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

    function close(): void {
      state.paramsOpen = false;
    }

    return { state, sel, params, onReset, onInput, onTimePart, onSelect, timeH, timeM, close };
  },
});
</script>

<template>
  <Teleport to="body">
    <div class="drawer-scrim" :class="{ show: state.paramsOpen }" @click="close" />
    <aside class="params-drawer" :class="{ open: state.paramsOpen }" aria-label="参数配置">
      <div class="drawer-head">
        <div class="drawer-title">
          <span class="drawer-kicker">parameters</span>
          <h3>{{ sel ? sel.title : "参数配置" }}</h3>
        </div>
        <button class="icon-btn sm" type="button" aria-label="关闭参数面板" @click="close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </div>

      <div class="drawer-body">
        <div class="params-head">
          <span class="params-kicker">运行参数 <em>parameters</em></span>
          <button class="link-btn" type="button" :hidden="params.length === 0" @click="onReset">重置默认</button>
        </div>

        <div class="params">
          <span v-if="!params.length" class="no-params">这个场景没有可调参数，直接点「一键运行」即可。</span>

          <label v-for="(p, i) in params" :key="p.key" class="field" :class="{ grow: p.type === 'text' }" :style="{ '--i': String(i) }">
            <span class="lbl">{{ p.label }}</span>

            <template v-if="p.type === 'time'">
              <input :id="`dp-${p.key}-hour`" class="w2" type="number" inputmode="numeric" min="0" max="23" :value="timeH(p)" :aria-label="`${p.label} · 时`" @input="onTimePart(p, 'h', $event)" />
              <span class="sep">:</span>
              <input :id="`dp-${p.key}-min`" class="w2" type="number" inputmode="numeric" min="0" max="59" :value="timeM(p)" :aria-label="`${p.label} · 分`" @input="onTimePart(p, 'm', $event)" />
            </template>

            <template v-else-if="p.type === 'select'">
              <SelectMenu
                :id="`dp-${p.key}`"
                :label="p.label"
                :options="(p.options ?? []).map((o) => ({ v: String(o.v), t: o.t }))"
                :model-value="state.params[p.key] ?? String(p.value ?? '')"
                @update:model-value="(v: string) => onSelect(p, v)"
              />
            </template>

            <template v-else>
              <input
                :id="`dp-${p.key}`"
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

      <div class="drawer-foot">
        <button class="btn ghost" type="button" @click="close">完成</button>
      </div>
    </aside>
  </Teleport>
</template>

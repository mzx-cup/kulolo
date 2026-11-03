<script lang="ts">
import { defineComponent } from "vue";
import { state } from "@/stores/core";
import { pad2 } from "@/lib/format";
import { refs } from "@/lib/refs";

export default defineComponent({
  name: "StepsPanel",
  setup() {
    return { state, pad2 };
  },
  mounted() {
    refs.stepsEl = this.$refs.list as HTMLElement;
  },
});
</script>

<template>
  <section class="panel steps-panel reveal" style="--i: 1">
    <div class="panel-head">
      <div class="panel-title">
        <h3>执行序列</h3>
        <span class="head-note">sequence</span>
      </div>
      <span id="countdown" class="countdown" :class="{ live: state.countdownLive }">{{ state.countdown }}</span>
    </div>

    <ol id="steps" ref="list" class="steps" :class="{ live: state.stepsLive }" aria-live="polite">
      <template v-if="!state.steps.length">
        <li class="placeholder">
          <span class="ph-glyph" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="3.2" />
              <path d="M12 3.5v3M12 17.5v3M3.5 12h3M17.5 12h3" />
            </svg>
          </span>
          <span>点击「一键运行」后<br />步骤会在这里逐条点亮</span>
          <em class="ph-tip">运行时可随时暂停或结束，右侧画面会自动刷新</em>
        </li>
      </template>

      <li
        v-for="s in state.steps"
        :id="`step-${s.no}`"
        :key="s.no"
        :class="s.state"
      >
        <span class="no">
          <span class="num">{{ pad2(s.no) }}</span>
          <svg class="tick" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 8.4 6.4 11.6 12.8 4.6" /></svg>
          <svg class="cross" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" /></svg>
        </span>
        <span class="body">
          <b>{{ s.title }}</b>
          <span class="ms">{{ `${s.ms ?? 0}ms ${s.detail || ""}`.trim() }}</span>
        </span>
      </li>
    </ol>
  </section>
</template>

<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import { clearLog } from "@/actions/session";
import { refs } from "@/lib/refs";

export default defineComponent({
  name: "LogPanel",
  setup() {
    const countText = computed(() => (state.logs.length ? `${state.logs.length} 行` : ""));
    return { state, countText, clearLog };
  },
  mounted() {
    refs.logEl = this.$refs.box as HTMLElement;
  },
});
</script>

<template>
  <section class="panel log-panel reveal" style="--i: 2">
    <div class="panel-head">
      <div class="panel-title">
        <h3>运行日志</h3>
        <span id="logcount" class="head-note">{{ countText }}</span>
      </div>
      <button id="btn-clear-log" class="icon-btn sm" type="button" title="清空日志" aria-label="清空日志" @click="clearLog">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M4 7h16M9 7V5h6v2M7 7l.8 12h8.4L17 7M10 11v4M14 11v4" />
        </svg>
      </button>
    </div>
    <div id="log" ref="box" class="log" role="log" aria-live="polite">
      <div v-for="l in state.logs" :key="l.id" class="logline" :class="l.kind">
        <span class="ts">{{ l.ts }}</span><span class="msg">{{ l.text }}</span>
      </div>
    </div>
  </section>
</template>

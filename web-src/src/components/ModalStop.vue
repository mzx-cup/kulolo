<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import { stopRun } from "@/actions/run";
import { useModal } from "@/lib/modal";

export default defineComponent({
  name: "ModalStop",
  setup() {
    const { shown, hidden } = useModal(computed(() => state.stopOpen));
    function dismiss(): void {
      state.stopOpen = false;
    }
    return { shown, hidden, stopRun, dismiss };
  },
});
</script>

<template>
  <div
    id="stop-confirm"
    class="modal"
    :class="{ show: shown }"
    :hidden="hidden"
    data-dismissible="true"
    @click.self="dismiss"
  >
    <div class="modal-card tone-rust" role="dialog" aria-modal="true" aria-labelledby="stop-title">
      <span class="modal-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <rect x="6.5" y="6.5" width="11" height="11" rx="2" /><path d="M4 4l16 16" />
        </svg>
      </span>
      <span class="eyebrow">stop&nbsp;·&nbsp;run</span>
      <h3 id="stop-title">结束当前任务？</h3>
      <p class="v-detail">正在执行的步骤会立即中断，手机可能停留在中间状态。<br />结束后可以重新运行。</p>
      <div class="v-actions">
        <button id="btn-stop-yes" class="vbtn bad" type="button" @click="stopRun">结束任务</button>
        <button id="btn-stop-no" class="vbtn plain" type="button" @click="dismiss">继续运行</button>
      </div>
    </div>
  </div>
</template>

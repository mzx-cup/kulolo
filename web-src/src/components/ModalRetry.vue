<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import { retryRun, declineRetry } from "@/actions/run";
import { useModal } from "@/lib/modal";

export default defineComponent({
  name: "ModalRetry",
  setup() {
    const { shown, hidden } = useModal(computed(() => state.retryOpen));
    return { shown, hidden, retryRun, declineRetry };
  },
});
</script>

<template>
  <div id="retry" class="modal corner" :class="{ show: shown }" :hidden="hidden">
    <div class="modal-card tone-amber" role="dialog" aria-modal="false" aria-labelledby="retry-title">
      <span class="modal-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" /><path d="M3.5 4.2v5.2h5.2" />
        </svg>
      </span>
      <span class="eyebrow">retry&nbsp;·&nbsp;未触发</span>
      <h3 id="retry-title">要重新触发吗？</h3>
      <p class="v-detail">卡片没出来，多半是这个日期已经触发过了。<br />再触发要等到下个月——是否把时间调整到下月同日重新试一次？</p>
      <div class="v-actions">
        <button id="btn-retry-yes" class="vbtn ok" type="button" @click="retryRun">重新触发</button>
        <button id="btn-retry-no" class="vbtn bad" type="button" @click="declineRetry">不再重试</button>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import { askAnswer } from "@/actions/run";
import { useModal } from "@/lib/modal";

export default defineComponent({
  name: "ModalAsk",
  setup() {
    const { shown, hidden } = useModal(computed(() => state.askOpen));
    return { state, shown, hidden, askAnswer };
  },
});
</script>

<template>
  <div id="ask" class="modal" :class="{ show: shown }" :hidden="hidden">
    <div class="modal-card tone-blue" role="dialog" aria-modal="true" aria-labelledby="ask-title">
      <span class="modal-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="8.8" />
          <path d="M3.2 12h17.6M12 3.2c2.3 2.4 3.5 5.5 3.5 8.8s-1.2 6.4-3.5 8.8c-2.3-2.4-3.5-5.5-3.5-8.8S9.7 5.6 12 3.2z" />
        </svg>
      </span>
      <span class="eyebrow">ask&nbsp;·&nbsp;oobe</span>
      <h3 id="ask-title">OOBE 国家是否已调整到中国？</h3>
      <p id="ask-prompt" class="v-detail">
        {{ state.askPrompt || "只有把国家调整到中国，节日卡片才能正常触发。" }}
      </p>
      <div class="v-actions">
        <button id="btn-ask-yes" class="vbtn ok" type="button" @click="askAnswer(true)">是，已调整</button>
        <button id="btn-ask-no" class="vbtn bad" type="button" @click="askAnswer(false)">否</button>
      </div>
    </div>
  </div>
</template>

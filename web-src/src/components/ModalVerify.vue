<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import { confirmAnswer } from "@/actions/run";
import { useModal } from "@/lib/modal";

export default defineComponent({
  name: "ModalVerify",
  setup() {
    const { shown, hidden } = useModal(computed(() => state.verifyOpen));
    return { state, shown, hidden, confirmAnswer };
  },
});
</script>

<template>
  <div id="verify" class="modal corner" :class="{ show: shown }" :hidden="hidden">
    <div class="modal-card tone-jade" role="dialog" aria-modal="false" aria-labelledby="verify-title">
      <span class="modal-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.2 4.2L19 6.8" /></svg>
      </span>
      <span class="eyebrow">confirm&nbsp;·&nbsp;card</span>
      <h3 id="verify-title">卡片是否已成功触发？</h3>
      <p class="v-detail">手机已上滑解锁。<br />看一下刚才锁屏上的卡片，是不是已经出来了？</p>
      <div class="v-actions">
        <button id="btn-success" class="vbtn ok" type="button" @click="confirmAnswer(true)">已触发</button>
        <button id="btn-fail" class="vbtn bad" type="button" @click="confirmAnswer(false)">未触发</button>
      </div>
    </div>
  </div>
</template>

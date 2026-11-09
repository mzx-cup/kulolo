<script lang="ts">
import { defineComponent } from "vue";
import { state } from "@/stores/core";
import { setDockPage } from "@/actions/dock";

/** 底部 dock：触发 / 消失 是两个页面的切换器（不是动作按钮）。
 *  当前页高亮，下方滑块跟着走，页面切换动画在 App.vue 的 <Transition> 里。 */
export default defineComponent({
  name: "DockBar",
  setup() {
    function go(page: "trigger" | "dismiss"): void {
      setDockPage(page);
    }
    return { state, go };
  },
});
</script>

<template>
  <div class="dockbar" aria-label="页面切换">
    <div class="dockbar-shell" role="tablist">
      <button class="dock-btn is-trigger" type="button" role="tab"
        :aria-selected="state.dockPage === 'trigger'"
        :class="{ on: state.dockPage === 'trigger' }" @click="go('trigger')">
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M9 6.5 18 12l-9 5.5z" />
        </svg>
        <span>触发</span>
      </button>
      <button class="dock-btn is-dismiss" type="button" role="tab"
        :aria-selected="state.dockPage === 'dismiss'"
        :class="{ on: state.dockPage === 'dismiss' }" @click="go('dismiss')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
          stroke-linecap="round" aria-hidden="true">
          <path d="M3 12h18M8 7l-5 5 5 5M16 7l5 5-5 5" />
        </svg>
        <span>消失</span>
      </button>
      <span class="dock-ink" :class="{ right: state.dockPage === 'dismiss' }" aria-hidden="true" />
    </div>
  </div>
</template>

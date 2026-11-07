<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import { closeCardZoom, zoomLabel } from "@/actions/cards";
import { useModal } from "@/lib/modal";

/** 卡片大图：和 ShotLightbox（手机截图）同一个套路 —— 复用 .lightbox 的
 *  遮罩/入场动效，只是内容换成卡片本身，标题换成一「哪张卡 + 在哪儿采到的」。 */
export default defineComponent({
  name: "CardZoom",
  setup() {
    const open = computed(() => Boolean(state.cardZoomId));
    const { shown, hidden } = useModal(open);
    const info = computed(() => zoomLabel());
    return { state, shown, hidden, info, closeCardZoom };
  },
});
</script>

<template>
  <div id="card-view" class="lightbox" :class="{ show: shown }" :hidden="hidden" @click.self="closeCardZoom">
    <button class="lightbox-close" type="button" aria-label="关闭大图" @click="closeCardZoom">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
    </button>
    <img class="card-zoom-img" :src="info.src || undefined" :alt="info.title" />
    <span class="lightbox-cap"><b>{{ info.title }}</b><em>{{ info.sub }}</em></span>
  </div>
</template>

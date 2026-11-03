<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import { closeLightbox } from "@/actions/shot";
import { useModal } from "@/lib/modal";

export default defineComponent({
  name: "ShotLightbox",
  setup() {
    const open = computed(() => state.lightboxOpen);
    const { shown, hidden } = useModal(open);
    return { state, shown, hidden, closeLightbox };
  },
});
</script>

<template>
  <div id="shot-view" class="lightbox" :class="{ show: shown }" :hidden="hidden" @click.self="closeLightbox">
    <button id="btn-close-shot" class="lightbox-close" type="button" aria-label="关闭大图" @click="closeLightbox">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
    </button>
    <img id="shot-view-img" :src="state.shotSrc || undefined" alt="手机屏幕截图大图" />
    <span id="shot-cap" class="lightbox-cap">{{ state.shotTag }}</span>
  </div>
</template>

<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import { closeCardZoom, zoomGallery, zoomLabel } from "@/actions/cards";
import { useModal } from "@/lib/modal";

/** 卡片大图：和 ShotLightbox（手机截图）同一个套路 —— 复用 .lightbox 的
 *  遮罩/入场动效，只是内容换成卡片本身，标题换成一「哪张卡 + 在哪儿采到的」。
 *
 *  多语言卡点开是**多语陈列**：生活服务两张卡是中文 / English / العربية
 *  三张并排；重要日 8 张目前采到几种语言就陈列几张（中文齐全，英文边采边补），
 *  一眼能看出同一张卡在不同语言下长什么样；单图卡仍然只显示一张。 */
export default defineComponent({
  name: "CardZoom",
  setup() {
    const open = computed(() => Boolean(state.cardZoomId));
    const { shown, hidden } = useModal(open);
    const info = computed(() => zoomLabel());
    const gallery = computed(() => zoomGallery());
    return { state, shown, hidden, info, gallery, closeCardZoom };
  },
});
</script>

<template>
  <div id="card-view" class="lightbox" :class="{ show: shown }" :hidden="hidden" @click.self="closeCardZoom">
    <button class="lightbox-close" type="button" aria-label="关闭大图" @click="closeCardZoom">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
    </button>

    <div v-if="gallery.length > 1" class="card-zoom-group">
      <figure v-for="a in gallery" :key="a.lang" class="card-zoom-item" :class="`lang-${a.lang}`">
        <img class="card-zoom-img" :src="a.src" :alt="a.alt" loading="eager" decoding="async" />
        <figcaption class="card-zoom-tag">{{ a.label }}</figcaption>
      </figure>
    </div>
    <img v-else class="card-zoom-img" :src="info.src || undefined" :alt="info.title" />

    <span class="lightbox-cap"><b>{{ info.title }}</b><em>{{ info.sub }}</em></span>
  </div>
</template>

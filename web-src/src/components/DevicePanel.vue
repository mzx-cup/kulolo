<script lang="ts">
import { defineComponent } from "vue";
import { state } from "@/stores/core";
import { openLightbox, setShotGap } from "@/actions/shot";
import { refs } from "@/lib/refs";

export default defineComponent({
  name: "DevicePanel",
  setup() {
    /** 改间隔：夹到 1~60，并立刻重排下一次刷新 */
    function onGap(e: Event): void {
      const el = e.target as HTMLInputElement;
      const v = Math.min(60, Math.max(1, Math.round(Number(el.value) || 0)));
      setShotGap(v);
      el.value = String(v);
    }

    function onScreenClick(): void {
      if (state.hasShot) openLightbox();
    }

    return { state, onGap, onScreenClick, openLightbox };
  },
  mounted() {
    refs.deviceScreenEl = this.$refs.screen as HTMLElement;
    refs.shotImgEl = this.$refs.img as HTMLImageElement;
  },
});
</script>

<template>
  <aside class="panel device-panel reveal" style="--i: 3">
    <div class="panel-head">
      <div class="panel-title">
        <h3>实时画面</h3>
        <span class="head-note">device</span>
      </div>
      <button id="btn-shot-dock" class="icon-btn sm" type="button" title="查看大图" aria-label="查看大图" @click="onScreenClick">
        <svg class="ico-refresh" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20.5 11a8.5 8.5 0 1 0-2.4 6" /><path d="M20.5 4.5V11h-6.5" />
        </svg>
      </button>
    </div>

    <div class="device-body">
      <div class="device">
        <div id="device-screen" ref="screen" class="device-screen" :class="{ 'has-shot': state.hasShot, swap: state.shotSwap }" @click="onScreenClick">
          <span class="island" aria-hidden="true" />
          <img id="shot" ref="img" alt="截图" class="shot" :class="{ empty: !state.hasShot }" :src="state.shotSrc || undefined" />
          <span class="glare" aria-hidden="true" />
          <span class="scan" aria-hidden="true" />
          <span class="live-badge"><i />LIVE</span>
          <span class="screen-hint">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect x="7" y="2.8" width="10" height="18.4" rx="2.4" /><path d="M10.5 5.5h3" />
            </svg>
            <span>尚未截图</span>
          </span>
          <button id="btn-expand" class="expand-btn" type="button" title="放大查看" aria-label="查看大图" :hidden="!state.hasShot" @click.stop="openLightbox">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M9 4H4v5M15 4h5v5M20 15v5h-5M4 15v5h5" />
            </svg>
          </button>
          <span class="home-bar" aria-hidden="true" />
        </div>
      </div>
      <p id="shottag" class="shottag">{{ state.shotTag }}</p>
      <p id="dev-meta" class="dev-meta">{{ state.devMeta }}</p>
      <div class="shot-ctrl">
        <span class="k">自动刷新</span>
        <label class="interval">
          <input id="shot-gap" type="number" min="1" max="60" step="1" :value="state.shotGap" aria-label="截图自动刷新间隔（秒）" @change="onGap" />
          <span>s</span>
        </label>
        <span id="shot-state" class="state" :class="{ on: state.shotStateOn }" aria-live="polite">{{ state.shotStateText }}</span>
      </div>
      <p class="device-tip">点击画面可放大查看</p>
    </div>
  </aside>
</template>

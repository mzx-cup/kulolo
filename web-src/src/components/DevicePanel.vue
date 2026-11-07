<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import { manualShot, openLightbox, setShotGap } from "@/actions/shot";
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

    /** 电量是否已知（后端给 -1 表示读不到，此时整块隐藏） */
    const hasBattery = computed(() => state.battery >= 0);
    /** 低于 20% 变红，其余绿色 */
    const batteryLow = computed(() => state.battery >= 0 && state.battery < 20);
    const batteryTone = computed(() => (batteryLow.value ? "low" : "ok"));
    /** 充电中时电量徽标带一点动效，表明正在补电 */
    const charging = computed(
      () => state.batteryStatus === "charging" || state.batteryStatus === "full",
    );

    /** 系统版本：没读到就不显示 */
    const hasAndroid = computed(() => Boolean(state.androidVer));

    return {
      state,
      onGap,
      onScreenClick,
      manualShot,
      openLightbox,
      hasBattery,
      batteryLow,
      batteryTone,
      charging,
      hasAndroid,
    };
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
      <!-- 手动刷新一张截图（之前这里误绑成了「查看大图」） -->
      <button
        id="btn-shot-dock"
        class="icon-btn sm"
        type="button"
        title="立即刷新一次截图"
        aria-label="立即刷新截图"
        @click.stop="manualShot"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20.5 11a8.5 8.5 0 1 0-2.4 6" /><path d="M20.5 4.5V11h-6.5" />
        </svg>
      </button>
    </div>

    <div class="device-body">
      <div class="device">
        <div id="device-screen" ref="screen" class="device-screen" :class="{ 'has-shot': state.hasShot, swap: state.shotSwap }" @click="onScreenClick">
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
        </div>
      </div>

      <p id="shottag" class="shottag">{{ state.shotTag }}</p>
      <p id="dev-meta" class="dev-meta">{{ state.devMeta }}</p>

      <!-- 设备指标：电量 + 系统版本（读不到就整条隐藏） -->
      <div v-if="hasBattery || hasAndroid" class="dev-stats">
        <span
          v-if="hasBattery"
          class="dev-stat dev-battery"
          :class="[batteryTone, { charging }]"
          :title="`电量 ${state.battery}%${state.batteryStatus ? ' · ' + state.batteryStatus : ''}`"
        >
          <!-- 电池外形：外壳 + 正极小凸点 + 内部按百分比填充 -->
          <span class="batt-glyph" aria-hidden="true">
            <span class="batt-fill" :style="{ width: Math.max(4, state.battery) + '%' }" />
          </span>
          <span class="batt-num">{{ state.battery }}%</span>
        </span>

        <span v-if="hasAndroid" class="dev-stat dev-android" :title="`系统版本 ${state.androidVer}`">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="6" y="2.6" width="12" height="18.8" rx="2.6" />
            <path d="M10.5 5.2h3" />
          </svg>
          <span>{{ state.androidVer }}</span>
        </span>
      </div>

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

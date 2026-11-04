<script lang="ts">
import { defineComponent } from "vue";
import { state } from "@/stores/core";
import { recheckDevice, launchScrcpy, deviceLabel } from "@/actions/device";
import { toggleTheme } from "@/actions/theme";
import { manualShot } from "@/actions/shot";
import { pickDevice } from "@/actions/device";

export default defineComponent({
  name: "TheTopbar",
  setup() {
    return { state, recheckDevice, launchScrcpy, toggleTheme, manualShot, pickDevice, deviceLabel };
  },
});
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark" aria-hidden="true">
        <!-- 库洛米额头上那枚骷髅 -->
        <svg viewBox="0 0 32 32" fill="none">
          <path
            d="M16 3.6c-5.5 0-9.6 3.8-9.6 8.6 0 2.9 1.5 5 3.4 6.2v4.1c0 1 .8 1.8 1.8 1.8h1.4v2.1c0 .6.5 1.1 1.1 1.1h3.8c.6 0 1.1-.5 1.1-1.1v-2.1h1.4c1 0 1.8-.8 1.8-1.8v-4.1c1.9-1.2 3.4-3.3 3.4-6.2 0-4.8-4.1-8.6-9.6-8.6z"
            stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"
          />
          <ellipse cx="12.2" cy="12.6" rx="2.5" ry="3" fill="currentColor" />
          <ellipse cx="19.8" cy="12.6" rx="2.5" ry="3" fill="currentColor" />
          <path d="M16 17.4v2.6M13.4 22.4v1.6M16 22.4v1.6M18.6 22.4v1.6"
                stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
      </span>
      <span class="brand-txt">
        <h1>手机遥控台</h1>
        <span class="tag">scenario&nbsp;atelier</span>
      </span>
    </div>

    <div class="topbar-mid">
      <button
        id="devstatus"
        class="devstatus"
        :class="state.devTone"
        type="button"
        :title="state.devTitle"
        :aria-label="state.devAria"
        @click="recheckDevice"
      >
        <span class="led" aria-hidden="true" /><span class="txt">{{ state.devLabel }}</span>
      </button>
      <span id="devpick" class="devpick" :hidden="state.devices.length < 2">
        <button
          v-for="d in state.devices"
          :key="d.serial"
          type="button"
          class="chip"
          :class="{ on: d.serial === state.selectedSerial }"
          :title="d.serial"
          @click="pickDevice(d.serial)"
        >
          {{ deviceLabel(d) }}
        </button>
      </span>
    </div>

    <div class="hdr-actions">
      <button
        id="btn-catalog"
        class="btn ghost catalog-toggle"
        type="button"
        aria-label="场景目录"
        @click="state.catalogOpen = !state.catalogOpen"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h10" />
        </svg>
        <span class="txt">场景目录</span>
      </button>
      <button id="btn-shot" class="btn ghost" type="button" title="立即刷新一次手机截图" @click="manualShot">
        <svg class="ico-refresh" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20.5 11a8.5 8.5 0 1 0-2.4 6" />
          <path d="M20.5 4.5V11h-6.5" />
        </svg>
        <span class="txt">刷新截图</span>
      </button>
      <button
        id="btn-scrcpy"
        class="btn ghost"
        type="button"
        :disabled="state.scrcpyDisabled"
        :title="state.scrcpyPath || '未找到 scrcpy.exe（可用 python main.py --scrcpy <路径> 指定）'"
        @click="launchScrcpy"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="6" y="2.8" width="12" height="18.4" rx="2.6" />
          <path d="M10 9.2 14.6 12 10 14.8z" />
        </svg>
        <span class="txt">scrcpy</span>
      </button>
      <button
        id="theme-toggle"
        class="btn ghost icon-btn"
        type="button"
        :title="state.theme === 'light' ? '切换到深色主题' : '切换到浅色主题'"
        aria-label="切换明暗主题"
        :aria-pressed="state.theme === 'light'"
        @click="toggleTheme"
      >
        <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.6v2M12 19.4v2M4.4 4.4l1.4 1.4M18.2 18.2l1.4 1.4M2.6 12h2M19.4 12h2M4.4 19.6l1.4-1.4M18.2 5.8l1.4-1.4" />
        </svg>
        <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20.2 14.6A8.6 8.6 0 0 1 9.4 3.8a8.6 8.6 0 1 0 10.8 10.8z" />
        </svg>
      </button>
    </div>
  </header>
</template>

<script lang="ts">
import { defineComponent, computed, ref, onMounted, onBeforeUnmount } from "vue";
import { state } from "@/stores/core";
import { recheckDevice, launchScrcpy, deviceLabel } from "@/actions/device";
import { toggleTheme, THEMES } from "@/actions/theme";
import { manualShot } from "@/actions/shot";
import { pickDevice } from "@/actions/device";

export default defineComponent({
  name: "TheTopbar",
  setup() {
    const themeMenuOpen = ref(false);
    const themeLabel = computed(() => {
      const t = THEMES.find((x) => x.id === state.theme);
      return t ? t.label : state.theme;
    });

    /** 点击外部区域关闭主题菜单 */
    function onDocClick(e: MouseEvent): void {
      if (!themeMenuOpen.value) return;
      const t = e.target as Node | null;
      const el = e.currentTarget as HTMLElement;
      if (!el.contains(t)) themeMenuOpen.value = false;
    }

    onMounted(() => document.addEventListener("click", onDocClick));
    onBeforeUnmount(() => document.removeEventListener("click", onDocClick));

    return {
      state,
      recheckDevice,
      launchScrcpy,
      toggleTheme,
      manualShot,
      pickDevice,
      deviceLabel,
      THEMES,
      themeLabel,
      themeMenuOpen,
    };
  },
});
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark" aria-hidden="true">
        <!-- 库洛米造型：黑色头巾 + 白骷髅 + 粉色缎带 -->
        <svg viewBox="0 0 32 32" fill="none">
          <defs>
            <radialGradient id="kuroBow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stop-color="#ffd6ea" />
              <stop offset="100%" stop-color="#ffb3d9" />
            </radialGradient>
          </defs>
          <!-- 头巾轮廓 -->
          <path
            d="M16 3c-5 0-9 3.5-9 8.5 0 2 1 3.5 2.5 4.5v3.5c0 1 .8 1.8 1.8 1.8h1.2v2c0 .6.5 1.1 1.1 1.1h3.6c.6 0 1.1-.5 1.1-1.1v-2h1.2c1 0 1.8-.8 1.8-1.8v-3.5c1.5-1 2.5-2.5 2.5-4.5 0-5-4-8.5-9-8.5z"
            stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"
          />
          <!-- 左眼 -->
          <ellipse cx="12" cy="12.5" rx="2.6" ry="3.2" fill="currentColor" />
          <!-- 右眼 -->
          <ellipse cx="20" cy="12.5" rx="2.6" ry="3.2" fill="currentColor" />
          <!-- 嘴巴 -->
          <path d="M16 17.8v2.8M13.5 22.6v1.6M16 22.6v1.6M18.5 22.6v1.6"
                stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          <!-- 粉色缎带（头巾右侧） -->
          <path d="M22 6q2 2 3 5t-1 6" stroke="url(#kuroBow)" stroke-width="3" stroke-linecap="round" />
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
        class="btn ghost icon-btn theme-picker"
        type="button"
        :title="`当前主题：${themeLabel}`"
        aria-label="选择主题色"
        @click="themeMenuOpen = !themeMenuOpen"
      >
        <span class="theme-chip" :style="{ backgroundColor: 'var(--amber)' }" aria-hidden="true" />
        <span class="theme-caret">
          <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3 4.5l3 3 3-3" />
          </svg>
        </span>
      </button>

      <!-- 主题选择下拉菜单 -->
      <div
        class="theme-menu"
        :class="{ open: themeMenuOpen }"
      >
        <div class="theme-menu-head">
          <span class="theme-menu-kicker">主题色</span>
          <button
            class="theme-menu-close"
            type="button"
            aria-label="关闭主题选择"
            @click="themeMenuOpen = false"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div class="theme-menu-list">
          <button
            v-for="t in THEMES"
            :key="t.id"
            type="button"
            class="theme-option"
            :class="{ on: state.theme === t.id }"
            :title="t.desc"
            @click="toggleTheme(t.id); themeMenuOpen = false"
          >
            <span
              class="theme-option-dot"
              :style="{
                backgroundColor: state.theme === t.id ? 'var(--amber)' : 'transparent',
                borderColor: 'var(--amber)',
              }"
              aria-hidden="true"
            />
            <span class="theme-option-name">{{ t.label }}</span>
            <span class="theme-option-desc">{{ t.desc }}</span>
          </button>
        </div>
      </div>
    </div>
  </header>
</template>

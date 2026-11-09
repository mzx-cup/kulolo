<script lang="ts">
import { defineComponent, computed, ref, onMounted, onBeforeUnmount } from "vue";
import { state } from "@/stores/core";
import { recheckDevice, launchScrcpy, deviceLabel } from "@/actions/device";
import { toggleTheme, THEMES } from "@/actions/theme";
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
        <!-- 缎带蝴蝶结：两片外扩的尖角环 + 中间小方结，粉→紫渐变跟主题色联动。
             用尖角而不是椭圆，是因为 22px 下椭圆会糊成三个圆点。 -->
        <svg viewBox="0 0 32 32" fill="none">
          <defs>
            <linearGradient id="brandBow" x1="2" y1="6" x2="30" y2="26" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="var(--amber-bright, #ffd6ea)" />
              <stop offset="46%" stop-color="var(--amber, #ffb3d9)" />
              <stop offset="100%" stop-color="var(--tone-violet, #c3a6ff)" />
            </linearGradient>
          </defs>
          <!-- 左环：中间收窄、外缘饱满，是一段真的缎带环而不是三角形 -->
          <path d="M13.9 16
                   C11.4 13.5 6.4 9.4 4.2 9.0
                   C2.4 8.7 2.0 12.6 2.0 16
                   C2.0 19.4 2.4 23.3 4.2 23.0
                   C6.4 22.6 11.4 18.5 13.9 16 Z" fill="url(#brandBow)" />
          <!-- 右环 -->
          <path d="M18.1 16
                   C20.6 13.5 25.6 9.4 27.8 9.0
                   C29.6 8.7 30.0 12.6 30.0 16
                   C30.0 19.4 29.6 23.3 27.8 23.0
                   C25.6 22.6 20.6 18.5 18.1 16 Z" fill="url(#brandBow)" />
          <!-- 环面高光：沿着上缘的一道缎带反光 -->
          <path d="M11.6 13.6C9.2 11.9 6.2 10.2 4.6 10.0M20.4 13.6C22.8 11.9 25.8 10.2 27.4 10.0"
                stroke="rgba(255, 255, 255, .55)" stroke-width="1.15" stroke-linecap="round" />
          <!-- 中间结 -->
          <rect x="12.9" y="11.5" width="6.2" height="9" rx="2.9" fill="url(#brandBow)" />
          <rect x="12.9" y="11.5" width="6.2" height="9" rx="2.9"
                stroke="rgba(255, 255, 255, .72)" stroke-width="1.05" />
          <!-- 结上的竖向褶光 -->
          <path d="M15.6 13.1v5.8" stroke="rgba(255, 255, 255, .5)"
                stroke-width="1" stroke-linecap="round" />
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
        <!-- 换装图标：一件连衣裙，裙身填充当前主题色 -->
        <span class="theme-chip" aria-hidden="true">
          <svg viewBox="0 0 32 32" fill="none">
            <defs>
              <linearGradient id="themeDress" x1="8" y1="6" x2="24" y2="28" gradientUnits="userSpaceOnUse">
                <stop offset="0%" stop-color="var(--amber-bright, #ffd6ea)" />
                <stop offset="100%" stop-color="var(--amber, #ffb3d9)" />
              </linearGradient>
            </defs>
            <!-- 肩带 -->
            <path d="M11.9 4.6v3.5M20.1 4.6v3.5"
                  stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            <!-- 裙身（上身收腰 + A 字裙摆）。描边用比填充更深的同色，
                 否则 21px 下轮廓跟填充糊成一块，只剩一个色块。 -->
            <path
              d="M11.2 8.1h9.6l-.75 3.4c2.3 4.2 4.1 8.7 4.9 13.1.22 1.2-.7 2.2-1.95 2.2H8.95c-1.25 0-2.17-1-1.95-2.2.8-4.4 2.6-8.9 4.9-13.1l-.7-3.4z"
              fill="url(#themeDress)"
              stroke="color-mix(in srgb, var(--amber) 52%, #2a0f20)"
              stroke-width="1.5" stroke-linejoin="round"
            />
            <!-- 腰线：低饱和深色，比白色更耐看 -->
            <path d="M12.2 12.3c2.6.8 5 .8 7.6 0"
                  stroke="rgba(58, 16, 40, .34)" stroke-width="1.05" stroke-linecap="round" />
            <!-- 裙摆褶皱 -->
            <path d="M13.6 17.4c.32 3.4.32 6.6 0 9.3M18.4 17.4c-.32 3.4-.32 6.6 0 9.3"
                  stroke="rgba(58, 16, 40, .26)" stroke-width="1" stroke-linecap="round" />
          </svg>
        </span>
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

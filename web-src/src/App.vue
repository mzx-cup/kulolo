<script lang="ts">
import { defineComponent, onMounted, onUnmounted } from "vue";
import TheTopbar from "@/components/TheTopbar.vue";
import CatalogPanel from "@/components/CatalogPanel.vue";
import HeroPanel from "@/components/HeroPanel.vue";
import StepsPanel from "@/components/StepsPanel.vue";
import LogPanel from "@/components/LogPanel.vue";
import DevicePanel from "@/components/DevicePanel.vue";
import ModalVerify from "@/components/ModalVerify.vue";
import ModalAsk from "@/components/ModalAsk.vue";
import ModalRetry from "@/components/ModalRetry.vue";
import ModalStop from "@/components/ModalStop.vue";
import ShotLightbox from "@/components/ShotLightbox.vue";
import ResultFx from "@/components/ResultFx.vue";
import ToastBar from "@/components/ToastBar.vue";
import { state } from "@/stores/core";
import { initTheme, loadScenarios } from "@/actions/boot";
import { applyTheme } from "@/actions/theme";
import { refreshStatus, statusSchedule } from "@/actions/device";
import { poll, runScenario } from "@/actions/run";
import { shotSchedule, shotStateRefresh, setVisible, fetchShot, closeLightbox } from "@/actions/shot";
import { cycleScenario } from "@/actions/catalog";
import { toast } from "@/actions/toast";

export default defineComponent({
  name: "App",
  components: {
    TheTopbar,
    CatalogPanel,
    HeroPanel,
    StepsPanel,
    LogPanel,
    DevicePanel,
    ModalVerify,
    ModalAsk,
    ModalRetry,
    ModalStop,
    ShotLightbox,
    ResultFx,
    ToastBar,
  },
  setup() {
    /** 全局快捷键。原来这一大坨在 bind() 里，现在单独一个函数，
     *  顺序保持原样：先处理面板类（Ctrl+K / Ctrl+Enter / Esc / 斜杠），
     *  再处理方向键 —— 否则在输入框里按方向键会误切场景。 */
    function onKeydown(e: KeyboardEvent): void {
      const t = e.target as HTMLElement | null;
      const typing =
        !!t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.tagName === "SELECT" ||
          t.isContentEditable);
      const meta = e.ctrlKey || e.metaKey;

      if (meta && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        openSearch();
        return;
      }
      if (meta && e.key === "Enter") {
        e.preventDefault();
        void runScenario();
        return;
      }
      if (e.key === "Escape") {
        if (state.lightboxOpen) {
          closeLightbox();
          return;
        }
        if (state.stopOpen) {
          state.stopOpen = false;
          return;
        }
        if (state.catalogOpen) {
          state.catalogOpen = false;
          return;
        }
        if (state.query) state.query = "";
        return;
      }
      if (e.key === "/" && !typing && !meta) {
        e.preventDefault();
        openSearch();
        return;
      }
      if (typing) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        cycleScenario(e.key === "ArrowDown" ? 1 : -1);
      }
    }

    function openSearch(): void {
      state.catalogOpen = true;
      window.setTimeout(() => {
        const el = document.querySelector<HTMLInputElement>("#sc-search");
        el?.focus();
        el?.select();
      }, 90);
    }

    function onVisibility(): void {
      const v = !document.hidden;
      setVisible(v);
      shotSchedule();
      shotStateRefresh();
      if (v) {
        void poll();
        void refreshStatus();
      }
    }

    /* 涟漪：挂在全局 pointerdown 上，只对指定控件生效 */
    function onPointerDown(e: PointerEvent): void {
      if (e.button !== 0) return;
      const el = (e.target as HTMLElement | null)?.closest<HTMLElement>(
        ".commit,.vbtn,.btn,.filter,.icon-btn",
      );
      if (!el || (el as HTMLButtonElement).disabled) return;
      const r = document.createElement("span");
      r.className = "ripple";
      const rect = el.getBoundingClientRect();
      const d = Math.max(rect.width, rect.height) * 2;
      r.style.width = r.style.height = d + "px";
      r.style.left = e.clientX - rect.left - d / 2 + "px";
      r.style.top = e.clientY - rect.top - d / 2 + "px";
      el.appendChild(r);
      r.addEventListener("animationend", () => r.remove());
    }

    let loopTimer: number | null = null;

    onMounted(async () => {
      initTheme();
      applyTheme(state.theme, false);

      await refreshStatus();
      shotStateRefresh();
      shotSchedule();
      statusSchedule();

      /* 页面一打开就尝试抓一帧（状态接口有时要等几秒，别让画面空着） */
      window.setTimeout(() => {
        if (state.connected === true && !state.running && !state.starting && !state.hasShot) {
          void fetchShot("初始画面 " + new Date().toLocaleTimeString());
        }
      }, 1200);

      try {
        await loadScenarios();
      } catch (err) {
        console.error(err);
        toast("界面初始化失败，请刷新页面", true);
      }
      void poll();
      loopTimer = window.setInterval(() => {
        if (!document.hidden) void poll();
      }, 600);

      document.addEventListener("keydown", onKeydown);
      document.addEventListener("visibilitychange", onVisibility);
      document.addEventListener("pointerdown", onPointerDown);

      /* 首屏渲染完成后给 shell 加 page-loaded 类，触发整页淡入 */
      window.requestAnimationFrame(() => {
        document.documentElement.classList.add("page-loaded");
      });
    });

    onUnmounted(() => {
      if (loopTimer !== null) clearInterval(loopTimer);
      document.removeEventListener("keydown", onKeydown);
      document.removeEventListener("visibilitychange", onVisibility);
      document.removeEventListener("pointerdown", onPointerDown);
    });

    return { state };
  },
});
</script>

<template>
  <div class="ambient" aria-hidden="true"><span class="stars"></span></div>
  <a class="skip-link" href="#sc-title">跳到场景内容</a>

  <TheTopbar />

  <main class="shell">
    <CatalogPanel />
    <div class="scrim" :class="{ show: state.catalogOpen }" :hidden="!state.catalogOpen" @click="state.catalogOpen = false" />

    <div class="workspace">
      <div class="work-grid">
        <HeroPanel />
        <StepsPanel />
        <LogPanel />
        <DevicePanel />
      </div>
    </div>
  </main>

  <ModalVerify />
  <ModalAsk />
  <ModalRetry />
  <ModalStop />
  <ShotLightbox />
  <ResultFx />
  <ToastBar />
</template>

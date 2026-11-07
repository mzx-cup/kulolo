<script lang="ts">
import { defineComponent, onMounted, onUnmounted, ref } from "vue";
import TheTopbar from "@/components/TheTopbar.vue";
import CategoryNav from "@/components/CategoryNav.vue";
import ScenarioStage from "@/components/ScenarioStage.vue";
import DevicePanel from "@/components/DevicePanel.vue";
import RecentBar from "@/components/RecentBar.vue";
import ParamsDrawer from "@/components/ParamsDrawer.vue";
import StepsPanel from "@/components/StepsPanel.vue";
import LogPanel from "@/components/LogPanel.vue";
import ModalVerify from "@/components/ModalVerify.vue";
import ModalAsk from "@/components/ModalAsk.vue";
import ModalRetry from "@/components/ModalRetry.vue";
import ModalStop from "@/components/ModalStop.vue";
import ShotLightbox from "@/components/ShotLightbox.vue";
import CardZoom from "@/components/CardZoom.vue";
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
    CategoryNav,
    ScenarioStage,
    DevicePanel,
    RecentBar,
    ParamsDrawer,
    StepsPanel,
    LogPanel,
    ModalVerify,
    ModalAsk,
    ModalRetry,
    ModalStop,
    ShotLightbox,
    CardZoom,
    ResultFx,
    ToastBar,
  },
  setup() {
    /** 轮播组件实例引用，用来把 ← / → 键盘事件转发进去 */
    const stageRef = ref<{ onKey: (dir: number) => void } | null>(null);

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
        if (state.selected?.unsupported_note) {
          toast(state.selected.unsupported_note, true);
          return;
        }
        void runScenario();
        return;
      }
      if (e.key === "Escape") {
        if (state.lightboxOpen) {
          closeLightbox();
          return;
        }
        if (state.paramsOpen) {
          state.paramsOpen = false;
          return;
        }
        if (state.stopOpen) {
          state.stopOpen = false;
          return;
        }
        if (state.query) {
          state.query = "";
          return;
        }
        return;
      }
      if (e.key === "/" && !typing && !meta) {
        e.preventDefault();
        openSearch();
        return;
      }
      if (typing) return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        stageRef.value?.onKey(e.key === "ArrowRight" ? 1 : -1);
        return;
      }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        cycleScenario(e.key === "ArrowDown" ? 1 : -1);
      }
    }

    function openSearch(): void {
      window.setTimeout(() => {
        const el = document.querySelector<HTMLInputElement>("#cat-search");
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

    /* 液态玻璃光晕：全局 pointermove 把光标坐标写进 hover 中卡片/控件的
     *  --mx / --my（百分比），CSS 用它定位跟随指针的径向光斑；中央大卡
     *  再叠加轻微 3D 倾斜。只写 CSS 变量，不做 DOM 增删。
     *
     *  GLOW_SEL 是「哪些元素有光晕」的唯一事实来源：
     *  .glow-target 是显式标注（模板里挂的），后面那串是自动覆盖
     *  （面板 / 按钮 / 芯片 / 卡片等玻璃面），与 _liquid.scss 里的
     *  强度分级一一对应。命中即写变量，没命中就什么都不做。 */
    const GLOW_SEL = [
      ".glow-target",
      ".panel",
      ".device-panel",
      ".catnav",
      ".catalog",
      ".stage-card",
      ".recentbar-card",
      ".btn",
      ".icon-btn",
      ".vbtn",
      ".commit",
      ".stage-icbtn",
      ".filter",
      ".chip",
      ".recent-chip",
      ".catnav-subitem",
      ".catnav-item-inner",
      ".catnav-fold",
      ".card",
      ".theme-option",
      ".sel-opt",
    ].join(",");

    function onPointerMove(e: PointerEvent): void {
      const glow = (e.target as HTMLElement | null)?.closest<HTMLElement>(GLOW_SEL) ?? null;
      if (glow) {
        const r = glow.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
          glow.style.setProperty("--mx", (((e.clientX - r.left) / r.width) * 100).toFixed(2) + "%");
          glow.style.setProperty("--my", (((e.clientY - r.top) / r.height) * 100).toFixed(2) + "%");
        }
      }
      /* 中央大卡的 3D 倾斜：拖拽时由 ScenarioStage 自己接管 --dx，
       *  这里只做悬停时的轻倾斜（拖拽中禁用，避免双重 transform 打架） */
      const center = document.querySelector<HTMLElement>(".stage-card.is-center");
      if (!center) return;
      if (center.closest(".stage-viewport")?.classList.contains("dragging")) return;
      if (center.contains(e.target as Node)) {
        const r = center.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width - 0.5;
        const py = (e.clientY - r.top) / r.height - 0.5;
        center.style.setProperty("--tilt-y", (px * 5).toFixed(2) + "deg");
        center.style.setProperty("--tilt-x", (-py * 4).toFixed(2) + "deg");
      } else {
        center.style.setProperty("--tilt-y", "0deg");
        center.style.setProperty("--tilt-x", "0deg");
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
      document.addEventListener("pointermove", onPointerMove, { passive: true });

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
      document.removeEventListener("pointermove", onPointerMove);
    });

    return { state, stageRef };
  },
});
</script>

<template>
  <!-- 背景层：柔光晕 + 简笔画散落底纹（太阳/云/树/房子/动物…随机排布） -->
  <div class="ambient" aria-hidden="true"><span class="doodles"></span></div>
  <a class="skip-link" href="#sc-title">跳到场景内容</a>

  <TheTopbar />

  <main class="shell">
    <!-- 左侧：分类导航 -->
    <CategoryNav />
    <div class="scrim" :class="{ show: state.catalogOpen }" :hidden="!state.catalogOpen" @click="state.catalogOpen = false" />

    <!-- 中央工作区：舞台 + 设备舱 + 最近使用 + 步骤 + 日志 -->
    <div class="workspace">
      <ScenarioStage ref="stageRef" />
      <DevicePanel />
      <RecentBar />
      <div class="flow">
        <StepsPanel />
        <LogPanel />
      </div>
    </div>
  </main>

  <ParamsDrawer />

  <ModalVerify />
  <ModalAsk />
  <ModalRetry />
  <ModalStop />
  <ShotLightbox />
  <CardZoom />
  <ResultFx />
  <ToastBar />
</template>

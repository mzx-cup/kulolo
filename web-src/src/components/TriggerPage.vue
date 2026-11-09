<script lang="ts">
import { defineComponent, ref } from "vue";
import CategoryNav from "./CategoryNav.vue";
import ScenarioStage from "./ScenarioStage.vue";
import DevicePanel from "./DevicePanel.vue";
import RecentBar from "./RecentBar.vue";
import StepsPanel from "./StepsPanel.vue";
import LogPanel from "./LogPanel.vue";

/** 触发页 = 左侧分类导航 + 中央卡片轮播工作台。
 *  单独成组件是为了让 <KeepAlive> 缓存它——切去「消失」页再切回来时
 *  不整页重挂，页面切换的渐现曲线才顺，舞台/日志状态也原样保留。
 *  onKey 透传给内部的 ScenarioStage（App 的 ←→ 方向键用）。 */
export default defineComponent({
  name: "TriggerPage",
  components: { CategoryNav, ScenarioStage, DevicePanel, RecentBar, StepsPanel, LogPanel },
  setup(_, { expose }) {
    const stageRef = ref<{ onKey: (dir: number) => void } | null>(null);
    expose({
      onKey: (dir: number) => stageRef.value?.onKey(dir),
    });
    return { stageRef };
  },
});
</script>

<template>
  <div class="page-trigger">
    <CategoryNav />
    <div class="workspace">
      <ScenarioStage ref="stageRef" />
      <DevicePanel />
      <RecentBar />
      <div class="flow">
        <StepsPanel />
        <LogPanel />
      </div>
    </div>
  </div>
</template>

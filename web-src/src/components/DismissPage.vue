<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import {
  DISMISS_STEPS,
  DISMISS_PREP,
  obsOf,
  obsStats,
  setObs,
  clearObs,
} from "@/actions/dock";
import DevicePanel from "@/components/DevicePanel.vue";

/** 消失页 = 「卡片消失机制检测台」。
 *
 *  排版刻意和触发页不同：触发页是居中卡片轮播，这里改成
 *  左侧竖向流程时间轴（9 个观察节点）+ 右侧实时画面与统计，
 *  每个节点现场记录「卡片消失 / 卡片仍在」。
 *  右栏的实时画面直接复用触发页的 DevicePanel（手机框 + LIVE + 自动刷新）。 */
export default defineComponent({
  name: "DismissPage",
  components: { DevicePanel },
  setup() {
    const stats = computed(() => obsStats());
    const phases = computed(() => {
      const out: { phase: string; steps: typeof DISMISS_STEPS }[] = [];
      for (const s of DISMISS_STEPS) {
        const last = out[out.length - 1];
        if (last && last.phase === s.phase) last.steps.push(s);
        else out.push({ phase: s.phase, steps: [s] });
      }
      return out;
    });

    function onObs(id: string, v: "gone" | "stay"): void {
      setObs(id, v);
    }

    return { state, phases, stats, obsOf, onObs, clearObs, DISMISS_PREP };
  },
});
</script>

<template>
  <div class="dismiss-page" role="tabpanel" aria-label="卡片消失机制检测">
    <!-- 页头：标题 + 进度统计 + 清空 -->
    <header class="dismiss-head">
      <div class="dismiss-title">
        <h2>卡片消失机制检测</h2>
        <p class="dismiss-sub">
          按流程折腾桌面形态，每一步看卡片还在不在。9 个观察点，记录会自动保存。
        </p>
      </div>
      <div class="dismiss-stats">
        <div class="dismiss-stat">
          <b>{{ stats.done }}</b><span>/ {{ stats.total }} 已观察</span>
        </div>
        <div class="dismiss-stat is-gone">
          <b>{{ stats.gone }}</b><span>消失</span>
        </div>
        <div class="dismiss-stat is-stay">
          <b>{{ stats.stay }}</b><span>仍在</span>
        </div>
        <button class="vbtn" type="button" @click="clearObs()">清空记录</button>
      </div>
    </header>

    <!-- 前置准备 -->
    <section class="dismiss-prep">
      <span class="dismiss-prep-tag">前置</span>
      <div class="dismiss-prep-body">
        <b>{{ DISMISS_PREP.title }}</b>
        <small>{{ DISMISS_PREP.how }}</small>
      </div>
    </section>

    <div class="dismiss-body">
      <!-- 左：流程时间轴 -->
      <ol class="dismiss-timeline">
        <li v-for="g in phases" :key="g.phase" class="dismiss-phase">
          <h3 class="dismiss-phase-name">{{ g.phase }}</h3>
          <ol class="dismiss-steps">
            <li v-for="s in g.steps" :key="s.id" class="dismiss-step"
              :class="{ 'is-gone': obsOf(s.id) === 'gone', 'is-stay': obsOf(s.id) === 'stay' }">
              <div class="dismiss-step-dot" aria-hidden="true" />
              <div class="dismiss-step-body">
                <div class="dismiss-step-head">
                  <b>{{ s.title }}</b>
                  <span class="dismiss-step-how">{{ s.how }}</span>
                </div>
                <div class="dismiss-obs" role="radiogroup" :aria-label="s.title + ' 观察结果'">
                  <button class="dismiss-obs-btn is-gone" type="button" role="radio"
                    :aria-checked="obsOf(s.id) === 'gone'"
                    :class="{ on: obsOf(s.id) === 'gone' }" @click="onObs(s.id, 'gone')">
                    卡片消失
                  </button>
                  <button class="dismiss-obs-btn is-stay" type="button" role="radio"
                    :aria-checked="obsOf(s.id) === 'stay'"
                    :class="{ on: obsOf(s.id) === 'stay' }" @click="onObs(s.id, 'stay')">
                    卡片仍在
                  </button>
                </div>
              </div>
            </li>
          </ol>
        </li>
      </ol>

      <!-- 右：实时画面（与触发页同款手机框 DevicePanel） + 说明 -->
      <aside class="dismiss-side">
        <DevicePanel />

        <section class="panel dismiss-help">
          <div class="panel-head">
            <div class="panel-title">
              <h3>怎么用</h3>
              <span class="head-note">guide</span>
            </div>
          </div>
          <ol class="dismiss-help-list">
            <li>先关掉桌面底部谷歌搜索，再开始遍历网格。</li>
            <li>每做完一个操作，看桌面卡片在不在，点「卡片消失 / 卡片仍在」。</li>
            <li>同一个结果再点一次可以取消，改记另一个。</li>
            <li>9 个点都记完，这一轮检测就齐了。</li>
          </ol>
        </section>
      </aside>
    </div>
  </div>
</template>

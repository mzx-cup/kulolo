<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";

/** 右下角结算卡：成功/失败两种形态，进场后停留几秒淡出。
 *  颗粒（confetti / ash）本来由 spawnBits() 往卡片里塞 span，
 *  这些 span 纯装饰、无状态，这里改成数据驱动，
 *  但样式变量还是用原来的 --dx / --dy / --r / --d。 */
interface Bit {
  key: number;
  cls: "confetti" | "ash";
  style: Record<string, string>;
}

/* 成功彩纸：樱粉 / 薄荷 / 薰衣草 / 香槟白，跟库洛米主题同色系 */
const CONFETTI_COLORS = ["#ffa6c9", "#ffd0e2", "#7fdcc0", "#c3a6ff", "#fdf3f8"];
/* 失败灰烬：偏紫的炭黑，不再是旧主题的暖棕 */
const ASH_COLORS = ["#5c4a5c", "#7a6478", "#a8324f", "#a89aae"];

let seq = 0;

function spawnBits(kind: "ok" | "fail", n: number): Bit[] {
  const out: Bit[] = [];
  for (let i = 0; i < n; i++) {
    const style: Record<string, string> = {
      "--d": `${Math.round(Math.random() * 300)}ms`,
    };
    if (kind === "ok") {
      const s = 6 + Math.random() * 6;
      style.width = style.height = `${s.toFixed(0)}px`;
      style.background = CONFETTI_COLORS[i % CONFETTI_COLORS.length];
      style.borderRadius = i % 3 ? "2px" : "50%";
      style["--dx"] = `${Math.round(Math.random() * 280 - 140)}px`;
      style["--dy"] = `${Math.round(Math.random() * 160 - 215)}px`;
      style["--r"] = `${Math.round(Math.random() * 540 - 270)}deg`;
    } else {
      const s = 3 + Math.random() * 4;
      style.width = style.height = `${s.toFixed(0)}px`;
      style.background = ASH_COLORS[i % ASH_COLORS.length];
      style["--dx"] = `${Math.round(Math.random() * 120 - 60)}px`;
      style["--dy"] = `${Math.round(60 + Math.random() * 150)}px`;
    }
    seq += 1;
    out.push({ key: seq, cls: kind === "ok" ? "confetti" : "ash", style });
  }
  return out;
}

export default defineComponent({
  name: "ResultFx",
  setup() {
    /* 每次重新打开都重新生成一批颗粒，位置不重复 */
    const bits = computed<Bit[]>(() =>
      state.fxOpen ? spawnBits(state.fxKind, state.fxKind === "ok" ? 26 : 18) : [],
    );
    return { state, bits };
  },
});
</script>

<template>
  <div
    id="result-fx"
    class="result-fx"
    :class="[state.fxKind, { out: state.fxOut }]"
    :hidden="!state.fxOpen"
  >
    <div class="rt-card">
      <span class="rt-icon" aria-hidden="true">
        <svg v-if="state.fxKind === 'ok'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12.5l4.2 4.2L19 6.8" />
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M7 7l10 10M17 7 7 17" />
        </svg>
      </span>
      <span class="rt-copy">
        <b>{{ state.fxKind === "ok" ? "卡片已成功触发" : "卡片未触发" }}</b>
        <small>{{ state.fxKind === "ok" ? "流程全部生效 · 锁屏卡片确认出现" : "已记录本次结果 · 可调整参数后重试" }}</small>
      </span>
    </div>
    <span v-for="b in bits" :key="b.key" :class="b.cls" :style="b.style" aria-hidden="true" />
  </div>
</template>

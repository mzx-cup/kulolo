<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import type { ScenarioView } from "@/types/api";
import { trySelect, isFavorite, toggleFavorite } from "@/actions/catalog";
import { iconBody } from "@/lib/icons";
import { artFor } from "@/actions/cards";

/**
 * 底部最近使用 / 快捷访问横向条。
 * 复用 state.recent（最近执行过的场景 id），横向排列，点击切换到中央主卡片。
 */
export default defineComponent({
  name: "RecentBar",
  setup() {
    const items = computed<ScenarioView[]>(() =>
      state.recent
        .map((id) => state.scenarios.find((s) => s.id === id))
        .filter((s): s is ScenarioView => Boolean(s)),
    );

    function onSelect(id: string): void {
      trySelect(id);
    }

    function onFav(e: Event, id: string): void {
      e.stopPropagation();
      toggleFavorite(id);
    }

    return { state, items, isFavorite, onSelect, onFav, iconBody, artFor };
  },
});
</script>

<template>
  <section v-if="items.length" class="recentbar reveal" style="--i: 3" aria-label="最近使用">
    <div class="recentbar-head">
      <div class="panel-title">
        <h3>最近使用</h3>
        <span class="head-note">recent</span>
      </div>
    </div>

    <div class="recentbar-track">
      <button
        v-for="s in items"
        :key="s.id"
        type="button"
        class="recentbar-card glow-target"
        :class="{ on: state.selected?.id === s.id }"
        :style="{ '--g-tone': state.groups.find((g) => g.name === s._group)?.tone ?? 'var(--tone-amber)' }"
        :title="`${s.title} · ${s.tag}`"
        @click="onSelect(s.id)"
      >
        <span class="recentbar-glyph" aria-hidden="true">
          <img v-if="artFor(s.id)" :src="artFor(s.id)" alt="" loading="lazy" decoding="async" />
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" v-html="iconBody(s)" />
        </span>
        <span class="recentbar-main">
          <span class="recentbar-title">{{ s.title }}</span>
          <span class="recentbar-group">{{ s._group }}</span>
        </span>
        <button
          class="recentbar-fav"
          type="button"
          :class="{ on: isFavorite(s.id) }"
          :aria-pressed="isFavorite(s.id)"
          :aria-label="isFavorite(s.id) ? '取消收藏' : '收藏'"
          @click="onFav($event, s.id)"
        >
          <svg viewBox="0 0 24 24" :fill="isFavorite(s.id) ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 20.4S4.6 16 4.6 10.9A4.1 4.1 0 0 1 12 8.2a4.1 4.1 0 0 1 7.4 2.7c0 5.1-7.4 9.5-7.4 9.5z" />
          </svg>
        </button>
      </button>
    </div>
  </section>
</template>

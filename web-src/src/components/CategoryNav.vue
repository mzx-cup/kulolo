<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import type { ScenarioView } from "@/types/api";
import {
  currentVisible,
  expandAllGroups,
  collapseAllGroups,
  isGroupClosed,
  setFilter,
  setQuery,
  toggleGroupCollapsed,
  trySelect,
} from "@/actions/catalog";
import { artFor, openCardZoom } from "@/actions/cards";
import { iconBody } from "@/lib/icons";

/**
 * 左侧场景中心。
 *
 * 交互分工：
 *   · 点分组头的名字/圆点 → 按该分组筛选
 *   · 点右侧箭头 → 只切换展开/收起，不触发筛选
 *   · 点条目缩略图 → 放大预览这张卡（不切换场景）
 *   · 点条目其余部分 → 选中该场景
 *   · 顶部「全部展开 / 全部收起」一键切换
 *
 * 注意：缩略图放大是本组件提供的唯一「看大图」入口 —— 右侧的
 * 「卡片实拍」面板已经删掉了，避免同一张图有两个入口。
 */
export default defineComponent({
  name: "CategoryNav",
  setup() {
    const visible = computed(() => currentVisible());
    const searching = computed(() => Boolean(state.query.trim()));
    const filtering = computed(() => searching.value || state.activeFilter !== "all");

    const sections = computed(() =>
      state.groups.map((g) => ({
        group: g,
        count: g.list.length,
        closed: isGroupClosed(g.name, searching.value),
        items: g.list as ScenarioView[],
      })),
    );

    /** 全部收起时按钮变成「全部展开」 */
    const allClosed = computed(
      () => state.groups.length > 0 && state.groups.every((g) => state.collapsed.has(g.name)),
    );

    const totalText = computed(() =>
      filtering.value ? `${visible.value.length} / ${state.scenarios.length}` : `${state.scenarios.length} 个`,
    );

    function onFilter(name: string): void {
      setFilter(name);
    }

    function onSearch(e: Event): void {
      setQuery((e.target as HTMLInputElement).value);
    }

    function clearSearch(): void {
      setQuery("");
    }

    /** 只切折叠，不碰筛选 */
    function onToggleGroup(name: string, e: Event): void {
      e.stopPropagation();
      toggleGroupCollapsed(name);
    }

    function onToggleAll(): void {
      if (allClosed.value) expandAllGroups();
      else collapseAllGroups();
    }

    /** 选中某个场景。
     *
     *  「筛选会自动让位」这件事已经统一在 catalog.selectScenario 里处理
     *  （选中项不在当前分组 → 自动切回全部场景），所以这里直接调用即可。
     *  这样左侧条目、最近使用、快捷键等所有入口行为一致。 */
    function onSelectItem(id: string): void {
      trySelect(id);
    }

    /** 点缩略图：放大看这张卡，不切换选中的场景（两个动作别互相干扰） */
    function onThumb(e: Event, id: string): void {
      e.stopPropagation();
      openCardZoom(id);
    }

    /** 条目缩略图：实拍 > 设计稿 > 空（空时模板退回 SVG 图标） */
    function thumb(id: string): string {
      return artFor(id);
    }

    return {
      state,
      visible,
      sections,
      searching,
      filtering,
      allClosed,
      totalText,
      onFilter,
      onSearch,
      clearSearch,
      onToggleGroup,
      onToggleAll,
      onSelectItem,
      onThumb,
      thumb,
      iconBody,
    };
  },
});
</script>

<template>
  <aside class="catnav" aria-label="场景中心">
    <div class="catnav-head">
      <div class="catnav-heading">
        <span class="kicker">Library</span>
        <h2>场景中心</h2>
      </div>
      <div class="catnav-head-right">
        <span class="count-badge" :title="'场景数量'">{{ totalText }}</span>
        <button
          class="icon-btn sm catnav-toggle-all"
          type="button"
          :title="allClosed ? '全部展开' : '全部收起'"
          :aria-label="allClosed ? '全部展开' : '全部收起'"
          @click="onToggleAll"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
            :class="{ flipped: allClosed }"
          >
            <path d="M6 14.5 12 8.5l6 6" />
            <path d="M6 19.5 12 13.5l6 6" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 搜索 -->
    <div class="search" :class="{ 'has-value': Boolean(state.query) }">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">
        <circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.2 4.2" />
      </svg>
      <input
        id="cat-search"
        type="search"
        placeholder="搜索场景、标签或描述"
        autocomplete="off"
        spellcheck="false"
        aria-label="搜索场景"
        :value="state.query"
        @input="onSearch"
      />
      <kbd class="search-kbd">/</kbd>
      <button class="search-clear" type="button" aria-label="清空搜索" :hidden="!state.query" @click="clearSearch">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M7 7l10 10M17 7 7 17" /></svg>
      </button>
    </div>

    <!-- 分类列表 -->
    <nav class="catnav-scroll" aria-label="场景分类">
      <button
        class="catnav-item glow-target"
        :class="{ on: state.activeFilter === 'all' }"
        type="button"
        :aria-pressed="state.activeFilter === 'all'"
        @click="onFilter('all')"
      >
        <span class="catnav-dot" aria-hidden="true" />
        <span class="catnav-name">全部场景</span>
        <span class="catnav-count">{{ state.scenarios.length }}</span>
      </button>

      <div
        v-for="sec in sections"
        :key="sec.group.name"
        class="catnav-group"
        :class="{ closed: sec.closed }"
        :style="{ '--g-tone': sec.group.tone }"
      >
        <div class="catnav-group-head glow-target" :class="{ on: state.activeFilter === sec.group.name }">
          <!-- 点这块：按分组筛选 -->
          <button
            type="button"
            class="catnav-item catnav-item-inner"
            :aria-pressed="state.activeFilter === sec.group.name"
            @click="onFilter(sec.group.name)"
          >
            <span class="catnav-dot" aria-hidden="true" />
            <span class="catnav-name">{{ sec.group.name }}</span>
            <span class="catnav-count">{{ sec.count }}</span>
          </button>

          <!-- 点这块：只展开 / 收起 -->
          <button
            type="button"
            class="catnav-fold"
            :aria-expanded="!sec.closed"
            :aria-label="`${sec.closed ? '展开' : '收起'}${sec.group.name}`"
            :title="sec.closed ? '展开' : '收起'"
            @click="onToggleGroup(sec.group.name, $event)"
          >
            <svg
              class="catnav-caret"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.9"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </button>
        </div>

        <!-- 分组下的场景子列表：每条左边一张卡片 UI 图（点图放大预览） -->
        <div class="catnav-sub" :class="{ open: !sec.closed }">
          <div class="catnav-sub-inner">
            <div
              v-for="s in sec.items"
              :key="s.id"
              class="catnav-subitem glow-target"
              :class="{ on: state.selected?.id === s.id }"
              :style="{ '--g-tone': sec.group.tone }"
            >
              <!-- 缩略图：独立按钮，点它只放大预览，不切换场景 -->
              <button
                type="button"
                class="catnav-thumb"
                :class="{ 'has-art': Boolean(thumb(s.id)) }"
                :title="thumb(s.id) ? `${s.title} · 点击放大预览` : s.title"
                :aria-label="`放大预览：${s.title}`"
                :disabled="!thumb(s.id)"
                @click="onThumb($event, s.id)"
              >
                <img v-if="thumb(s.id)" :src="thumb(s.id)" alt="" loading="lazy" decoding="async" />
                <svg
                  v-else
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.6"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                  v-html="iconBody(s)"
                />
              </button>

              <!-- 名字区：选中该场景 -->
              <button
                type="button"
                class="catnav-submain"
                :title="s.title"
                @click="onSelectItem(s.id)"
              >
                <span class="catnav-subname">{{ s.title }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 无结果 -->
      <div v-if="state.scenarios.length && visible.length === 0" class="catnav-empty">
        <span class="nr-glyph" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.2 4.2M8.5 11h5" /></svg>
        </span>
        <p>没有匹配的场景</p>
      </div>
    </nav>

    <div class="catnav-foot">
      <span><kbd>←</kbd><kbd>→</kbd> 切换</span>
      <span><kbd>Ctrl</kbd><kbd>Enter</kbd> 运行</span>
    </div>
  </aside>
</template>

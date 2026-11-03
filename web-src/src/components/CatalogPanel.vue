<script lang="ts">
import { computed, defineComponent } from "vue";
import { state } from "@/stores/core";
import type { ScenarioView } from "@/types/api";
import { currentVisible, highlight, selectScenario, setFilter, setQuery, trySelect, toggleGroupCollapsed, isBusy } from "@/actions/catalog";
import { resetParams } from "@/actions/params";
import { iconBody } from "@/lib/icons";
import { pad2 } from "@/lib/format";
import { refs } from "@/lib/refs";
import { resetRunUi } from "@/actions/session";
import { loadScenarios } from "@/actions/boot";

export default defineComponent({
  name: "CatalogPanel",
  setup() {
    const visible = computed(() => currentVisible());

    /** 搜索/筛选生效时强制展开全部分组（以前就是这个行为：
     *  找东西的时候不该被折叠挡住） */
    const filtering = computed(() => Boolean(state.query.trim()) || state.activeFilter !== "all");

    const sections = computed(() =>
      state.groups
        .map((g) => ({
          group: g,
          list: visible.value.filter((s) => s._group === g.name),
          closed: !filtering.value && state.collapsed.has(g.name),
        }))
        .filter((x) => x.list.length > 0),
    );

    const totalText = computed(() =>
      filtering.value ? `${visible.value.length} / ${state.scenarios.length}` : `${state.scenarios.length} 个`,
    );

    const recentItems = computed(() =>
      state.query.trim() || state.activeFilter !== "all"
        ? []
        : state.recent
            .map((id) => state.scenarios.find((s) => s.id === id))
            .filter((s): s is ScenarioView => Boolean(s))
            .slice(0, 3),
    );

    function onSelect(id: string): void {
      trySelect(id);
    }

    function onGroupHead(name: string): void {
      if (filtering.value) return;
      toggleGroupCollapsed(name);
    }

    function onFilter(name: string): void {
      setFilter(name);
      scrollTop();
    }

    function onSearch(e: Event): void {
      setQuery((e.target as HTMLInputElement).value);
      scrollTop();
    }

    function clearSearch(): void {
      setQuery("");
      scrollTop();
    }

    function clearAll(): void {
      setQuery("");
      setFilter("all");
      scrollTop();
    }

    function scrollTop(): void {
      if (refs.catalogScrollEl) refs.catalogScrollEl.scrollTop = 0;
    }

    function onSearchEnter(): void {
      const list = visible.value;
      if (list.length) selectScenario(list[0].id);
    }

    /** 点「重置默认」：把参数恢复成场景自带的默认值 */
    function onResetParams(): void {
      resetParams();
      resetRunUi();
    }

    /** 目录加载失败时点「重新加载」 */
    function onReload(): void {
      void loadScenarios();
    }

    return {
      state,
      visible,
      sections,
      filtering,
      totalText,
      recentItems,
      pad2,
      iconBody,
      onSelect,
      onGroupHead,
      onFilter,
      onSearch,
      clearSearch,
      clearAll,
      onSearchEnter,
      onResetParams,
      onReload,
      highlight,
      isBusy,
    };
  },
  mounted() {
    refs.catalogScrollEl = this.$refs.scroll as HTMLElement;
  },
});
</script>

<template>
  <aside id="catalog" class="catalog" :class="{ open: state.catalogOpen }" aria-label="场景目录">
    <div class="catalog-head">
      <div class="catalog-heading">
        <span class="kicker">Library</span>
        <h2>场景目录</h2>
      </div>
      <div class="catalog-head-right">
        <span id="sc-total" class="count-badge" title="场景数量">{{ totalText }}</span>
        <button
          id="btn-close-catalog"
          class="icon-btn close-catalog"
          type="button"
          aria-label="场景目录"
          @click="state.catalogOpen = false"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </div>
    </div>

    <div class="search" id="search-wrap" :class="{ 'has-value': Boolean(state.query) }">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">
        <circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.2 4.2" />
      </svg>
      <input
        id="sc-search"
        type="search"
        placeholder="搜索场景、标签或描述"
        autocomplete="off"
        spellcheck="false"
        aria-label="场景目录"
        :value="state.query"
        @input="onSearch"
        @keydown.enter.prevent="onSearchEnter"
      />
      <kbd class="search-kbd">/</kbd>
      <button
        id="search-clear"
        class="search-clear"
        type="button"
        aria-label="清空搜索"
        :hidden="!state.query"
        @click="clearSearch"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M7 7l10 10M17 7 7 17" /></svg>
      </button>
    </div>

    <div id="recent" class="recent" :hidden="recentItems.length === 0">
      <span class="recent-label">最近</span>
      <div id="recent-chips" class="recent-chips">
        <button
          v-for="s in recentItems"
          :key="s.id"
          type="button"
          class="recent-chip"
          :title="s.title"
          @click="onSelect(s.id)"
        >
          {{ s.title }}
        </button>
      </div>
    </div>

    <div id="filters" class="filters" role="group" aria-label="按分组筛选">
      <button
        class="filter"
        :class="{ on: state.activeFilter === 'all' }"
        type="button"
        data-group="all"
        role="button"
        :aria-pressed="state.activeFilter === 'all'"
        @click="onFilter('all')"
      >
        全部 <span class="n">{{ state.scenarios.length }}</span>
      </button>
      <button
        v-for="g in state.groups"
        :key="g.name"
        class="filter"
        :class="{ on: state.activeFilter === g.name }"
        type="button"
        :data-group="g.name"
        role="button"
        :aria-pressed="state.activeFilter === g.name"
        :style="{ '--g-tone': g.tone }"
        @click="onFilter(g.name)"
      >
        <span class="dot" />{{ g.name }}<span class="n">{{ g.list.length }}</span>
      </button>
    </div>

    <div class="catalog-scroll" id="catalog-scroll" ref="scroll">
      <div id="cards" class="cards">
        <div v-if="state.loading" class="skel-list" aria-hidden="true">
          <span class="skel" /><span class="skel" /><span class="skel" />
          <span class="skel" /><span class="skel" />
        </div>

        <div v-else-if="state.loadError" class="load-error">
          <span class="le-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 8.5v5M12 17.2v.1" />
              <path d="M10.3 4.4 3.5 16.2A1.9 1.9 0 0 0 5.2 19h13.6a1.9 1.9 0 0 0 1.7-2.8L13.7 4.4a1.9 1.9 0 0 0-3.4 0z" />
            </svg>
          </span>
          <b>场景读取失败</b>
          <p>{{ state.loadError }}</p>
          <button class="btn ghost sm" type="button" @click="onReload">重新加载</button>
        </div>

        <template v-else>
          <section
            v-for="sec in sections"
            :key="sec.group.name"
            class="group"
            :class="{ closed: sec.closed }"
            :data-group="sec.group.name"
            :style="{ '--g-tone': sec.group.tone }"
          >
            <button
              type="button"
              class="group-head"
              :aria-expanded="!sec.closed"
              @click="onGroupHead(sec.group.name)"
            >
              <span class="g-dot" />
              <span class="g-name">{{ sec.group.name }}</span>
              <span class="g-count">{{ sec.list.length }}</span>
              <svg class="g-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
            <div class="group-body">
              <div class="group-inner">
                <ul class="group-list">
                  <li v-for="(s, i) in sec.list" :key="s.id">
                    <button
                      type="button"
                      class="card"
                      :class="{ on: state.selected?.id === s.id }"
                      :data-id="s.id"
                      :aria-pressed="state.selected?.id === s.id"
                      :style="{ '--ci': String(Math.min(i, 12)), '--g-tone': sec.group.tone }"
                      :title="`${s.title} · ${s.tag}`"
                      @click="onSelect(s.id)"
                    >
                      <span class="card-glyph" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" v-html="iconBody(s)" />
                      </span>
                      <span class="card-main">
                        <span class="card-line">
                          <span class="card-no">{{ pad2(s._no) }}</span>
                          <span class="card-title" v-html="highlight(s.title, state.query)" />
                        </span>
                        <span class="card-tag" v-html="highlight(s.tag, state.query)" />
                      </span>
                      <span class="card-go" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6" /></svg>
                      </span>
                    </button>
                  </li>
                </ul>
              </div>
            </div>
          </section>
        </template>
      </div>

      <div id="no-results" class="no-results" :hidden="!(state.scenarios.length && visible.length === 0)">
        <span class="nr-glyph" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.2 4.2M8.5 11h5" /></svg>
        </span>
        <p>没有匹配的场景</p>
        <span>换个关键词，或看看别的分组</span>
        <button id="btn-clear-filter" class="btn ghost sm" type="button" @click="clearAll">清除筛选</button>
      </div>
    </div>

    <div class="catalog-foot">
      <span><kbd>↑</kbd><kbd>↓</kbd> 切换</span>
      <span><kbd>Ctrl</kbd><kbd>↑</kbd> 运行</span>
    </div>
  </aside>
</template>

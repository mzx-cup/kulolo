import { state } from "@/stores/core";
import type { Scenario, ScenarioGroup, ScenarioView } from "@/types/api";
import { STORAGE_KEYS, readJSON, readText, writeJSON, writeText } from "@/lib/storage";
import { toast } from "./toast";
import { resetParams } from "./params";
import { applyRunMemory, resetRunUi } from "./session";

/** 分组强调色。顺序有讲究：先匹配到的赢，所以「节日」要排在「重要日」前面，
 *  否则「节日祝福卡片」会先被「重要|日历」那条吃掉。 */
const TONES = [
  "var(--tone-amber)",
  "var(--tone-rose)",
  "var(--tone-jade)",
  "var(--tone-blue)",
  "var(--tone-violet)",
  "var(--tone-cyan)",
  "var(--tone-orange)",
];

const TONE_RULES: ReadonlyArray<readonly [RegExp, string]> = [
  [/boomplay|音乐/i, "var(--tone-violet)"],
  [/节日/, "var(--tone-rose)"],
  [/重要|日历/, "var(--tone-amber)"],
  [/生活服务/, "var(--tone-orange)"],
  [/玩机技巧/, "var(--tone-cyan)"],
  [/时间/, "var(--tone-cyan)"],
  [/位置|定位|跨国|跨城/, "var(--tone-blue)"],
  [/停电|电力|outage/i, "var(--tone-orange)"],
  [/路况|天气|traffic|weather/i, "var(--tone-blue)"],
  [/隐私|合规|privacy/i, "var(--tone-violet)"],
];

/** 把后端给的一维场景数组按 group 归并成目录用的结构，
 *  顺手补上 _no（全局序号）和 _group（归一化分组名）。 */
export function buildGroups(): void {
  const map = new Map<string, ScenarioGroup>();
  state.scenarios.forEach((s: Scenario, i: number) => {
    const name = s.group || "其他场景";
    let g = map.get(name);
    if (!g) {
      g = { name, list: [], tone: "" };
      map.set(name, g);
    }
    const view = s as ScenarioView;
    view._no = i + 1;
    view._group = name;
    g.list.push(view);
  });

  let ci = 0;
  for (const g of map.values()) {
    const hit = TONE_RULES.find(([re]) => re.test(g.name));
    g.tone = hit ? hit[1] : TONES[ci % TONES.length];
    ci += 1;
  }
  state.groups = [...map.values()];
}

/** 当前筛选 + 搜索命中的场景。搜索是「按空格分词、每个词都要命中」。 */
export function currentVisible(): ScenarioView[] {
  const tokens = state.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return state.scenarios.filter((s) => {
    if (state.activeFilter !== "all" && s._group !== state.activeFilter) return false;
    if (!tokens.length) return true;
    const hay = `${s.title} ${s.tag} ${s.desc || ""} ${s._group} ${s.id}`.toLowerCase();
    return tokens.every((t) => hay.includes(t));
  });
}

/** 搜索词高亮：先转义再包 <mark>，任何时候都不会把用户输入当 HTML。 */
export function highlight(text: string, q: string): string {
  const safe = escapeHtml(text);
  const tokens = q.trim().split(/\s+/).filter(Boolean).map(escapeRegExp);
  if (!tokens.length) return safe;
  try {
    return safe.replace(new RegExp(`(${tokens.join("|")})`, "gi"), "<mark>$1</mark>");
  } catch {
    return safe;
  }
}

function escapeHtml(s: string): string {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[m] as string,
  );
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 记住最近用过的场景，最多留 4 个（界面上展示前 3 个） */
export function addRecent(id: string): void {
  state.recent = [id, ...state.recent.filter((x) => x !== id)].slice(0, 4);
  writeJSON(STORAGE_KEYS.recent, state.recent);
}

export function isBusy(): boolean {
  return state.starting || state.running;
}

/** 切换场景。运行时默认拒绝（除非 force），silent 时不弹提示也不播切换动画。 */
export function selectScenario(id: string, opts: { force?: boolean; silent?: boolean } = {}): boolean {
  if (isBusy() && !opts.force) {
    if (!opts.silent) toast("运行中，结束后再切换场景", true);
    return false;
  }
  const s = state.scenarios.find((x) => x.id === id);
  if (!s) return false;

  /* 选中的场景不在当前分组筛选里 → 自动退回「全部场景」。
   *
   * 为什么必须在这里做：`currentVisible()` 是按 activeFilter 过滤的，
   * 而轮播的索引（ScenarioStage.syncIndex）只认可见列表。如果筛选停在
   * 「时间管理」却选了「重要日卡片」下的场景，可见列表里根本找不到它，
   * syncIndex 就会把中央卡强行拉回时间管理组的第一张 ——
   * 表现就是「点了别的分类的卡没反应，必须先点全部场景」。
   *
   * 放在 selectScenario 而不是各个组件里，是为了让左侧条目、最近使用、
   * 快捷键等所有入口都自动获得这个行为，不必各自复制一遍判断。 */
  if (state.activeFilter !== "all" && s._group !== state.activeFilter) {
    state.activeFilter = "all";
  }

  if (state.selected && state.selected.id === id && !opts.force) {
    return true;
  }

  state.selected = s;
  state.pendingConfirm = false;
  state.pendingAsk = false;
  state.verifyOpen = false;
  state.askOpen = false;
  state.retryOpen = false;
  state.stopOpen = false;

  resetParams();
  resetRunUi();
  state.runLabel = "一键运行";
  state.runBusy = false;
  state.runDisabled = false;
  /* 只还原这张卡片自己的触发状态（没跑过就是「就绪」） */
  applyRunMemory();

  document.title = `${s.title} · 手机遥控台`;
  writeText(STORAGE_KEYS.last, s.id);
  addRecent(s.id);
  return true;
}

/** 运行中不允许换场景，给个提示 */
export function trySelect(id: string): void {
  if (isBusy()) {
    toast("运行中，结束后再切换场景", true);
    return;
  }
  selectScenario(id);
}

/** ↑↓ 在可见列表里循环切换 */
export function cycleScenario(dir: number): void {
  if (isBusy()) return;
  const list = currentVisible();
  if (!list.length) return;
  let idx = state.selected ? list.findIndex((s) => s.id === state.selected?.id) : -1;
  if (idx === -1) idx = dir > 0 ? -1 : 0;
  const next = list[(idx + dir + list.length) % list.length];
  selectScenario(next.id);
}

/** 分组折叠状态。
 *
 *  以前这里有个坑：折叠只在「无搜索、无筛选」时生效（组件里用
 *  `!filtering && collapsed.has(name)` 算 closed），而点分组头本身就会
 *  触发筛选 —— 于是一点分组就进了筛选态，折叠被永久锁死，表现得像
 *  「展开收起坏了」。
 *
 *  现在改成：折叠是纯用户意图，任何时候都生效；唯一例外是正在搜索
 *  （用户要找东西，别让折叠挡住结果）。 */
export function toggleGroupCollapsed(name: string): void {
  if (state.collapsed.has(name)) state.collapsed.delete(name);
  else state.collapsed.add(name);
  writeJSON(STORAGE_KEYS.collapsed, [...state.collapsed]);
}

/** 某个分组当前是否应该显示为折叠。
 *
 *  @param name  分组名
 *  @param searching  是否正在搜索（搜索时强制展开） */
export function isGroupClosed(name: string, searching: boolean): boolean {
  if (searching) return false;
  return state.collapsed.has(name);
}

/** 一次性展开全部分组 */
export function expandAllGroups(): void {
  state.collapsed.clear();
  writeJSON(STORAGE_KEYS.collapsed, []);
}

/** 一次性收起全部分组 */
export function collapseAllGroups(): void {
  const names = state.groups.map((g) => g.name);
  state.collapsed = new Set(names);
  writeJSON(STORAGE_KEYS.collapsed, names);
}

export function setFilter(name: string): void {
  state.activeFilter = name;
}

export function setQuery(q: string): void {
  state.query = q;
}

export function clearFilters(): void {
  state.query = "";
  state.activeFilter = "all";
}

/** 收藏开关：点一下在收藏 / 取消收藏之间切换。纯前端偏好，写 localStorage。 */
export function toggleFavorite(id: string): void {
  if (!id) return;
  if (state.favorites.includes(id)) {
    state.favorites = state.favorites.filter((x) => x !== id);
  } else {
    state.favorites = [id, ...state.favorites];
  }
  writeJSON(STORAGE_KEYS.favorites, state.favorites);
}

/** 某场景是否已收藏 */
export function isFavorite(id: string): boolean {
  return state.favorites.includes(id);
}

/** 从 localStorage 恢复上次的偏好 */
export function loadPrefs(): void {
  const rawCollapsed = readJSON<unknown>(STORAGE_KEYS.collapsed, null);
  if (Array.isArray(rawCollapsed)) {
    state.collapsed = new Set(rawCollapsed as string[]);
    collapsedRestored = true;
  } else {
    /* 首次访问：没有历史折叠记录。
     * 30 个场景、10 个分组如果全展开，侧栏内容会溢出一倍多，分组头被
     * 挤出可视区，用起来像「点不动」。所以首次全部收起，只自动展开
     * 「当前选中场景所在的那一组」，用户再按需展开其它。 */
    state.collapsed = new Set();
    collapsedRestored = false;
  }
  const rawRecent = readJSON<unknown>(STORAGE_KEYS.recent, []);
  state.recent = Array.isArray(rawRecent) ? (rawRecent as string[]) : [];
  const rawFavs = readJSON<unknown>(STORAGE_KEYS.favorites, []);
  state.favorites = Array.isArray(rawFavs) ? (rawFavs as string[]) : [];
  const gap = Number(readText(STORAGE_KEYS.shotGap));
  state.shotGap = Number.isFinite(gap) && gap >= 1 ? Math.min(60, Math.round(gap)) : 5;
  const theme = readText(STORAGE_KEYS.theme);
  state.theme = theme === "light" ? "light" : "dark";
}

/** 有没有恢复过用户的折叠偏好（false = 本次是首次，需要给个默认展开策略） */
let collapsedRestored = false;

/** 首次进入时默认全部收起。
 *
 *  为什么不是「展开当前选中组」：重要日卡片一个组就有 8 个条目，
 *  展开后仍会把后面 9 个分组头推出可视区 —— 用户看到的就是「点不动」。
 *  全部收起时 10 个分组头能一次看全（实测无溢出），想看哪个点箭头即可。
 *  已有历史偏好时尊重用户自己的选择，不覆盖。 */
export function applyInitialCollapse(): void {
  if (collapsedRestored) return;
  state.collapsed = new Set(state.groups.map((g) => g.name));
  writeJSON(STORAGE_KEYS.collapsed, [...state.collapsed]);
}

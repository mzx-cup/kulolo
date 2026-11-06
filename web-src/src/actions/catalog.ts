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

/** 收藏的分组折叠状态（只在「无搜索、无筛选」时生效，和以前一致） */
export function toggleGroupCollapsed(name: string): void {
  if (state.collapsed.has(name)) state.collapsed.delete(name);
  else state.collapsed.add(name);
  writeJSON(STORAGE_KEYS.collapsed, [...state.collapsed]);
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

/** 从 localStorage 恢复上次的偏好 */
export function loadPrefs(): void {
  const rawCollapsed = readJSON<unknown>(STORAGE_KEYS.collapsed, []);
  state.collapsed = new Set(Array.isArray(rawCollapsed) ? (rawCollapsed as string[]) : []);
  const rawRecent = readJSON<unknown>(STORAGE_KEYS.recent, []);
  state.recent = Array.isArray(rawRecent) ? (rawRecent as string[]) : [];
  const gap = Number(readText(STORAGE_KEYS.shotGap));
  state.shotGap = Number.isFinite(gap) && gap >= 1 ? Math.min(60, Math.round(gap)) : 5;
  const theme = readText(STORAGE_KEYS.theme);
  state.theme = theme === "light" ? "light" : "dark";
}

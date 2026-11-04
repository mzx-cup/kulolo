import { state } from "@/stores/core";
import type { ScenarioView } from "@/types/api";
import { STORAGE_KEYS, readText } from "@/lib/storage";
import { api } from "@/lib/api";
import { buildGroups, currentVisible, loadPrefs, selectScenario } from "./catalog";
import { syncMetaColor } from "./theme";
import { toast } from "./toast";

/** 首次加载：拉场景 → 建分组 → 恢复上次选中的那个。 */

export function initTheme(): void {
  loadPrefs();
  const saved = readText(STORAGE_KEYS.theme);
  const t = saved === "light" ? "light" : "dark";
  state.theme = t;
  document.documentElement.dataset.theme = t;
  /* 颜色只认 applyTheme 里那一份 META_COLOR，别再抄一遍 */
  syncMetaColor(t);
}

export async function loadScenarios(): Promise<void> {
  state.loading = true;
  state.loadError = "";

  let list: ScenarioView[] = [];
  try {
    const data = await api.scenarios();
    list = Array.isArray(data.scenarios) ? (data.scenarios as ScenarioView[]) : [];
  } catch {
    state.loading = false;
    state.loadError = "连不上本地服务，请确认 python main.py 仍在运行。";
    toast("读取场景列表失败", true);
    return;
  }

  if (!list.length) {
    state.loading = false;
    state.loadError = "服务没有返回任何场景。";
    return;
  }

  state.scenarios = list;
  buildGroups();

  if (state.activeFilter !== "all" && !state.groups.some((g) => g.name === state.activeFilter)) {
    state.activeFilter = "all";
  }
  state.recent = state.recent.filter((id) => state.scenarios.some((s) => s.id === id));

  const saved = readText(STORAGE_KEYS.last);
  const pick = state.scenarios.find((s) => s.id === saved) || state.scenarios[0];
  state.loading = false;
  selectScenario(pick.id, { silent: true, force: true });
}

export { currentVisible };

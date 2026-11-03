/** localStorage 的薄封装：所有读写都可能抛（隐私模式 / 配额），
 *  出错时一律静默降级，绝不让界面因为存不了东西而崩。 */

export const STORAGE_KEYS = {
  theme: "ui.theme",
  shotGap: "shotGapSec",
  last: "ui.lastScenario",
  recent: "ui.recent",
  collapsed: "ui.collapsedGroups",
} as const;

export function readJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writeJSON(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 隐私模式下无法写入，忽略 */
  }
}

export function writeText(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 同上 */
  }
}

export function readText(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

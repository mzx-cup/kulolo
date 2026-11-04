import { state } from "@/stores/core";
import { STORAGE_KEYS, writeText } from "@/lib/storage";

/* 各主题对应的 meta[theme-color] 色值 */
const META_COLOR: Record<string, string> = {
  dark: "#0b0610",
  light: "#fdf4f8",
  rose: "#0f0610",
  mint: "#081010",
  violet: "#0e0816",
  midnight: "#060a12",
} as const;

export type ThemeId = keyof typeof META_COLOR;

let switchTimer: number | null = null;

/** 所有可用主题的元信息（用于渲染选择器） */
export const THEMES: { id: ThemeId; label: string; desc: string }[] = [
  { id: "dark", label: "午夜粉", desc: "近黑紫调 + 樱粉，经典夜航" },
  { id: "light", label: "象牙纸感", desc: "奶油白 + 草莓粉，清甜日光" },
  { id: "rose", label: "夜幕草莓", desc: "深底 + 草莓红，甜美可爱" },
  { id: "mint", label: "雾隐薄荷", desc: "深底 + 薄荷绿，清新治愈" },
  { id: "violet", label: "星空薰衣草", desc: "深底 + 薰衣草紫，梦幻高级" },
  { id: "midnight", label: "深海午夜", desc: "深底 + 青蓝，冷静专业" },
];

/** 只同步 meta[theme-color]，不动 <html data-theme>。
 *  boot.initTheme 首屏已经手写过 data-theme，就用它来补 meta。 */
export function syncMetaColor(theme: string): void {
  const t = (theme as ThemeId) ?? "dark";
  const meta = document.querySelector<HTMLMetaElement>("#theme-color");
  if (meta) meta.content = META_COLOR[t] ?? META_COLOR.dark;
}

/** 落主题：写 <html data-theme>、meta[theme-color]，可选存盘。 */
export function applyTheme(theme: string, persist = true): void {
  const t = (theme as ThemeId) ?? "dark";
  state.theme = t as "dark" | "light" | "rose" | "mint" | "violet" | "midnight";
  document.documentElement.dataset.theme = t;
  if (persist) writeText(STORAGE_KEYS.theme, t);
  syncMetaColor(t);
}

/** 切主题时给 <html> 加一个短暂的 theme-switching class，
 *  样式表靠它把全局的 transition 收窄，避免整页元素同时闪一下。 */
export function toggleTheme(theme?: string): void {
  const fallback = state.theme === "dark" ? "light" : "dark";
  const next = (THEMES.find((t) => t.id === theme)?.id ?? fallback) as ThemeId;
  document.documentElement.classList.add("theme-switching");
  applyTheme(next);
  if (switchTimer !== null) clearTimeout(switchTimer);
  switchTimer = window.setTimeout(() => {
    document.documentElement.classList.remove("theme-switching");
    switchTimer = null;
  }, 420);
}

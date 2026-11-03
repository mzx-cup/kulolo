import { state } from "@/stores/core";
import { STORAGE_KEYS, writeText } from "@/lib/storage";

const META_COLOR = { dark: "#080b10", light: "#f2ebdd" } as const;

let switchTimer: number | null = null;

/** 落主题：写 <html data-theme>、meta[theme-color]，可选存盘。
 *  不存盘的那次是首屏调用（index.html 的内联脚本已经把值放进来了）。 */
export function applyTheme(theme: string, persist = true): void {
  const t = theme === "light" ? "light" : "dark";
  state.theme = t;
  document.documentElement.dataset.theme = t;
  if (persist) writeText(STORAGE_KEYS.theme, t);
  const meta = document.querySelector<HTMLMetaElement>("#theme-color");
  if (meta) meta.content = META_COLOR[t];
}

/** 切主题时给 <html> 加一个短暂的 theme-switching class，
 *  样式表靠它把全局的 transition 收窄，避免整页元素同时闪一下。 */
export function toggleTheme(): void {
  const next = state.theme === "light" ? "dark" : "light";
  document.documentElement.classList.add("theme-switching");
  applyTheme(next);
  if (switchTimer !== null) clearTimeout(switchTimer);
  switchTimer = window.setTimeout(() => {
    document.documentElement.classList.remove("theme-switching");
    switchTimer = null;
  }, 420);
}

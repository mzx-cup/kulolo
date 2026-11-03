import { api } from "@/lib/api";
import { refs } from "@/lib/refs";
import { STORAGE_KEYS, writeText } from "@/lib/storage";
import { state } from "@/stores/core";
import { toast } from "./toast";

/** 手机截图：定时刷新、手动刷新、放大查看。
 *  对象 URL 必须显式 revoke，否则每 5 秒一张会一直泄漏。 */

let shotUrl: string | null = null;
let inFlight = false;
let lastTag = "";
let timer: number | null = null;
let visible = !document.hidden;

export const isVisible = (): boolean => visible;

export function setVisible(v: boolean): void {
  visible = v;
}

/** 把一张图挂到设备画面上。先用 Image 预加载，成功了再换，
 *  避免刷新过程中画面闪成空白。 */
export function setShot(src: string, tag: string): void {
  const pre = new Image();
  pre.onload = () => {
    const screen = refs.deviceScreenEl;
    state.shotSrc = src;
    state.hasShot = true;
    if (screen) screen.style.setProperty("--shot-bg", `url("${src}")`);
    /* 先摘掉再挂上，强制重排一次让动画重播 */
    state.shotSwap = false;
    requestAnimationFrame(() => {
      state.shotSwap = true;
      window.setTimeout(() => {
        state.shotSwap = false;
      }, 520);
    });
  };
  pre.onerror = () => toast("截图加载失败", true);
  pre.src = src;
  lastTag = tag || lastTag;
  if (tag) state.shotTag = tag;
}

export async function fetchShot(tag: string): Promise<boolean> {
  if (inFlight) return false;
  inFlight = true;
  try {
    const r = await api.screenshot();
    if (!r.ok) return false;
    const blob = await r.blob();
    if (shotUrl) URL.revokeObjectURL(shotUrl);
    shotUrl = URL.createObjectURL(blob);
    setShot(shotUrl, tag);
    return true;
  } catch {
    return false;
  } finally {
    inFlight = false;
  }
}

export async function manualShot(): Promise<void> {
  if (inFlight) {
    toast("截图正在刷新，稍等一下");
    return;
  }
  const ok = await fetchShot("手动刷新 " + new Date().toLocaleTimeString());
  if (!ok) toast("截图失败", true);
}

/** 自动刷新：setTimeout 递归（不用 setInterval），
 *  这样改间隔能立刻生效，也不会在切后台时堆任务。 */
export function shotSchedule(): void {
  if (timer !== null) clearTimeout(timer);
  if (state.shotGap <= 0) return;
  timer = window.setTimeout(async () => {
    if (visible && state.connected === true && !state.running && !state.starting) {
      await fetchShot("自动刷新 " + new Date().toLocaleTimeString());
    }
    shotSchedule();
  }, state.shotGap * 1000);
}

export function setShotGap(v: number): void {
  const n = Number.isFinite(v) ? Math.min(60, Math.max(1, Math.round(v))) : 5;
  state.shotGap = n;
  writeText(STORAGE_KEYS.shotGap, String(n));
  shotStateRefresh();
  shotSchedule();
}

/** 右下角那行小字：现在到底是「刷新中」还是「已暂停」 */
export function shotStateRefresh(): void {
  let text: string;
  let on = false;
  if (state.running) {
    text = "运行中暂停";
  } else if (state.connected !== true) {
    text = "等待设备";
  } else if (!visible) {
    text = "后台暂停";
  } else if (state.shotGap > 0) {
    text = "刷新中";
    on = true;
  } else {
    text = "已暂停";
  }
  state.shotStateText = text;
  state.shotStateOn = on;
}

export function openLightbox(): void {
  if (!state.hasShot) {
    toast("还没有截图，先刷新一次吧");
    return;
  }
  state.lightboxOpen = true;
  document.body.classList.add("lightbox-open");
}

export function closeLightbox(): void {
  if (!state.lightboxOpen) return;
  state.lightboxOpen = false;
  document.body.classList.remove("lightbox-open");
}

export const currentTag = (): string => lastTag;

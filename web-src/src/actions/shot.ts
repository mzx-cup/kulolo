import { api } from "@/lib/api";
import { refs } from "@/lib/refs";
import { STORAGE_KEYS, writeText } from "@/lib/storage";
import { state } from "@/stores/core";
import { toast } from "./toast";

/** 手机截图：定时刷新、手动刷新、放大查看。
 *  对象 URL 必须显式 revoke，否则每 5 秒一张会一直泄漏。 */

let shotUrl: string | null = null;
let lastTag = "";
let timer: number | null = null;
let visible = !document.hidden;

/** 截图结果：失败时带上可读原因，别再一律丢一句「截图失败」 */
type ShotResult = { ok: true } | { ok: false; reason: string };

/** 串行队列：自动刷新和手动刷新撞在一起时排队，而不是互相顶掉后误报失败。
 *  旧的 inFlight 布尔会让「正在自动刷新」期间的手动点击直接拿到 false → 红色错误提示。 */
let queue: Promise<unknown> = Promise.resolve();

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
    /* KeepAlive 下触发页/消失页各有一个 .device-screen（refs 只指向当前显示的那个），
     *  模糊底图逐个写，切页回来不会拿到过期画面 */
    const bg = `url("${src}")`;
    for (const el of document.querySelectorAll<HTMLElement>(".device-screen")) {
      el.style.setProperty("--shot-bg", bg);
    }
    if (screen) screen.style.setProperty("--shot-bg", bg);
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

/** 打一次截图请求，返回可读结果。signal 用于手动刷新的超时取消。 */
async function shotOnce(tag: string, signal?: AbortSignal): Promise<ShotResult> {
  /* 进队列时可能已排队了一会，超时取消的请求就别再发了 */
  if (signal?.aborted) return { ok: false, reason: "截图超时，请重试" };
  try {
    const r = await api.screenshot(signal);
    if (!r.ok) {
      /* 后端 5xx 会带 JSON {error:...}，把它读出来给用户看真正的原因 */
      let reason = `截图服务返回 ${r.status}`;
      try {
        const data = (await r.json()) as { error?: string };
        if (data?.error) reason = data.error;
      } catch { /* 非 JSON 就保留状态码 */ }
      return { ok: false, reason };
    }
    const blob = await r.blob();
    if (signal?.aborted) return { ok: false, reason: "截图超时" };
    if (shotUrl) URL.revokeObjectURL(shotUrl);
    shotUrl = URL.createObjectURL(blob);
    setShot(shotUrl, tag);
    return { ok: true };
  } catch (e) {
    if (signal?.aborted) return { ok: false, reason: "截图超时，请重试" };
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, reason: msg.includes("fetch")
      ? "本地服务无响应，请确认后端已启动"
      : msg };
  }
}

/** 串行执行：把任务挂到队列尾巴，保证同一时刻只有一次请求在跑。 */
function enqueue(tag: string, signal?: AbortSignal): Promise<ShotResult> {
  const job = queue.then(() => shotOnce(tag, signal));
  /* 无论成功失败都让队列继续走，别把后面的任务卡死 */
  queue = job.catch(() => undefined);
  return job;
}

export async function fetchShot(tag: string): Promise<boolean> {
  const r = await enqueue(tag);
  return r.ok;
}

/** 手动刷新：先给 loading 反馈，成功/失败都有明确提示，
 *  并显示后端返回的真实原因，不再出现「点了没反应、还弹个笼统红错」。
 *  不依赖 state.connected 前置拦截（轮询可能滞后），一律真发请求由后端裁决。 */
export async function manualShot(): Promise<void> {
  if (state.shotBusy) return;
  state.shotBusy = true;
  const ctrl = new AbortController();
  const timeout = window.setTimeout(() => ctrl.abort(), 12000);
  try {
    const r = await enqueue("手动刷新 " + new Date().toLocaleTimeString(), ctrl.signal);
    if (!r.ok) toast(r.reason, true);
    else toast("画面已刷新");
  } finally {
    clearTimeout(timeout);
    state.shotBusy = false;
  }
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

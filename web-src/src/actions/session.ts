import { state } from "@/stores/core";
import type { LogLine, StepItem } from "@/stores/core";
import { refs } from "@/lib/refs";
import { nowText, pad2 } from "@/lib/format";

/** 会话层：一次「运行」界面的全部可变部分 —— 步骤、日志、进度、倒计时。
 *  它只依赖 state 和 refs，不引用任何其它 action 文件，
 *  这样 catalog / run 都可以放心引用它而不会形成循环依赖。 */

let elapsedTimer: number | null = null;
let elapsedClearTimer: number | null = null;
let runStart = 0;
let runEstimateSec = 0;
let uiRunToken = 0;

/** 这一份 run.result 属于哪个场景。
 *
 *  没有它就会出「切到别张卡片还显示上一张的完成结果」：服务端 `_state`
 *  会一直抱着上一轮的 result，轮询每秒都在，`resetRunUi` 清完界面，
 *  下一次 poll 又把旧 summary 写回来。 */
let runOwner: string | null = null;

export function setRunOwner(id: string | null | undefined): void {
  runOwner = id ?? null;
}

/** 只有「结果归属的场景就是当前选中的场景」时才允许渲染它 */
export function runOwnerIs(id: string | null | undefined): boolean {
  return runOwner !== null && runOwner === id;
}

/** 当前这一轮归属的场景 id（没有归属就是 null） */
export function currentRunOwner(): string | null {
  return runOwner;
}

/* ── 每张卡片各自的触发状态 ────────────────────────────────────────
   服务端只有一个全局 result，所以归属由前端记。跑完把结果存到它自己
   那张卡片名下；换卡片时只还原该卡片自己的那份，绝不会串到别的卡片。 */
type RunMemory = { tone: "ok" | "fail"; text: string; progress: number };
const runMemory = new Map<string, RunMemory>();

export function rememberRun(id: string | null | undefined, rec: RunMemory | null): void {
  if (!id) return;
  if (rec) runMemory.set(id, rec);
  else runMemory.delete(id);
}

/** 把当前选中卡片自己的状态套回界面（没有就回到「就绪」） */
export function applyRunMemory(): void {
  const id = state.selected?.id;
  const rec = id ? runMemory.get(id) : undefined;
  if (rec) {
    state.runTone = rec.tone;
    state.runStateText = rec.text;
    state.progress = rec.progress;
  } else {
    state.runTone = "idle";
    state.runStateText = "就绪。点按钮后全程自动，请勿拔线。";
    state.progress = 0;
  }
}

export function bumpRunToken(): number {
  uiRunToken += 1;
  return uiRunToken;
}
export const runToken = (): number => uiRunToken;

/* ── 步骤 ─────────────────────────────────────────────────────────── */

export function pushStep(no: number, title: string): void {
  if (state.steps.some((s) => s.no === no)) return;
  state.steps.push({ no, title, state: "doing", ms: 0, detail: "" });
  state.stepsLive = true;
}

export function finishStep(no: number, ok: boolean, ms: number, detail: string): void {
  const step = state.steps.find((s) => s.no === no);
  if (!step) return;
  step.state = ok ? "ok" : "fail";
  step.ms = ms;
  step.detail = detail;
}

/* ── 日志 ─────────────────────────────────────────────────────────── */

const LOG_LIMIT = 600;

/** 追加一行日志。贴底时自动滚到底，翻上去看历史时不打断。 */
export function appendLine(kind: LogLine["kind"], text: string): void {
  const box = refs.logEl;
  const nearBottom = box ? box.scrollHeight - box.scrollTop - box.clientHeight < 80 : true;

  state.logSeq += 1;
  state.logs.push({ id: state.logSeq, ts: nowText(), kind, text });
  if (state.logs.length > LOG_LIMIT) state.logs.splice(0, state.logs.length - LOG_LIMIT);

  if (nearBottom && box) {
    requestAnimationFrame(() => {
      box.scrollTop = box.scrollHeight;
    });
  }
}

export function clearLog(): void {
  state.logs = [];
}

/* ── 进度 ─────────────────────────────────────────────────────────── */

export function startClock(estimateSec: number): void {
  stopClock();
  runEstimateSec = estimateSec;
  runStart = Date.now();
  state.progress = 0;
  state.elapsedText = "00:00";
  state.elapsedFade = false;
  elapsedTimer = window.setInterval(tickElapsed, 250);
}

export function stopClock(): void {
  if (elapsedTimer !== null) clearInterval(elapsedTimer);
  elapsedTimer = null;
}

/** 跑完之后让时间再停留一小会儿，别一结束就清零 */
export function fadeElapsedLater(): void {
  if (elapsedClearTimer !== null) clearTimeout(elapsedClearTimer);
  elapsedClearTimer = window.setTimeout(() => {
    if (!state.running) {
      state.elapsedFade = true;
      window.setTimeout(() => {
        if (!state.running) state.elapsedText = "";
      }, 400);
    }
    elapsedClearTimer = null;
  }, 1600);
}

export function tickElapsed(): void {
  if (!runStart) return;
  const s = Math.floor((Date.now() - runStart) / 1000);
  state.elapsedText = `${pad2(Math.floor(s / 60))}:${pad2(s % 60)}`;
  if (!runEstimateSec) return;
  const p = 0.95 * (1 - Math.exp((-1.7 * s) / Math.max(15, runEstimateSec)));
  if (p <= state.progress) return;
  state.progress = Math.min(0.95, p);
}

/** 结束一瞬间把进度条推满，视觉上有个收束 */
export function finishClock(ok: boolean): void {
  stopClock();
  state.progress = ok ? 1 : state.progress;
  fadeElapsedLater();
}

/* ── 整块重置 ─────────────────────────────────────────────────────── */

/** 新开一轮 / 切换场景时把所有运行期状态清干净。
 *  注意：这里不动 selected / params —— 那是 catalog 的职责。 */
export function resetRunUi(): void {
  bumpRunToken();
  stopClock();
  if (elapsedClearTimer !== null) clearTimeout(elapsedClearTimer);
  elapsedClearTimer = null;
  runStart = 0;
  runEstimateSec = 0;
  /* 换场景 / 新开一轮：上一轮的 result 不再属于当前界面 */
  runOwner = null;

  state.steps = [];
  state.stepsLive = false;
  state.logs = [];
  state.countdown = "";
  state.countdownLive = false;
  state.progress = 0;
  state.elapsedText = "00:00";
  state.elapsedFade = false;
  state.verifyOpen = false;
  state.askOpen = false;
  state.retryOpen = false;
  state.stopOpen = false;
  state.pendingConfirm = false;
  state.pendingAsk = false;
  state.runTone = "idle";
  state.runStateText = "就绪。点按钮后全程自动，请勿拔线。";
  state.fxOpen = false;
  state.fxOut = false;
}

/** 反查某一步现在处于什么状态（模板里用来挂 class） */
export function stepStateOf(item: StepItem): string {
  return item.state;
}

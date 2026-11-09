import { api } from "@/lib/api";
import { refs } from "@/lib/refs";
import { RETRYABLE, estimateRunSeconds, pad2 } from "@/lib/format";
import { state } from "@/stores/core";
import type { RunEvent, RunSnapshot } from "@/types/api";
import { collectParams } from "./params";
import { toast } from "./toast";
import { isBusy, selectScenario } from "./catalog";
import { refreshCards } from "./device";
import { setShot, shotStateRefresh } from "./shot";
import {
  appendLine,
  bumpRunToken,
  clearLog,
  finishClock,
  finishStep,
  pushStep,
  resetRunUi,
  setRunOwner,
  runOwnerIs,
  currentRunOwner,
  rememberRun,
  startClock,
  stopClock,
  runToken,
} from "./session";

/** 运行编排：发起、事件渲染、结算动效、确认询问。
 *  这是 app.js 里最长的一段（poll + renderEvent + runScenario + 各种 settle），
 *  拆开之后每个函数只做一件事。 */

let lastId = 0;
let eventsPrimed = false;
let wasRunning = false;
let suppressStaleResult = false;
let fxTimers: number[] = [];

export const isRunning = (): boolean => wasRunning;

/* ── 启动一轮 ─────────────────────────────────────────────────────── */

export async function runScenario(extra: Record<string, string | number> = {}): Promise<void> {
  if (!state.selected || isBusy()) return;

  const params = collectParams();
  state.starting = true;
  resetRunUi();
  /* 这一轮的 result 只属于当前选中的场景，切走后不允许再渲染它 */
  setRunOwner(state.selected.id);
  state.runDisabled = true;
  state.runBusy = true;
  state.runLabel = "启动中…";
  state.runTone = "doing";
  state.runStateText = "正在启动场景…";
  /* 选场景 / 新开跑时，先别把上一轮遗留的 result 当成这一轮的结论 */
  suppressStaleResult = true;

  try {
    const r = await api.run(state.selected.id, { ...params, ...extra });
    if (r.error) {
      state.starting = false;
      state.runDisabled = false;
      state.runBusy = false;
      state.runLabel = "一键运行";
      state.runTone = "fail";
      state.runStateText = r.error;
      rememberRun(state.selected?.id, { tone: "fail", text: r.error, progress: 1 });
      appendLine("err", "!! " + r.error);
      toast(r.error, true);
    } else {
      toast("已开始，全程自动执行");
      state.runTone = "doing";
      state.runStateText = "已启动，正在接管手机…";
      startClock(estimateRunSeconds(state.selected, params as Record<string, string>));
    }
  } catch {
    state.starting = false;
    state.runDisabled = false;
    state.runBusy = false;
    state.runLabel = "一键运行";
    state.runTone = "fail";
    state.runStateText = "启动失败：本地服务无响应";
    rememberRun(state.selected?.id, { tone: "fail", text: "启动失败：本地服务无响应", progress: 1 });
    toast("启动失败：本地服务无响应", true);
  }
}

/* ── 事件渲染 ─────────────────────────────────────────────────────── */

export function renderEvent(e: RunEvent, run: RunSnapshot | null): void {
  switch (e.t) {
    case "step": {
      if (e.state === "start") {
        pushStep(e.no, e.title ?? "");
        appendLine("evt", `[${pad2(e.no)}] ${e.title ?? ""}`);
        scrollStepIntoView(e.no);
      } else {
        const ok = e.state === "ok";
        finishStep(e.no, ok, e.ms ?? 0, e.detail ?? "");
        appendLine(ok ? "ok" : "err", (e.detail ?? "").trim());
        scrollStepIntoView(e.no);
      }
      break;
    }
    case "log":
      appendLine("detail", "· " + (e.msg ?? ""));
      break;
    case "shot":
      setShot("data:image/png;base64," + e.png_b64, `#${pad2(e.no)} ${e.tag ?? ""}`);
      break;
    case "tick":
      state.countdown = `息屏 ${e.remain}s`;
      state.countdownLive = true;
      break;
    case "error":
      appendLine("err", "!! " + (e.msg ?? ""));
      toast("执行失败：" + (e.msg ?? "未知错误"), true);
      break;
    case "card":
      /* 服务端自动识别卡片的结果（不再弹人工确认框）。
         成功时把实拍图挂到对应场景名下，前端卡片缩略图随之更新。 */
      if (e.ok) {
        const where = e.where === "lock" ? "锁屏" : "桌面";
        state.cardProbeOk = true;
        state.cardProbeText = `${where}识别到「${e.text ?? ""}」`;
        appendLine("ok", `自动识别：${state.cardProbeText}`);
        if (e.scenario) {
          void refreshCards();
        }
      } else {
        state.cardProbeOk = false;
        state.cardProbeText = "翻完轮播没找到卡片";
        appendLine("err", "自动识别：翻完智慧建议轮播仍未找到卡片");
      }
      break;
    case "done":
      state.countdownLive = false;
      break;
    case "confirm":
      /* 页面重载时服务端可能还留着历史事件；只在任务确实仍在等待时弹确认 */
      if (!run || !run.running) break;
      state.pendingConfirm = true;
      appendLine("detail", "等待确认：卡片是否已成功触发？");
      window.setTimeout(() => {
        if (state.pendingConfirm) state.verifyOpen = true;
      }, 280);
      break;
    case "ask":
      /* OOBE 国家询问已经下线：后端不再发 ask（改成开跑前自动检测 + 置灰）。
         万一收到历史事件，只记一行日志，不再弹窗拦住流程。 */
      appendLine("detail", "（旧版）前置询问：" + (e.prompt ?? ""));
      break;
    case "pause":
      appendLine("detail", "▮▮ 已暂停（可点「继续」恢复）");
      state.paused = true;
      break;
    case "resume":
      appendLine("detail", "▶ 已继续执行");
      state.paused = false;
      break;
    case "stop":
      appendLine("detail", "■ 用户请求结束场景");
      break;
    default:
      break;
  }
}

function scrollStepIntoView(no: number): void {
  const box = refs.stepsEl;
  if (!box) return;
  requestAnimationFrame(() => {
    const li = box.querySelector<HTMLElement>(`#step-${no}`);
    if (!li) return;
    const lr = li.getBoundingClientRect();
    const br = box.getBoundingClientRect();
    if (lr.top < br.top + 6 || lr.bottom > br.bottom - 6) {
      box.scrollTo({ top: box.scrollTop + (lr.top - br.top) - 12, behavior: "smooth" });
    }
  });
}

/* ── 轮询 ─────────────────────────────────────────────────────────── */

export async function poll(): Promise<void> {
  let d;
  try {
    d = await api.events(lastId);
  } catch {
    return;
  }
  if (!d || !d.run) return;
  const run = d.run;

  /* 首次轮询时如果服务端没在跑任务，就把历史事件直接标记为已读，
     避免一刷新页面就被上一轮的长日志刷屏。 */
  const skipHistory = !eventsPrimed && !run.running;
  eventsPrimed = true;
  for (const e of Array.isArray(d.events) ? d.events : []) {
    lastId = Math.max(lastId, e.id);
    if (!skipHistory) renderEvent(e, run);
  }

  if (run.running) {
    state.starting = false;
    suppressStaleResult = false;
    if (!wasRunning) {
      wasRunning = true;
      /* 页面刷新时后端正在跑，我们没有归属信息，就把它记到当前选中的场景名下 */
      if (!runOwnerIs(state.selected?.id)) setRunOwner(state.selected?.id);
      startClock(estimateRunSeconds(state.selected, state.params));
      shotStateRefresh();
    }
    state.running = true;
    state.paused = run.paused;
    state.runDisabled = true;
    state.runBusy = true;
    state.runLabel = "运行中";
    state.runTone = "doing";
    state.runStateText = run.paused ? "已暂停…点「继续」恢复" : "运行中…请勿拔线、勿手动操作手机。";
  } else {
    if (state.starting && (run.result || run.error)) {
      state.starting = false;
      /* 我们自己刚发起的这一轮已经结算，结果就是新的 */
      suppressStaleResult = false;
    }
    state.running = false;

    if (wasRunning) {
      wasRunning = false;
      suppressStaleResult = false;
      /* 切走了就别把这一轮的结算动效/进度套到别的卡片上（按钮状态照常复位） */
      if (runOwnerIs(state.selected?.id)) {
        stopClock();
        state.countdown = "";
        state.countdownLive = false;
        finishClock(Boolean(run.result && run.result.confirmed_ok !== false));
        shotStateRefresh();

        const token = runToken();
        const sid = state.selected?.id;
        if (run.result && !run.error && !state.pendingConfirm) {
          if (run.result.confirmed_ok === true) {
            window.setTimeout(() => {
              if (token !== runToken() || wasRunning) return;
              settleOk();
            }, 900);
          } else if (run.result.confirmed_ok === false) {
            const sel = state.selected;
            const canRetry = Boolean(sel) && (typeof sel?.retryable === "boolean" ? sel.retryable : RETRYABLE.has(sel!.id));
            window.setTimeout(() => {
              if (token !== runToken() || wasRunning) return;
              if (state.selected?.id !== sid) return;
              if (canRetry) showRetry();
              else settleFail();
            }, 900);
          }
        }
      }
    }

    if (!state.starting) {
      state.runDisabled = false;
      state.runBusy = false;
      state.runLabel = "一键运行";
      /* 结果先记到它自己那张卡片名下，再决定要不要渲染到当前界面——
         否则服务端抱着上一轮的 result，每张卡片都会显示上一张的完成结果。 */
      const owned = runOwnerIs(state.selected?.id);
      if (!suppressStaleResult && run.error) {
        const text = "失败：" + run.error;
        rememberRun(currentRunOwner(), { tone: "fail", text, progress: 1 });
        if (owned) {
          state.progress = 1;
          state.runTone = "fail";
          state.runStateText = text;
        }
      } else if (!suppressStaleResult && run.result) {
        const text = run.result.summary || "完成。";
        rememberRun(currentRunOwner(), { tone: "ok", text, progress: 1 });
        if (owned) {
          state.progress = 1;
          state.runTone = "ok";
          state.runStateText = text;
        }
      }
    }
  }
}

/* ── 确认 / 询问 / 暂停 / 结束 ────────────────────────────────────── */

export async function confirmAnswer(ok: boolean): Promise<void> {
  state.verifyOpen = false;
  state.pendingConfirm = false;
  try {
    const r = await api.confirm(ok);
    if (r.error) {
      state.pendingConfirm = true;
      state.verifyOpen = true;
      toast(r.error, true);
      return;
    }
    appendLine(ok ? "ok" : "err", ok ? "已确认：卡片成功触发，继续执行" : "已确认：卡片未触发，继续执行");
  } catch {
    state.pendingConfirm = true;
    state.verifyOpen = true;
    toast("确认失败：本地服务无响应", true);
  }
}

export async function pauseOrResume(): Promise<void> {
  const pausing = !state.paused;
  try {
    const r = pausing ? await api.pause() : await api.resume();
    if (r.error) toast(r.error, true);
  } catch {
    toast("操作失败：本地服务无响应", true);
  }
}

export async function stopRun(): Promise<void> {
  state.stopOpen = false;
  try {
    const r = await api.stop();
    if (r.error) toast(r.error, true);
    else toast("已请求结束当前场景");
  } catch {
    toast("操作失败：本地服务无响应", true);
  }
}

/* ── 结算动效 ─────────────────────────────────────────────────────── */

function clearFxTimers(): void {
  for (const t of fxTimers) clearTimeout(t);
  fxTimers = [];
}

/** 展示一张结算卡：hold 毫秒后淡出，再 650 毫秒摘掉 */
function showFx(kind: "ok" | "fail", hold: number): void {
  clearFxTimers();
  state.fxKind = kind;
  state.fxOut = false;
  state.fxOpen = true;
  fxTimers = [
    window.setTimeout(() => {
      state.fxOut = true;
    }, hold),
    window.setTimeout(() => {
      state.fxOpen = false;
      state.fxOut = false;
    }, hold + 650),
  ];
}

export function settleOk(): void {
  state.verifyOpen = false;
  state.pendingConfirm = false;
  showFx("ok", 3000);
}

export function settleFail(): void {
  state.verifyOpen = false;
  state.retryOpen = false;
  state.pendingConfirm = false;
  showFx("fail", 2600);
}

/* ── 重试 ─────────────────────────────────────────────────────────── */

export function showRetry(): void {
  state.verifyOpen = false;
  state.retryOpen = true;
  appendLine("detail", "卡片没出来，询问是否把目标日期平移一个月重试");
}

export function retryRun(): void {
  state.retryOpen = false;
  appendLine("detail", "用户选择重新触发：目标日期平移 +1 个月");
  void runScenario({ offset_months: 1, retry: 1 });
}

export function declineRetry(): void {
  state.retryOpen = false;
  settleFail();
}

/* ── 换场景时清场 ─────────────────────────────────────────────────── */

/** 只清「事件游标」之外的东西；真正重置界面在 session.resetRunUi。 */
export function resetForScenario(id: string): void {
  bumpRunToken();
  clearFxTimers();
  state.fxOpen = false;
  clearLog();
  selectScenario(id, { force: true });
}

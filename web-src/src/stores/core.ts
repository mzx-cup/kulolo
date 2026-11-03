import { reactive } from "vue";
import type { DeviceEntry, ScenarioGroup, ScenarioView } from "@/types/api";

/** 日志行：kind 决定颜色，text 是正文 */
export interface LogLine {
  /** 自增序号，仅用于 :key，避免同文本重复时复用错节点 */
  id: number;
  ts: string;
  kind: "evt" | "ok" | "err" | "detail";
  text: string;
}

/** 执行序列里的一步 */
export interface StepItem {
  no: number;
  title: string;
  state: "doing" | "ok" | "fail";
  ms: number;
  detail: string;
}

export type RunStateKind = "idle" | "doing" | "ok" | "fail";

/** 整个界面共享的唯一一份状态。
 *
 *  为什么不用 Pinia：这份状态只有一个消费者树（App 一个根），
 *  没有跨路由复用需求，加一层 store 库只是多一个文件和一个依赖。
 *  拆成 core（只有数据）+ 若干 actions 文件（各自 import core），
 *  就避免了循环依赖。 */
export const state = reactive({
  /* ── 场景目录 ─────────────────────────────────────────────── */
  scenarios: [] as ScenarioView[],
  groups: [] as ScenarioGroup[],
  selected: null as ScenarioView | null,
  activeFilter: "all",
  query: "",
  collapsed: new Set<string>(),
  recent: [] as string[],
  loading: true,
  loadError: "",
  catalogOpen: false,

  /* ── 参数 ─────────────────────────────────────────────────── */
  /** 当前场景的参数值，key 与 ScenarioParam.key 一致。
   *  time 型存 "H" 与 "M" 两个字段，键名是 `<key>.h` / `<key>.m`。 */
  params: {} as Record<string, string>,

  /* ── 运行 ─────────────────────────────────────────────────── */
  steps: [] as StepItem[],
  stepsLive: false,
  logs: [] as LogLine[],
  logSeq: 0,
  /** 进度条宽度，0~1（不叫 progressPct，避免和百分数混淆） */
  progress: 0,
  /** 已用时长，形如 "01:23" */
  elapsedText: "00:00",
  /** 结束后把已用时长淡出 */
  elapsedFade: false,
  countdown: "",
  countdownLive: false,
  running: false,
  paused: false,
  starting: false,
  /** 提交按钮上的文案：一键运行 / 启动中… / 运行中 */
  runLabel: "一键运行",
  runBusy: false,
  runDisabled: false,
  /** #runstate 状态胶囊的色调与文案 */
  runTone: "idle" as RunStateKind,
  runStateText: "就绪。点按钮后全程自动，请勿拔线。",
  /** 结算动效：显示中 / 已淡出 */
  fxOpen: false,
  fxKind: "ok" as "ok" | "fail",
  fxOut: false,

  /* ── 弹层 ─────────────────────────────────────────────────── */
  verifyOpen: false,
  askOpen: false,
  askPrompt: "",
  retryOpen: false,
  stopOpen: false,
  lightboxOpen: false,
  pendingConfirm: false,
  pendingAsk: false,
  toastText: "",
  toastKind: "" as "" | "err",
  toastShow: false,

  /* ── 设备 ─────────────────────────────────────────────────── */
  connected: null as boolean | null,
  devLabel: "检测设备中…",
  devTone: "loading" as "loading" | "on" | "off",
  devTitle: "设备状态",
  devAria: "",
  devMeta: "等待设备接入…",
  scrcpyPath: "",
  scrcpyDisabled: true,
  devices: [] as DeviceEntry[],
  selectedSerial: null as string | null,

  /* ── 截图 ─────────────────────────────────────────────────── */
  shotSrc: "",
  shotTag: "手机截图",
  hasShot: false,
  /** 换图瞬间给 <img> 挂 swap 动效 */
  shotSwap: false,
  shotGap: 5,
  shotStateText: "",
  shotStateOn: false,

  /* ── 外观 ─────────────────────────────────────────────────── */
  theme: "dark" as "dark" | "light",
});

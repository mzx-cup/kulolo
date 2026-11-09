import { reactive } from "vue";
import type {
  CardShot,
  CountryInfo,
  DeviceEntry,
  ModelInfo,
  RootInfo,
  ScenarioGroup,
  ScenarioView,
} from "@/types/api";

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
  /** 收藏的场景 id（收藏是纯前端偏好，不依赖后端） */
  favorites: [] as string[],
  loading: true,
  loadError: "",
  catalogOpen: false,
  /** 参数抽屉是否打开 */
  paramsOpen: false,

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
  /** OOBE 国家检测：null=还没读到；is_cn=false 时节日卡片置灰 */
  country: null as CountryInfo | null,
  /** root 检测：null=还没读到；is_root=false 时停电建议卡片置灰 */
  root: null as RootInfo | null,
  /** 型号检测：null=还没读到；is_note=true 时纪念日策划案卡置灰 */
  modelInfo: null as ModelInfo | null,
  devLabel: "检测设备中…",
  devTone: "loading" as "loading" | "on" | "off",
  devTitle: "设备状态",
  devAria: "",
  devMeta: "等待设备接入…",
  /** 电量百分比 0~100；-1 表示不可用 */
  battery: -1,
  /** 充电状态：charging / discharging / full / not-charging / unknown */
  batteryStatus: "",
  /** 系统版本，形如 "Android 14"；空串表示不可用 */
  androidVer: "",
  scrcpyPath: "",
  scrcpyDisabled: true,
  devices: [] as DeviceEntry[],
  selectedSerial: null as string | null,

  /* ── 截图 ─────────────────────────────────────────────────── */
  shotSrc: "",
  shotTag: "手机截图",
  hasShot: false,
  /** 手动刷新进行中：给按钮挂 loading 旋转，避免「点了没反应」 */
  shotBusy: false,
  /** 换图瞬间给 <img> 挂 swap 动效 */
  shotSwap: false,
  shotGap: 5,
  shotStateText: "",
  shotStateOn: false,

  /* ── 卡片库 ───────────────────────────────────────────────── */
  /** 自动识别时采集到的卡片实拍图：scenario id → 记录。
   *  由 /api/status 一起带回来（每 3~5 秒刷新），跑完一轮自动出现新图。 */
  cards: {} as Record<string, CardShot>,
  /** 放大查看的卡片场景 id；空表示没开灯箱 */
  cardZoomId: "",
  /** 运行事件里最近一次「自动识别结果」，给 Steps 面板显示 */
  cardProbeText: "",
  cardProbeOk: null as boolean | null,

  /* ── 底部 dock：页面切换 + 消失检测记录 ─────────────────────── */
  /** 当前页面："trigger"=卡片触发工作台 / "dismiss"=卡片消失检测台 */
  dockPage: "trigger" as "trigger" | "dismiss",
  /** 消失检测台的观察记录：行 id → "gone"=卡片消失 / "stay"=卡片仍在 */
  dismissObs: {} as Record<string, "gone" | "stay" | "">,

  /* ── 外观 ─────────────────────────────────────────────────── */
  theme: "dark" as "dark" | "light" | "rose" | "mint" | "violet" | "midnight",
});

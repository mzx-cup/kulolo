/**
 * 后端 /api/* 的接口形状，全部集中在这里。
 *
 * 这些类型是照着 main.py 的 _scenarios_json() / _events_after() / _status()
 * 手抄出来的；后端字段变了，这里没有跟着改，typecheck 会立刻报错 —— 这正是
 * 换成 TS 最主要的目的（以前靠人肉记住 25 个场景的字段名）。
 */

/** ── 场景参数 ─────────────────────────────────────────────────── */

export type ParamType = "number" | "time" | "text" | "select";

export interface SelectOption {
  /** 提交给后端的值 */
  v: string;
  /** 展示给用户的文案 */
  t: string;
}

export interface ScenarioParam {
  key: string;
  type: ParamType;
  label?: string;
  /** number 型的默认值 */
  value?: string | number;
  /** time 型的「时」默认值，缺省按 9 处理 */
  h?: number;
  /** time 型的「分」默认值，缺省按 30 处理 */
  m?: number;
  min?: number;
  max?: number;
  unit?: string;
  placeholder?: string;
  options?: SelectOption[];
}

/** Hero 面板右上角那排「规格」：k = 名称，v = 静态值；
 *  带 from 的表示要实时读某个参数输入框。 */
export interface ScenarioSpec {
  k: string;
  v?: string | number;
  /** 关联的参数 key，有值就实时同步显示 */
  from?: string;
  prefix?: string;
  suffix?: string;
}

export interface Scenario {
  id: string;
  title: string;
  tag: string;
  desc?: string;
  group?: string;
  icon?: string;
  params?: ScenarioParam[];
  specs?: ScenarioSpec[];
  retryable?: boolean;
}

/** 前端渲染时给场景补上的派生字段 */
export interface ScenarioView extends Scenario {
  /** 在整张清单里的序号（1 起），用于 UI 上显示 01 / 02 */
  _no: number;
  /** 归一化后的分组名（后端可能没给 group） */
  _group: string;
}

export interface ScenarioGroup {
  name: string;
  list: ScenarioView[];
  /** 该分组的强调色，形如 var(--tone-rose) */
  tone: string;
}

/** ── 运行事件（/api/events） ───────────────────────────────────── */

export type StepState = "start" | "ok" | "fail";

interface EventBase {
  id: number;
  t: string;
}

export interface StepEvent extends EventBase {
  t: "step";
  no: number;
  state: StepState;
  title?: string;
  detail?: string;
  ms?: number;
}

export interface LogEvent extends EventBase {
  t: "log";
  msg?: string;
}

export interface ShotEvent extends EventBase {
  t: "shot";
  no: number;
  tag?: string;
  png_b64: string;
}

export interface TickEvent extends EventBase {
  t: "tick";
  remain: number;
}

export interface ErrorEvent extends EventBase {
  t: "error";
  msg?: string;
}

export interface DoneEvent extends EventBase {
  t: "done";
}

export interface ConfirmEvent extends EventBase {
  t: "confirm";
}

export interface AskEvent extends EventBase {
  t: "ask";
  prompt?: string;
}

export interface PauseEvent extends EventBase {
  t: "pause";
}

export interface ResumeEvent extends EventBase {
  t: "resume";
}

export interface StopEvent extends EventBase {
  t: "stop";
}

export type RunEvent =
  | StepEvent
  | LogEvent
  | ShotEvent
  | TickEvent
  | ErrorEvent
  | DoneEvent
  | ConfirmEvent
  | AskEvent
  | PauseEvent
  | ResumeEvent
  | StopEvent;

/** 场景 run() 的返回值，只有前端真正读的字段写进来 */
export interface ScenarioResult {
  /** 卡片是否确认触发；缺省表示这个场景不询问 */
  confirmed_ok?: boolean;
  summary?: string;
  ok?: boolean;
  steps?: number;
  [key: string]: unknown;
}

export interface RunSnapshot {
  running: boolean;
  paused: boolean;
  result: ScenarioResult | null;
  error: string | null;
}

export interface EventsResponse {
  run: RunSnapshot;
  events: RunEvent[];
}

/** ── 设备状态（/api/status） ───────────────────────────────────── */

export interface DeviceEntry {
  serial: string;
  state: string;
}

export interface StatusResponse {
  connected: boolean;
  /** 找到的 scrcpy.exe 路径；空表示没找到，前端据此禁用按钮 */
  scrcpy?: string;
  serial?: string;
  model?: string;
  width?: number;
  height?: number;
  keyguard?: boolean;
  error?: string;
  devices?: DeviceEntry[];
  /** 用户手动指定的设备 serial（多机时） */
  selected?: string | null;
  run?: RunSnapshot;
}

/** ── 通用响应 ─────────────────────────────────────────────────── */

export interface ErrorResponse {
  error: string;
}

export interface ScenariosResponse {
  scenarios: Scenario[];
}

/** POST /api/scenario/<id> 的请求体：参数 + 重试附加项 */
export type RunRequestBody = Record<string, string | number>;

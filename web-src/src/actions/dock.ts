import { state } from "@/stores/core";
import { STORAGE_KEYS, readJSON, readText, writeJSON, writeText } from "@/lib/storage";

/** 底部 dock：触发 / 消失 不是两个动作，而是两个页面。
 *
 *  触发页 = 现在的卡片触发工作台（ScenarioStage 那套）。
 *  消失页 = 「卡片消失机制检测台」：按一套固定操作流程折腾桌面
 *  （关谷歌搜索 → 遍历网格 → 无字模式 → 无字+网格 → 超小模式往返），
 *  每个节点记录「卡片消失 / 卡片仍在」，用来验证各种桌面形态下
 *  卡片会不会被挤掉。
 *
 *  这里只管页面切换 + 检测记录的读写；后端自动化尚未接入。 */

export type DockPage = "trigger" | "dismiss";
/** 观察记录三态：gone=卡片消失 / stay=卡片仍在 / ""=还没观察 */
export type ObsValue = "gone" | "stay" | "";

/** 检测流程的一个观察节点 */
export interface DismissStep {
  id: string;
  /** 小阶段标题（时间轴分组） */
  phase: string;
  /** 这一步做什么 */
  title: string;
  /** 操作路径（怎么在手机上做到这一步） */
  how: string;
}

/** 卡片消失机制检测流程，共 9 个观察节点。
 *
 *  来源（用户口述流程）：先关掉桌面底部谷歌搜索，再遍历桌面设置里的
 *  「切换网格」（蜂窝网格、规则网格……全部遍历），然后开无字模式观察，
 *  无字模式下再切网格观察，最后切超小模式再切回来观察。 */
export const DISMISS_STEPS: DismissStep[] = [
  { id: "grid-any", phase: "切换网格", title: "遍历每种网格", how: "长按桌面 → 设置 → 切换网格，蜂窝网格 / 规则网格 / 其余网格逐一切换" },
  { id: "grid-honeycomb", phase: "切换网格", title: "蜂窝网格", how: "桌面设置 → 切换网格 → 蜂窝网格" },
  { id: "grid-regular", phase: "切换网格", title: "规则网格", how: "桌面设置 → 切换网格 → 规则网格" },
  { id: "wordless-on", phase: "无字模式", title: "打开无字模式", how: "桌面设置 → 无字模式 → 开启" },
  { id: "wordless-honeycomb", phase: "无字模式", title: "无字 + 蜂窝网格", how: "无字模式保持开启 → 切换网格 → 蜂窝网格" },
  { id: "wordless-regular", phase: "无字模式", title: "无字 + 规则网格", how: "无字模式保持开启 → 切换网格 → 规则网格" },
  { id: "wordless-other", phase: "无字模式", title: "无字 + 其余网格", how: "无字模式保持开启 → 切换网格 → 逐一切换剩下的网格" },
  { id: "tiny-in", phase: "超小模式", title: "切到超小模式", how: "设置 → 显示 → 超小模式（或桌面设置里）→ 切换到超小" },
  { id: "tiny-back", phase: "超小模式", title: "切回正常模式", how: "从超小模式切回正常模式，观察卡片是否回来" },
];

/** 前置准备（不产生观察记录，只是流程的第一步） */
export const DISMISS_PREP = {
  id: "prep-google",
  title: "关闭桌面底部谷歌搜索",
  how: "长按桌面底部的谷歌搜索栏 → 设置 → 关闭",
};

export function setDockPage(p: DockPage): void {
  if (state.dockPage === p) return;
  state.dockPage = p;
  writeText(STORAGE_KEYS.dockPage, p);
}

/** 读上次停留的页面；boot 时调一次（setDockPage 用 writeText 存纯串，这里对应 readText） */
export function loadDockPage(): void {
  const saved = readText(STORAGE_KEYS.dockPage);
  state.dockPage = saved === "dismiss" ? "dismiss" : "trigger";
}

/** 读观察记录；boot 时调一次 */
export function loadDismissObs(): void {
  state.dismissObs = readJSON<Record<string, ObsValue>>(STORAGE_KEYS.dismissObs, {});
}

/** 记一个观察结果；同一结果再点一次 = 取消（回到未观察） */
export function setObs(id: string, v: "gone" | "stay"): void {
  const next = { ...state.dismissObs };
  next[id] = next[id] === v ? "" : v;
  state.dismissObs = next;
  writeJSON(STORAGE_KEYS.dismissObs, next);
}

export function clearObs(): void {
  state.dismissObs = {};
  writeJSON(STORAGE_KEYS.dismissObs, {});
}

export function obsOf(id: string): ObsValue {
  return state.dismissObs[id] ?? "";
}

/** 已观察 / 已消失 / 仍在 的统计，给检测台头部用 */
export function obsStats(): { total: number; done: number; gone: number; stay: number } {
  let done = 0;
  let gone = 0;
  let stay = 0;
  for (const s of DISMISS_STEPS) {
    const v = obsOf(s.id);
    if (v === "gone") {
      done += 1;
      gone += 1;
    } else if (v === "stay") {
      done += 1;
      stay += 1;
    }
  }
  return { total: DISMISS_STEPS.length, done, gone, stay };
}

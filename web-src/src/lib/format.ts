/** 零碎格式化：以前散在 app.js 顶部的 pad2 / nowText / shortSerial，
 *  以及底部那段「按参数猜总时长」的估算逻辑。 */

export const pad2 = (n: number): string => String(n).padStart(2, "0");

export function nowText(): string {
  const d = new Date();
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

/** 设备序列号太长，只留后 8 位 */
export const shortSerial = (s: string): string => (s.length > 12 ? "…" + s.slice(-8) : s);

export const escapeRegExp = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** 进度条按「已用时间 / 预估总时长」平滑推进；长等待（warmup / wait_sec）
 *  会计入预估，所以 10 分钟预热不会几秒就冲到 100%。 */
export function estimateRunSeconds(
  scenario: { id?: string } | null,
  params: Record<string, string | number>,
): number {
  let sec = 30;
  const wait = Number(params.wait_sec);
  if (Number.isFinite(wait)) sec += Math.max(0, wait);
  const warm = Number(params.warmup_min);
  if (Number.isFinite(warm)) sec += Math.max(0, warm) * 60;
  // 跨国/跨城定位法要在两个城市各亮屏 N 分钟
  const each = Number(params.wait_min);
  if (Number.isFinite(each) && each > 0) sec += each * 60 * 2;
  const id = scenario?.id ?? "";
  if (/anniversary/.test(id)) sec += 60;
  if (/^festival_/.test(id)) sec += 15;
  if (/^(greeting|birthday|anniversary|important_day|show_day)/.test(id)) {
    sec += 45; // 首次 seed 可能走一次日历 UI；fast 路径会提前结束，影响不大
  }
  return Math.max(25, sec);
}

/** 这些场景没触发时值得「把日期挪一个月再试」，其余直接判失败 */
export const RETRYABLE = new Set([
  "greeting",
  "birthday",
  "anniversary",
  "anniversary_greeting",
  "exam",
  "exam_greeting",
  "show_day",
  "important_day",
]);

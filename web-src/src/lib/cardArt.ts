/** 卡片素材：每个场景「这张卡长什么样」的示意图 + 实拍图。
 *
 *  两类图来源不同，用途也不同：
 *
 *  * **素材图**（`public/cards/*.png`）—— 手工准备的设计稿，抠掉背景后当
 *    场景卡片的缩略图用。目前只有「考试祝福卡片」有（`exam-blessing.png`，
 *    由 `tools/make_card_art.py` 从 `资源/图片资源/_incoming/` 生成）。
 *  * **实拍图**（`/api/cards/<id>.png`）—— 自动识别卡片时截下来的真机截图，
 *    跑一次场景就有一张，优先展示它（比设计稿可信）。
 *
 *  两者都没有时，卡片退回原来的 SVG 图标（`lib/icons.ts`）。
 */

export interface CardArt {
  /** public/ 下的相对路径，Vite 会原样搬到 web/ 根目录 */
  src: string;
  /** 无障碍描述；也说给读屏用户听这是哪张卡 */
  alt: string;
}

/** 场景 id → 素材图。没列出 = 这张卡没有设计稿。 */
const ART: Record<string, CardArt> = {
  exam_greeting: { src: "./cards/exam-blessing.png", alt: "考试祝福卡片：四叶草「今天是Bday110792」" },
};

/** 取素材图；没有就返回 null，调用方退回 SVG 图标。 */
export function cardArt(scenarioId: string | undefined): CardArt | null {
  if (!scenarioId) return null;
  return ART[scenarioId] ?? null;
}

/** 实拍图的 URL。`ts` 用来破缓存 —— 同一场景重跑会覆盖同一张图，
 *  不加时间戳的话浏览器会一直显示旧的。
 *  返回空串表示这张卡还没采集过。 */
export function shotUrl(scenarioId: string, ts?: number): string {
  if (!scenarioId) return "";
  const stamp = ts ? `?ts=${Math.round(ts)}` : "";
  return `/api/cards/${encodeURIComponent(scenarioId)}.png${stamp}`;
}

/** 有素材图 / 实拍图，就应该用图片代替 SVG 图标。 */
export function hasArt(scenarioId: string | undefined): boolean {
  return cardArt(scenarioId) !== null;
}

/** 卡片素材：每个场景「这张卡长什么样」的示意图 + 实拍图。
 *
 *  两类图来源不同，用途也不同：
 *
 *  * **素材图**（`public/cards/*.png`）—— 手工准备的设计稿或真机截图，
 *    抠掉背景后当场景卡片的缩略图用（考试祝福卡片来自
 *    `资源/图片资源/_incoming/`，节日卡 / 个人知识库卡来自真机截图，
 *    都由 `tools/make_card_art.py` 裁成紧框 + 透明圆角）。
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

/** 场景 id → 素材图。没列出 = 这张卡没有素材图（退回 SVG 图标）。 */
const ART: Record<string, CardArt> = {
  exam_greeting: { src: "./cards/exam-blessing.png", alt: "考试祝福卡片：四叶草「今天是Bday110792」" },

  /* 节日祝福卡片：素材来自真机跑场景时的自动识别截图（桌面智慧建议小部件），
     由后端 `make_card_art.cutout_png` 裁成卡片紧框 + 透明圆角后存进卡片库，
     再原样拷到 public/cards/。工程上比只依赖 /api/cards 稳：卡片库在
     %APPDATA%，清缓存 / 换机器就没了；这些是随仓库走的静态兜底图。

     新年 / 端午 / 中秋这三张暂时**不登记**：它们没采到可用素材（每张卡基本
     只出一次，机会用掉了），登记了反而会指向不存在的 png、在页面上显示成
     裂图。缺省就是退回 SVG 图标 —— 等以后重新采到图再往这里加一行。 */
  festival_chunjie: { src: "./cards/festival_chunjie.png", alt: "春节祝福卡片：红灯笼「春节 · 团圆、喜悦与祝福，共迎新年」" },
  festival_guoqing: { src: "./cards/festival_guoqing.png", alt: "国庆节祝福卡片：城楼「国庆节快乐 · 经典盛典，岁岁荣光」" },
  festival_dongzhi: { src: "./cards/festival_dongzhi.png", alt: "冬至祝福卡片：汤圆水饺「冬至日 · 岁寒向暖，顺遂无忧」" },
  festival_shengdanye: { src: "./cards/festival_shengdanye.png", alt: "圣诞夜祝福卡片：圣诞树礼物「平安夜 · 光芒、希望与温暖，照亮整个夜晚」" },
  festival_shengdan: { src: "./cards/festival_shengdan.png", alt: "圣诞节祝福卡片：圣诞树「圣诞节快乐」" },

  /* 个人知识库授权卡片：蓝色底图的 TPK 自绘卡（serviceId=66071 / 规则
     10061）。控件树里没有文字，按文本识别会认成旁边的「玩机技巧卡」，所以
     素材图直接从真机节点日截图里按蓝色像素紧框裁出来（见 _t_pk40_d1.png）。
     圆角透明底，和节日卡片同一套 cutout_png 流程。 */
  personal_knowledge: { src: "./cards/personal_knowledge.png", alt: "个人知识库授权卡片：蓝色底图" },
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

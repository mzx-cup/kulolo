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

/** 真机语言。生活服务卡片会随系统语言变文案，一张卡要存三份图。 */
export type CardLang = "zh" | "en" | "ar";

/** 多语言卡片的一个语言版本：图 + 该语言下这一版的名字。 */
export interface CardLangArt extends CardArt {
  lang: CardLang;
  /** 灯箱里标在图下面的语言名（中文 / English / العربية） */
  label: string;
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

  /* 智能路况卡片（桌面智慧建议小部件里的「智能路况 / 大雨可能影响车费，
      请保持充足余额。/ 暴雨」）。素材来自真机 display 0 截图，按卡片紧框
      (639,241)-(1125,727) 裁出后走同一套 cutout_png 生成 512×512 透明
      圆角图，作为随仓库走的静态兜底素材。 */
  smart_traffic: { src: "./cards/smart_traffic.png", alt: "智能路况卡片：暴雨「大雨可能影响车费，请保持充足余额。」" },

  /* 年度总结卡片（体验报告组）。文案 `Hi, your Annual Summary is ready. / 2026`
     是**云端下发**的英文内容，切系统语言也不变（实测中文机也出英文），
     所以不按语言分版本，单图登记即可。素材来自真机跑 yearly_summary 场景时
     自动识别截下的卡片紧框，同一套 cutout_png 512×512 透明圆角。 */
  yearly_summary: { src: "./cards/summary_yearly.png", alt: "年度总结卡片：Hi, your Annual Summary is ready. 2026" },

  /* 月度总结卡片（体验报告组）。同一族的云端卡片，文案
     `Hi, your Monthly Report is ready. / Oct, 2026`，同样不随系统语言变。
     素材来自真机跑 monthly_summary 场景（时间设到下个月第二个周一 08:59）。 */
  monthly_summary: { src: "./cards/summary_monthly.png", alt: "月度总结卡片：Hi, your Monthly Report is ready. Oct, 2026" },
};

/** 多语言卡片：一个场景 → 真机各语言下的同一张卡。
 *
 *  为什么单独一张表而不是塞进 ART：ART 是「这张卡长什么样」的单图兜底，
 *  缩略图 / 最近栏 / 舞台卡都只要一张；而这批生活服务卡在真机上会**跟着
 *  系统语言换文案**（中文「出行时间 / 差不多该出发了」、英文「Ride Hailing /
 *  Time to get a ride」、阿拉伯语「طلب سيارة أجرة / حان وقت الحصول على رحلة」），
 *  是「同一张卡的三张照片」，得整组陈列。
 *
 *  数组顺序 = 场景中心缩略图优先级（中文在前）与灯箱展示顺序（中 → 英 → 阿）。
 *  三张图都是同一套 cutout_png 产出的 512×512 透明圆角图。 */
const LANG_ART: Record<string, CardLangArt[]> = {
  one_tap_taxi: [
    { lang: "zh", label: "中文", src: "./cards/one_tap_taxi_zh.png", alt: "一键打车出行卡片（中文）：出行时间「差不多该出发了」" },
    { lang: "en", label: "English", src: "./cards/one_tap_taxi_en.png", alt: "一键打车出行卡片（英文）：Ride Hailing「Time to get a ride」" },
    { lang: "ar", label: "العربية", src: "./cards/one_tap_taxi_ar.png", alt: "一键打车出行卡片（阿拉伯语）：طلب سيارة أجرة「حان وقت الحصول على رحلة」" },
  ],
  one_tap_food: [
    { lang: "zh", label: "中文", src: "./cards/one_tap_food_zh.png", alt: "一键点餐卡片（中文）：点餐时间「挑份喜欢的，准时开饭」" },
    { lang: "en", label: "English", src: "./cards/one_tap_food_en.png", alt: "一键点餐卡片（英文）：Food Ordering「Time to grab a bite」" },
    { lang: "ar", label: "العربية", src: "./cards/one_tap_food_ar.png", alt: "一键点餐卡片（阿拉伯语）：طلب الطعام「حان وقت تناول لقمة」" },
  ],

  /* 重要日分组 8 张卡：文案同样跟着系统语言变，三语文案实测如下 ——
   *
   *  生日（birthday）：  嗨，距离BdayNNNNNN还有 / Hi, Your BdayNNNNNN is in
   *  生日祝福（greeting）：嗨，BdayNNNNNN快乐！/ Happy BdayNNNNNN！
   *  考试（exam）：      距离BdayNNNNNN还有 3 天 / In 3 days
   *  考试祝福（exam_greeting）：今天是BdayNNNNNN / It's BdayNNNNNN today
   *  观演日（show_day）： 今天是BdayNNNNNN / It's BdayNNNNNN today
   *  重要日（important_day）：今天是BdayNNNNNN / It's BdayNNNNNN today
   *  纪念日（anniversary）：嗨，距离BdayNNNNNN还有 / Hi, Your BdayNNNNNN is in
   *  纪念日祝福（anniversary_greeting）：嗨，今天是BdayNNNNNN / It's BdayNNNNNN today
   *
   *  图都是真机跑场景时自动识别截下来的卡片紧框（512×512 透明圆角），
   *  由 `collect_id.py` 从卡片库按语言拷出后放进 public/cards/。 */
  birthday: [
    { lang: "zh", label: "中文", src: "./cards/important_birthday_zh.png", alt: "生日策划案卡片（中文）：嗨，距离BdayNNNNNN还有" },
  ],
  greeting: [
    { lang: "zh", label: "中文", src: "./cards/important_greeting_zh.png", alt: "生日祝福卡片（中文）：嗨，BdayNNNNNN快乐！" },
    { lang: "en", label: "English", src: "./cards/important_greeting_en.png", alt: "生日祝福卡片（英文）：Happy BdayNNNNNN！/ Generate Video" },
  ],
  exam: [
    { lang: "zh", label: "中文", src: "./cards/important_exam_zh.png", alt: "考试策划案卡片（中文）：距离考试还有 3 天，愿幸运四叶草保佑你" },
  ],
  exam_greeting: [
    { lang: "zh", label: "中文", src: "./cards/important_exam_greeting_zh.png", alt: "考试祝福卡片（中文）：今天是BdayNNNNNN，抽取你的幸运四叶草" },
  ],
  show_day: [
    { lang: "zh", label: "中文", src: "./cards/important_show_day_zh.png", alt: "观演日提醒卡片（中文）：今天是BdayNNNNNN" },
  ],
  important_day: [
    { lang: "zh", label: "中文", src: "./cards/important_important_day_zh.png", alt: "重要日提醒卡片（中文）：嗨，今天是BdayNNNNNN" },
    { lang: "en", label: "English", src: "./cards/important_important_day_en.png", alt: "重要日提醒卡片（英文）：It's BdayNNNNNN today" },
  ],
  anniversary: [
    { lang: "zh", label: "中文", src: "./cards/important_anniversary_zh.png", alt: "纪念日策划案卡片（中文）：嗨，距离BdayNNNNNN还有 3 天" },
    { lang: "en", label: "English", src: "./cards/important_anniversary_en.png", alt: "纪念日策划案卡片（英文）：Hi, Your BdayNNNNNN is in / Generate Plan" },
  ],
  anniversary_greeting: [
    { lang: "zh", label: "中文", src: "./cards/important_anniversary_greeting_zh.png", alt: "纪念日祝福卡片（中文）：嗨，今天是BdayNNNNNN" },
    { lang: "en", label: "English", src: "./cards/important_anniversary_greeting_en.png", alt: "纪念日祝福卡片（英文）：It's BdayNNNNNN today" },
  ],
};

/** 这张卡的全部语言版本；单图卡片返回空数组（灯箱退回单图模式）。 */
export function cardLangArts(scenarioId: string | undefined): CardLangArt[] {
  if (!scenarioId) return [];
  return LANG_ART[scenarioId] ?? [];
}

/** 取素材图；没有就返回 null，调用方退回 SVG 图标。
 *  多语言卡返回第一张 = 中文版（场景中心 / 最近栏 / 舞台卡都用它）。 */
export function cardArt(scenarioId: string | undefined): CardArt | null {
  if (!scenarioId) return null;
  const gallery = LANG_ART[scenarioId];
  if (gallery?.length) return gallery[0];
  return ART[scenarioId] ?? null;
}

/** 指定语言的那一版；没有就退回第一张（中文）。 */
export function cardArtOfLang(scenarioId: string | undefined, lang: CardLang): CardLangArt | null {
  const all = cardLangArts(scenarioId);
  if (!all.length) return null;
  return all.find((a) => a.lang === lang) ?? all[0];
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

import { state } from "@/stores/core";
import { cardArt, cardLangArts, shotUrl, type CardLangArt } from "@/lib/cardArt";

/** 卡片实拍：放大查看 + 取图地址。
 *
 *  单独一个文件是因为「组件里点一下」和「别处要算同一个 URL」是两件事：
 *  CardPanel 渲染缩略图，CardZoom 渲染大图，两边必须用**同一套规则**决定
 *  「这张卡该显示哪张图」（实拍优先、退回设计稿），否则点开大图会发现
 *  缩略图和大图不是同一张。 */

/** 这张卡当前该显示的图地址；既没采集过也没设计稿则返回空串。
 *
 *  多语言卡（一键打车 / 一键点餐 / 重要日 8 张）**固定用第一张素材图**
 *  （约定排在最前的是中文版），不跟实拍图走：实拍图是「上一次跑场景时
 *  真机什么语言就截到什么语言」，中文机上截到中文、阿语机上截到阿语，
 *  缩略图会随上次运行的语言跳来跳去。用户要求场景中心一律显示中文版，
 *  所以这里对这批卡跳过实拍、直接用静态素材。 */
export function artFor(scenarioId: string): string {
  const langs = cardLangArts(scenarioId);
  if (langs.length) return langs[0].src;
  const shot = state.cards[scenarioId];
  if (shot) return shotUrl(scenarioId, shot.ts);
  return cardArt(scenarioId)?.src ?? "";
}

export function openCardZoom(scenarioId: string): void {
  if (!artFor(scenarioId)) return;
  state.cardZoomId = scenarioId;
  document.body.classList.add("lightbox-open");
}

export function closeCardZoom(): void {
  if (!state.cardZoomId) return;
  state.cardZoomId = "";
  document.body.classList.remove("lightbox-open");
}

export function cardZoomOf(scenarioId: string): boolean {
  return state.cardZoomId === scenarioId;
}

/** 灯箱要显示的标题/副标题。 */
export function zoomLabel(): { title: string; sub: string; src: string } {
  const id = state.cardZoomId;
  if (!id) return { title: "", sub: "", src: "" };
  const sc = state.scenarios.find((s) => s.id === id);
  const shot = state.cards[id];
  const langs = cardLangArts(id);
  return {
    title: sc?.title ?? id,
    sub: langs.length
      ? `真机${langs.length > 1 ? "多语" : ""}卡片 · ${langs.map((a) => a.label).join(" / ")}`
      : shot
        ? `${shot.where === "lock" ? "锁屏" : "桌面"}识别 · ${shot.text || ""}`
        : "示意素材",
    src: artFor(id),
  };
}

/** 灯箱要陈列的整组图。
 *
 *  多语言卡返回中文 / 英文 / 阿拉伯语三张（顺序同 cardArt.ts 的 LANG_ART）；
 *  其它卡返回空数组，CardZoom 退回原来的单图布局。 */
export function zoomGallery(): CardLangArt[] {
  return cardLangArts(state.cardZoomId);
}

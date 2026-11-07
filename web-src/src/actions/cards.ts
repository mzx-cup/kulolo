import { state } from "@/stores/core";
import { cardArt, shotUrl } from "@/lib/cardArt";

/** 卡片实拍：放大查看 + 取图地址。
 *
 *  单独一个文件是因为「组件里点一下」和「别处要算同一个 URL」是两件事：
 *  CardPanel 渲染缩略图，CardZoom 渲染大图，两边必须用**同一套规则**决定
 *  「这张卡该显示哪张图」（实拍优先、退回设计稿），否则点开大图会发现
 *  缩略图和大图不是同一张。 */

/** 这张卡当前该显示的图地址；既没采集过也没设计稿则返回空串。 */
export function artFor(scenarioId: string): string {
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
  return {
    title: sc?.title ?? id,
    sub: shot
      ? `${shot.where === "lock" ? "锁屏" : "桌面"}识别 · ${shot.text || ""}`
      : "示意素材",
    src: artFor(id),
  };
}

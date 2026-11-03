/** 全局的弹层 / 抽屉 / 大图 / 涟漪这几个「DOM 副作用」工具。
 *  它们不碰运行时状态，只负责给 body / html 加 class、管理焦点。 */

export function setBodyClass(name: string, on: boolean): void {
  document.body.classList.toggle(name, on);
}

/** 给元素加一次性的动效 class（先摘掉再加，强制重排保证动画能重播）。 */
export function replayClass(el: Element | null, name: string, ms: number): void {
  if (!el) return;
  el.classList.remove(name);
  void (el as HTMLElement).offsetWidth;
  el.classList.add(name);
  window.setTimeout(() => el.classList.remove(name), ms);
}

/** 焦点落到弹层主按钮上；弹层已经关掉就什么都不做。 */
export function focusSoon(el: HTMLElement | null, delay = 90): void {
  if (!el) return;
  window.setTimeout(() => {
    if (!el.isConnected) return;
    try {
      el.focus({ preventScroll: true });
    } catch {
      el.focus();
    }
  }, delay);
}

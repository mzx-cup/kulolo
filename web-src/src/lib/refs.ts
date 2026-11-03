/** actions 层需要用到的 DOM 节点，由组件挂载时登记。
 *  以前这些是 app.js 顶部那张 $() 引用表；现在组件自己持有模板，
 *  只有少数「动作需要滚动/测量」的节点才登记到这里。 */

export const refs = {
  logEl: null as HTMLElement | null,
  stepsEl: null as HTMLElement | null,
  catalogScrollEl: null as HTMLElement | null,
  heroMainEl: null as HTMLElement | null,
  deviceScreenEl: null as HTMLElement | null,
  shotImgEl: null as HTMLImageElement | null,
};

export function setRef<K extends keyof typeof refs>(key: K, el: (typeof refs)[K]): void {
  refs[key] = el;
}

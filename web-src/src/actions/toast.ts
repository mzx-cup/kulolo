import { state } from "@/stores/core";

let timer: number | null = null;

/** 页面右下角的短提示。同一个时刻只显示一条，后来的顶掉前面的。 */
export function toast(msg: string, isErr = false): void {
  state.toastText = msg;
  state.toastKind = isErr ? "err" : "";
  state.toastShow = true;
  if (timer !== null) clearTimeout(timer);
  timer = window.setTimeout(() => {
    state.toastShow = false;
    timer = null;
  }, 3200);
}

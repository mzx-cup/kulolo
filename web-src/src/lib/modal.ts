import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { ComputedRef, Ref } from "vue";

export interface ModalState {
  /** 挂在根节点上的 hidden 属性 */
  hidden: Ref<boolean>;
  /** 挂在根节点上的 show 类（进场/退场动画靠它） */
  shown: Ref<boolean>;
  /** 根节点经常要用的一串绑定，模板里 v-bind 一次即可 */
  rootClass: ComputedRef<{ show: boolean }>;
  close: () => void;
}

/** 弹层的开合动画。
 *
 *  原来的写法是 showModal() 直接改 hidden + classList，然后 hideModal()
 *  延迟 270ms 才真正 hidden —— 这个延迟是为了让退场动画播完。Vue 里
 *  `<div :hidden="!open">` 会立刻消失，动画就没了，所以必须把这个
 *  时间差显式建模成两个状态：shown（是否加 .show）和 hidden（是否 display:none）。 */
export function useModal(open: Ref<boolean>, onClose?: () => void): ModalState {
  const shown = ref(false);
  const hidden = ref(!open.value);
  let hideTimer: number | null = null;

  function clearTimer(): void {
    if (hideTimer !== null) {
      window.clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  watch(
    open,
    (v) => {
      clearTimer();
      if (v) {
        hidden.value = false;
        /* 等一帧，让 display 从 none 变成可见后动画才有起点 */
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            shown.value = true;
          });
        });
      } else {
        shown.value = false;
        hideTimer = window.setTimeout(() => {
          if (!shown.value) hidden.value = true;
          hideTimer = null;
        }, 270);
      }
    },
    { immediate: true },
  );

  onBeforeUnmount(clearTimer);

  return {
    hidden,
    shown,
    rootClass: computed(() => ({ show: shown.value })),
    close: () => {
      if (onClose) onClose();
      else open.value = false;
    },
  };
}

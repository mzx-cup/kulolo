<script lang="ts">
import {
  computed,
  defineComponent,
  onBeforeUnmount,
  onMounted,
  ref,
} from "vue";

export interface SelectOption {
  v: string;
  t?: string;
}

/** 自绘下拉菜单。
 *
 *  原生 <select> 的选项浮层是浏览器/系统画的，CSS 根本够不着，
 *  白底、系统字体、没圆角，跟整套深色界面完全脱节。这里换成
 *  按钮 + 自绘列表，从触发器到浮层全部走同一套设计变量。
 *
 *  语义上仍然扮演 listbox：aria-haspopup / aria-expanded / role=option /
 *  aria-selected 都给全，键盘 Esc 关闭、Tab 照常移出。 */
export default defineComponent({
  name: "SelectMenu",
  props: {
    options: { type: Array as () => SelectOption[], default: () => [] },
    modelValue: { type: String, default: "" },
    label: { type: String, default: "" },
  },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    const open = ref(false);
    const root = ref<HTMLElement | null>(null);

    const current = computed(
      () =>
        props.options.find((o) => String(o.v) === props.modelValue)?.t ??
        props.modelValue,
    );

    function pick(v: string): void {
      emit("update:modelValue", v);
      open.value = false;
    }

    /** 点外面关掉。capture 阶段监听，避免按钮自身的 toggle 先被这里吃掉 */
    function onDocClick(e: MouseEvent): void {
      if (!open.value) return;
      if (root.value && !root.value.contains(e.target as Node)) {
        open.value = false;
      }
    }

    function onKey(e: KeyboardEvent): void {
      if (e.key === "Escape" && open.value) {
        open.value = false;
      }
    }

    onMounted(() => {
      document.addEventListener("click", onDocClick, true);
      document.addEventListener("keydown", onKey);
    });
    onBeforeUnmount(() => {
      document.removeEventListener("click", onDocClick, true);
      document.removeEventListener("keydown", onKey);
    });

    return { open, root, current, pick };
  },
});
</script>

<template>
  <span ref="root" class="sel" :class="{ open: open }">
    <button
      class="sel-btn"
      type="button"
      aria-haspopup="listbox"
      :aria-expanded="open ? 'true' : 'false'"
      :aria-label="label"
      @click="open = !open"
    >
      <span class="sel-val">{{ current }}</span>
      <svg class="sel-caret" viewBox="0 0 12 12" aria-hidden="true">
        <path
          d="M2.6 4.4 6 7.8l3.4-3.4"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>

    <transition name="sel-pop">
      <ul v-if="open" class="sel-menu" role="listbox" :aria-label="label">
        <li
          v-for="o in options"
          :key="String(o.v)"
          class="sel-opt"
          :class="{ on: String(o.v) === modelValue }"
          role="option"
          :aria-selected="String(o.v) === modelValue ? 'true' : 'false'"
          @click="pick(String(o.v))"
        >
          <span class="sel-opt-txt">{{ o.t ?? o.v }}</span>
          <svg
            v-if="String(o.v) === modelValue"
            class="sel-tick"
            viewBox="0 0 12 12"
            aria-hidden="true"
          >
            <path
              d="M2.2 6.3 4.7 8.8 9.8 3.4"
              fill="none"
              stroke="currentColor"
              stroke-width="1.7"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </li>
      </ul>
    </transition>
  </span>
</template>

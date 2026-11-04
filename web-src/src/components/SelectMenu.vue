<script lang="ts">
import {
  computed,
  defineComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  type CSSProperties,
} from "vue";

export interface SelectOption {
  v: string;
  t?: string;
}

const GAP = 6;
const MAX_H = 248;

/** 自绘下拉菜单。
 *
 *  原生 <select> 的选项浮层是浏览器/系统画的，CSS 根本够不着，
 *  白底、系统字体、没圆角，跟整套深色界面完全脱节。这里换成
 *  按钮 + 自绘列表，从触发器到浮层全部走同一套设计变量。
 *
 *  **浮层用 Teleport 挂到 body 上、position: fixed 定位。**
 *  之前它挂在 .sel 内部做绝对定位，被 .hero 的 overflow: hidden
 *  整块裁掉（裁剪发生在层叠之前，调 z-index 根本没用）。挂到
 *  body 后任何祖先的 overflow / transform / 层叠上下文都碰不到它，
 *  代价是要自己按按钮的 rect 算位置，并且滚动、缩放时实时跟随。
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
    const btn = ref<HTMLElement | null>(null);
    const menu = ref<HTMLElement | null>(null);
    const style = ref<CSSProperties>({});

    const current = computed(
      () =>
        props.options.find((o) => String(o.v) === props.modelValue)?.t ??
        props.modelValue,
    );

    /** 按触发按钮的视口矩形算出浮层位置；空间不够就向上翻 */
    function place(): void {
      const el = btn.value;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const roomBelow = window.innerHeight - r.bottom - GAP;
      const roomAbove = r.top - GAP;
      const wanted = Math.min(MAX_H, Math.max(props.options.length * 34 + 12, 60));
      const openUp = roomBelow < wanted && roomAbove > roomBelow;

      const width = Math.min(Math.max(r.width, 120), 320);
      const next: CSSProperties = {
        minWidth: `${Math.round(r.width)}px`,
        width: `${Math.round(width)}px`,
      };
      // 右边界别越出视口
      const left = Math.min(Math.max(r.left, 8), window.innerWidth - width - 8);
      next.left = `${Math.round(left)}px`;

      if (openUp) {
        next.bottom = `${Math.round(window.innerHeight - r.top + GAP)}px`;
        next.maxHeight = `${Math.round(Math.min(MAX_H, roomAbove))}px`;
      } else {
        next.top = `${Math.round(r.bottom + GAP)}px`;
        next.maxHeight = `${Math.round(Math.min(MAX_H, Math.max(roomBelow, 120)))}px`;
      }
      style.value = next;
    }

    function toggle(): void {
      open.value = !open.value;
      if (open.value) {
        place();
        void nextTick(place);
      }
    }

    function pick(v: string): void {
      emit("update:modelValue", v);
      open.value = false;
    }

    /** 点外面关掉。触发器在 root 里、浮层挂在 body 上，两处都要放行 */
    function onDocClick(e: MouseEvent): void {
      if (!open.value) return;
      const t = e.target as Node | null;
      if (root.value?.contains(t) || menu.value?.contains(t)) return;
      open.value = false;
    }

    function onKey(e: KeyboardEvent): void {
      if (e.key === "Escape" && open.value) {
        open.value = false;
      }
    }

    /** 浮层是 fixed 定位，页面一滚就脱位，得跟着走 */
    function onViewportChange(): void {
      if (open.value) place();
    }

    onMounted(() => {
      document.addEventListener("click", onDocClick, true);
      document.addEventListener("keydown", onKey);
      window.addEventListener("scroll", onViewportChange, true);
      window.addEventListener("resize", onViewportChange);
    });
    onBeforeUnmount(() => {
      document.removeEventListener("click", onDocClick, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onViewportChange, true);
      window.removeEventListener("resize", onViewportChange);
    });

    return { open, root, btn, menu, style, current, pick, toggle };
  },
});
</script>

<template>
  <span ref="root" class="sel" :class="{ open: open }">
    <button
      ref="btn"
      class="sel-btn"
      type="button"
      aria-haspopup="listbox"
      :aria-expanded="open ? 'true' : 'false'"
      :aria-label="label"
      @click="toggle"
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

    <Teleport to="body">
      <transition name="sel-pop">
        <ul
          v-if="open"
          ref="menu"
          class="sel-menu"
          role="listbox"
          :aria-label="label"
          :style="style"
        >
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
    </Teleport>
  </span>
</template>

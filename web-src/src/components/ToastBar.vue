<script lang="ts">
import { defineComponent } from "vue";
import { state } from "@/stores/core";

export default defineComponent({
  name: "ToastBar",
  setup() {
    return { state };
  },
});
</script>

<template>
  <div id="toast" class="toast" :class="{ show: state.toastShow, err: state.toastKind === 'err' }" role="status" aria-live="polite">
    {{ state.toastText }}
  </div>
</template>

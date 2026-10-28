<script setup lang="ts">
import {
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  useId,
  watch,
} from "vue";
import { X } from "lucide-vue-next";
const props = defineProps<{ open: boolean; title: string; wide?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const dialog = ref<HTMLDialogElement>();
const titleId = useId();
const offset = reactive({ x: 0, y: 0 });
const dragging = ref(false);
let previous: HTMLElement | null = null;
let observer: ResizeObserver | undefined;
let drag: {
  pointerId: number;
  x: number;
  y: number;
  left: number;
  top: number;
  target: HTMLElement;
} | null = null;
let moved = false;

function place(left: number, top: number) {
  const element = dialog.value;
  if (!element?.open) return;
  const box = element.getBoundingClientRect();
  const padding = 12;
  const x = Math.max(padding, Math.min(left, innerWidth - box.width - padding));
  const y = Math.max(
    padding,
    Math.min(top, innerHeight - box.height - padding),
  );
  offset.x = x - (innerWidth - box.width) / 2;
  offset.y = y - (innerHeight - box.height) / 2;
}
function keepInWindow() {
  const box = dialog.value?.getBoundingClientRect();
  if (box) place(box.left, box.top);
}
function startDrag(event: PointerEvent) {
  if (event.button !== 0 || !event.isPrimary || !dialog.value?.open) return;
  if (
    (event.target as Element).closest(
      "button, a, input, select, textarea, [contenteditable]",
    )
  )
    return;
  const box = dialog.value.getBoundingClientRect();
  const target = event.currentTarget as HTMLElement;
  drag = {
    pointerId: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    left: box.left,
    top: box.top,
    target,
  };
  moved = false;
  dragging.value = true;
  target.setPointerCapture(event.pointerId);
  event.preventDefault();
}
function moveDrag(event: PointerEvent) {
  if (!drag || event.pointerId !== drag.pointerId) return;
  const dx = event.clientX - drag.x,
    dy = event.clientY - drag.y;
  moved ||= Math.abs(dx) + Math.abs(dy) > 3;
  place(drag.left + dx, drag.top + dy);
  event.preventDefault();
}
function stopDrag() {
  const active = drag;
  drag = null;
  dragging.value = false;
  if (active?.target.hasPointerCapture(active.pointerId))
    active.target.releasePointerCapture(active.pointerId);
}
function backdropClick(event: MouseEvent) {
  if (moved) {
    moved = false;
    return;
  }
  const element = dialog.value;
  if (!element || event.target !== element) return;
  const box = element.getBoundingClientRect();
  if (
    event.clientX < box.left ||
    event.clientX > box.right ||
    event.clientY < box.top ||
    event.clientY > box.bottom
  )
    emit("close");
}
watch(
  () => props.open,
  async (open) => {
    await nextTick();
    if (open !== props.open) return;
    if (open) {
      previous = document.activeElement as HTMLElement;
      offset.x = 0;
      offset.y = 0;
      moved = false;
      if (!dialog.value?.open) dialog.value?.showModal();
    } else {
      stopDrag();
      dialog.value?.close();
      if (previous?.isConnected) previous.focus();
    }
  },
  { immediate: true },
);
onMounted(() => {
  observer = new ResizeObserver(keepInWindow);
  if (dialog.value) observer.observe(dialog.value);
  window.addEventListener("resize", keepInWindow);
});
onBeforeUnmount(() => {
  stopDrag();
  observer?.disconnect();
  window.removeEventListener("resize", keepInWindow);
  dialog.value?.close();
  if (previous?.isConnected) previous.focus();
});
</script>
<template>
  <dialog
    ref="dialog"
    class="modal"
    :class="{ wide }"
    :style="{ '--modal-x': `${offset.x}px`, '--modal-y': `${offset.y}px` }"
    :aria-labelledby="titleId"
    @cancel.prevent="emit('close')"
    @click="backdropClick"
  >
    <header
      class="modal-titlebar flex items-center justify-between mb-6"
      :class="{ 'is-dragging': dragging }"
      @pointerdown="startDrag"
      @pointermove="moveDrag"
      @pointerup="stopDrag"
      @pointercancel="stopDrag"
      @lostpointercapture="stopDrag"
    >
      <h2 :id="titleId">{{ title }}</h2>
      <button class="icon-btn" aria-label="关闭" @click="emit('close')">
        <X :size="18" />
      </button>
    </header>
    <slot />
    <footer v-if="$slots.footer" class="mt-6 flex justify-end gap-2">
      <slot name="footer" />
    </footer>
  </dialog>
</template>

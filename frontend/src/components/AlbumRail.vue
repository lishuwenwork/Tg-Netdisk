<script setup lang="ts">
import draggable from "vuedraggable";
import {
  ChevronLeft,
  ChevronRight,
  Film,
  GripVertical,
  Image as ImageIcon,
  Plus,
  X,
} from "lucide-vue-next";
import { useWorkspace } from "../stores/workspace";
import { mediaUrl } from "../lib/api";
import { time } from "../lib/format";
const emit = defineEmits<{ add: [] }>();
const store = useWorkspace();
function thumbnail(id: string, cover: string | null) {
  const asset = store.assets[id];
  return (
    cover || (asset?.kind === "image" ? id : asset?.metadata.thumbnails?.[0])
  );
}
</script>
<template>
  <section class="album-panel">
    <div class="flex items-center justify-between mb-4">
      <div class="flex gap-3 items-center">
        <h2>相册素材</h2>
        <span
          class="count-chip"
          :class="{ 'text-danger': store.draft.items.length > 10 }"
          >{{ store.draft.items.length }}
          <span class="text-muted">/ 10</span></span
        >
      </div>
      <button class="text-button" @click="emit('add')">
        <Plus :size="14" />添加素材
      </button>
    </div>
    <div class="album-scroll">
      <draggable
        v-model="store.draft.items"
        item-key="media_id"
        class="album-list"
        :animation="180"
        ghost-class="album-ghost"
        :scroll-sensitivity="70"
        :scroll-speed="12"
        :force-fallback="true"
        @end="store.autosave()"
      >
        <template #item="{ element, index }"
          ><article
            class="asset-card"
            :class="{ selected: store.selectedId === element.media_id }"
            tabindex="0"
            :aria-label="`素材 ${index + 1}：${store.assets[element.media_id]?.name || '素材丢失'}`"
            @click="store.select(element.media_id)"
            @keydown.enter="store.select(element.media_id)"
          >
            <div class="asset-thumb">
              <img
                v-if="thumbnail(element.media_id, element.cover_id)"
                :src="mediaUrl(thumbnail(element.media_id, element.cover_id)!)"
                alt=""
              /><Film
                v-else-if="store.assets[element.media_id]?.kind === 'video'"
                :size="23"
                class="text-muted"
              /><ImageIcon v-else :size="23" class="text-muted" /><span
                class="asset-number"
                >{{ String(index + 1).padStart(2, "0") }}</span
              ><button
                class="asset-remove"
                :aria-label="`移除素材 ${index + 1}`"
                @click.stop="store.remove(index)"
              >
                <X :size="12" /></button
              ><span v-if="element.cover_id" class="cover-badge">封面</span
              ><span class="asset-duration">{{
                store.assets[element.media_id]?.kind === "video"
                  ? time(store.assets[element.media_id]?.metadata.duration)
                  : "图片"
              }}</span>
            </div>
            <div class="asset-name">
              {{ store.assets[element.media_id]?.name || "文件不可用" }}
            </div>
            <div class="asset-bottom">
              <GripVertical :size="12" /><span>{{
                store.assets[element.media_id]?.status === "downloading"
                  ? "下载中"
                  : store.processing.has(element.media_id)
                    ? "分析中"
                    : store.assets[element.media_id]?.metadata.error
                      ? "不支持"
                      : ""
              }}</span>
              <div class="ml-auto flex">
                <button
                  class="icon-btn small"
                  :disabled="index === 0"
                  aria-label="前移"
                  @click.stop="store.move(index, -1)"
                >
                  <ChevronLeft :size="13" /></button
                ><button
                  class="icon-btn small"
                  :disabled="index === store.draft.items.length - 1"
                  aria-label="后移"
                  @click.stop="store.move(index, 1)"
                >
                  <ChevronRight :size="13" />
                </button>
              </div>
            </div></article
        ></template>
        <template #footer
          ><button class="add-card" aria-label="添加素材" @click="emit('add')">
            <Plus :size="23" :stroke-width="1" /></button
        ></template>
      </draggable>
    </div>
    <p v-if="store.draft.items.length > 10" class="field-error mt-3">
      超过 10 项，请拆分后提交
    </p>
  </section>
</template>

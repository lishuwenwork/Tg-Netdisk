<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  ChevronLeft,
  ChevronRight,
  FileVideo,
  Folder,
  Home,
  Image as ImageIcon,
  Search,
} from "lucide-vue-next";
import { api } from "../lib/api";
import { bytes } from "../lib/format";
import type { Asset } from "../types";
import UiModal from "./UiModal.vue";
import UiButton from "./UiButton.vue";
const props = withDefaults(
  defineProps<{ open: boolean; imagesOnly?: boolean; single?: boolean }>(),
  { imagesOnly: false, single: false },
);
const emit = defineEmits<{ close: []; selected: [assets: Asset[]] }>();
interface Entry {
  name: string;
  path: string;
  directory: boolean;
  size: number;
}
interface Listing {
  path: string;
  entries: Entry[];
  total: number;
  offset: number;
  limit: number;
}
const path = ref(""),
  query = ref(""),
  offset = ref(0),
  listing = ref<Listing>({
    path: "",
    entries: [],
    total: 0,
    offset: 0,
    limit: 100,
  });
const selected = ref<Set<string>>(new Set()),
  busy = ref(false),
  registering = ref(false),
  error = ref("");
let revision = 0;
const crumbs = computed(() => path.value.split("/").filter(Boolean));
async function browse(next = path.value, start = 0) {
  const current = ++revision;
  busy.value = true;
  error.value = "";
  path.value = next;
  offset.value = start;
  try {
    const result = await api<Listing>(
      `server-files?${new URLSearchParams({ path: next, query: query.value, offset: String(start), kind: props.imagesOnly ? "image" : "media" })}`,
    );
    if (current === revision) listing.value = result;
  } catch (cause) {
    if (current === revision)
      error.value = cause instanceof Error ? cause.message : "目录不可访问";
  } finally {
    if (current === revision) busy.value = false;
  }
}
function enter(next: string) {
  query.value = "";
  void browse(next);
}
function toggle(entry: Entry) {
  if (entry.directory) {
    enter(entry.path);
    return;
  }
  const values = new Set(props.single ? [] : selected.value);
  if (selected.value.has(entry.path)) values.delete(entry.path);
  else values.add(entry.path);
  selected.value = values;
}
async function confirm() {
  registering.value = true;
  error.value = "";
  try {
    const result = await api<{
      assets: Asset[];
      failures: { name: string; message: string }[];
    }>("server-files/register", "POST", { paths: [...selected.value] });
    if (result.failures.length) {
      error.value = result.failures
        .map((f) => `${f.name}：${f.message}`)
        .join("；");
      return;
    }
    emit("selected", result.assets);
    emit("close");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "选择失败";
  } finally {
    registering.value = false;
  }
}
watch(
  () => props.open,
  (open) => {
    revision++;
    if (open) {
      selected.value = new Set();
      query.value = "";
      void browse("");
    }
  },
);
</script>
<template>
  <UiModal
    :open="open"
    :title="imagesOnly ? '选择服务器图片' : '选择服务器文件'"
    wide
    @close="emit('close')"
    ><div class="server-picker">
      <div class="file-breadcrumb">
        <button class="icon-btn" aria-label="媒体根目录" @click="enter('')">
          <Home :size="16" /></button
        ><template v-for="(crumb, index) in crumbs" :key="index"
          ><ChevronRight :size="12" /><button
            class="text-button muted"
            @click="enter(crumbs.slice(0, index + 1).join('/'))"
          >
            {{ crumb }}
          </button></template
        >
      </div>
      <form class="file-search" @submit.prevent="browse(path)">
        <input
          v-model="query"
          class="field"
          placeholder="搜索当前目录"
          aria-label="搜索服务器文件"
        /><UiButton @click="browse(path)"><Search :size="15" />搜索</UiButton>
      </form>
      <p v-if="error" class="field-error mb-3" role="alert">{{ error }}</p>
      <div class="server-file-list" :aria-busy="busy">
        <div v-if="busy" class="file-empty"><span class="spinner" /></div>
        <template v-else
          ><button
            v-if="path"
            class="server-file-row"
            @click="enter(crumbs.slice(0, -1).join('/'))"
          >
            <ChevronLeft :size="17" /><span>上级目录</span></button
          ><button
            v-for="entry in listing.entries"
            :key="entry.path"
            class="server-file-row"
            :class="{ chosen: selected.has(entry.path) }"
            :aria-pressed="!entry.directory && selected.has(entry.path)"
            @click="toggle(entry)"
          >
            <Folder v-if="entry.directory" :size="18" /><ImageIcon
              v-else-if="/\.(png|jpe?g|webp)$/i.test(entry.name)"
              :size="18"
            /><FileVideo v-else :size="18" /><span class="file-name">{{
              entry.name
            }}</span
            ><span class="text-muted text-xs">{{
              entry.directory ? "目录" : bytes(entry.size)
            }}</span
            ><span v-if="!entry.directory" class="file-check">{{
              selected.has(entry.path) ? "✓" : ""
            }}</span
            ><ChevronRight v-else :size="14" />
          </button>
          <div v-if="!listing.entries.length" class="file-empty">
            暂无文件
          </div></template
        >
      </div>
      <div class="flex justify-between items-center mt-4 text-xs text-muted">
        <span>{{ listing.total }} 项 · 已选 {{ selected.size }} 项</span>
        <div class="flex gap-3">
          <UiButton
            :disabled="busy || offset === 0"
            @click="browse(path, Math.max(0, offset - 100))"
            >上一页</UiButton
          ><UiButton
            :disabled="busy || offset + 100 >= listing.total"
            @click="browse(path, offset + 100)"
            >下一页</UiButton
          >
        </div>
      </div>
    </div>
    <template #footer
      ><UiButton @click="emit('close')">取消</UiButton
      ><UiButton
        variant="primary"
        :busy="registering"
        :disabled="!selected.size || busy"
        @click="confirm"
        >{{ imagesOnly ? "选择图片" : "添加素材" }}</UiButton
      ></template
    ></UiModal
  >
</template>

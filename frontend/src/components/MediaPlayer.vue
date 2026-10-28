<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import {
  Camera,
  ChevronLeft,
  ChevronRight,
  Expand,
  Film,
  ImagePlus,
  Pause,
  Play,
  Volume2,
  VolumeX,
  ZoomIn,
  ZoomOut,
} from "lucide-vue-next";
import { useWorkspace } from "../stores/workspace";
import { mediaUrl, api } from "../lib/api";
import { bytes, time } from "../lib/format";
import { dataUrl, DecodedPlayer, exactFrame, openInput } from "../media/engine";
import type { Input } from "mediabunny";
import type { Asset } from "../types";
import UiButton from "./UiButton.vue";
import UiModal from "./UiModal.vue";

const emit = defineEmits<{ add: [] }>();
const store = useWorkspace();
const video = ref<HTMLVideoElement>(),
  canvas = ref<HTMLCanvasElement>(),
  surface = ref<HTMLElement>();
const playing = ref(false),
  inputReady = ref(false),
  position = ref(0),
  volume = ref(0.8),
  rate = ref(1),
  fallback = ref(false);
const zoom = ref(1),
  rangeStart = ref(0),
  busy = ref(false),
  frameOpen = ref(false);
const candidate = ref<{
  url: string;
  image: Blob;
  timestamp: number;
  source: string;
  width: number;
  height: number;
} | null>(null);
const asset = computed(() => store.current);
const duration = computed(() => asset.value?.metadata.duration || 0);
const playable = computed(
  () => asset.value?.kind === "video" && asset.value.metadata.video_decodable,
);
const controlsReady = computed(() => playable.value && inputReady.value);
let preciseTimestamp: number | null = null;
function updateTime() {
  const nativeTime = video.value?.currentTime || 0;
  // HTMLMediaElement may round a seek down to microseconds. Retain the selected decoded PTS.
  position.value =
    preciseTimestamp !== null &&
    !playing.value &&
    Math.abs(nativeTime - preciseTimestamp) < 0.005
      ? preciseTimestamp
      : nativeTime;
}
const span = computed(() => duration.value / zoom.value);
const thumbs = computed(() => asset.value?.metadata.thumbnails || []);
let input: Input | undefined,
  decoded: DecodedPlayer | undefined,
  loadRevision = 0;
function pause() {
  video.value?.pause();
  decoded?.pause();
  playing.value = false;
}
watch(
  () => `${asset.value?.id || ""}:${!!asset.value?.metadata.video_decodable}`,
  async () => {
    const revision = ++loadRevision;
    inputReady.value = false;
    preciseTimestamp = null;
    pause();
    const previousDecoded = decoded,
      previousInput = input;
    decoded = undefined;
    input = undefined;
    await previousDecoded?.dispose();
    previousInput?.dispose();
    if (revision !== loadRevision) return;
    position.value = 0;
    zoom.value = 1;
    rangeStart.value = 0;
    fallback.value = false;
    if (!playable.value || !asset.value) return;
    await store.guarded(async () => {
      const next = openInput(mediaUrl(asset.value!.id));
      input = next;
      const mime = await next.getMimeType();
      if (revision !== loadRevision) {
        next.dispose();
        return;
      }
      fallback.value = !document.createElement("video").canPlayType(mime);
      inputReady.value = true;
      await nextTick();
      if (fallback.value) await drawFrame();
    }, store.draftRevision);
  },
  { immediate: true },
);
async function drawFrame(direction = 0) {
  if (!input || !canvas.value) return;
  const revision = loadRevision;
  const frame = await exactFrame(input, position.value, direction);
  if (revision !== loadRevision) return;
  position.value = frame.timestamp;
  preciseTimestamp = frame.timestamp;
  const bitmap = await createImageBitmap(frame.blob);
  if (canvas.value) {
    canvas.value.width = frame.width;
    canvas.value.height = frame.height;
    canvas.value.getContext("2d")?.drawImage(bitmap, 0, 0);
  }
  bitmap.close();
}
async function toggle() {
  if (!controlsReady.value) return;
  if (playing.value) {
    pause();
    return;
  }
  if (position.value >= duration.value - 0.01) position.value = 0;
  preciseTimestamp = null;
  await store.guarded(async () => {
    if (!fallback.value && video.value) {
      video.value.currentTime = position.value;
      video.value.volume = volume.value;
      video.value.playbackRate = rate.value;
      try {
        await video.value.play();
        playing.value = true;
        return;
      } catch {
        fallback.value = true;
      }
    }
    if (!input || !canvas.value) return;
    decoded ||= new DecodedPlayer(input, canvas.value);
    playing.value = true;
    void decoded
      .play(
        position.value,
        rate.value,
        volume.value,
        (value) => {
          position.value = Math.min(value, duration.value);
        },
        () => {
          playing.value = false;
        },
      )
      .catch((e) => {
        playing.value = false;
        store.error = String(e);
      });
  });
}
async function seek(value: number, direction = 0) {
  if (!inputReady.value) return;
  pause();
  preciseTimestamp = null;
  position.value = Math.max(0, Math.min(duration.value, value));
  await store.guarded(async () => {
    if (direction || fallback.value) await drawFrame(direction);
    if (video.value) video.value.currentTime = position.value;
  });
}
function changeVolume(value: number) {
  volume.value = value;
  if (video.value) video.value.volume = value;
  decoded?.volume(value);
}
function changeRate(value: number) {
  const resume = playing.value;
  pause();
  rate.value = value;
  if (resume) void toggle();
}
function setZoom(value: number) {
  zoom.value = Math.min(16, Math.max(1, value));
  rangeStart.value = Math.max(
    0,
    Math.min(duration.value - span.value, position.value - span.value / 2),
  );
}
async function capture() {
  const revision = store.draftRevision;
  pause();
  busy.value = true;
  await store.guarded(async () => {
    if (!input || !asset.value) throw new Error("请先选择可解码的视频");
    const sourceId = asset.value.id;
    const frame = await exactFrame(input, preciseTimestamp ?? position.value);
    if (revision !== store.draftRevision || asset.value?.id !== sourceId)
      return;
    if (candidate.value) URL.revokeObjectURL(candidate.value.url);
    candidate.value = {
      url: URL.createObjectURL(frame.blob),
      image: frame.blob,
      timestamp: frame.timestamp,
      source: sourceId,
      width: frame.width,
      height: frame.height,
    };
    position.value = frame.timestamp;
    frameOpen.value = true;
  }, revision);
  busy.value = false;
}
async function saveFrame(purpose: "cover" | "album") {
  const revision = store.draftRevision;
  busy.value = true;
  await store.guarded(async () => {
    const frame = candidate.value;
    if (!frame) return;
    const saved = await api<Asset>("frames", "POST", {
      source_id: frame.source,
      timestamp: frame.timestamp,
      purpose,
      image: await dataUrl(frame.image),
    });
    if (revision !== store.draftRevision) return;
    store.assets[saved.id] = saved;
    if (purpose === "album") {
      store.addAssets([saved], frame.source);
      store.notify("图片已加入相册");
    } else {
      const item = store.draft.items.find(
        (item) => item.media_id === frame.source,
      );
      if (!item) throw new Error("源视频已移除");
      item.cover_id = saved.id;
      store.autosave();
      store.notify("视频封面已设置");
    }
  }, revision);
  busy.value = false;
}
function exportFrame() {
  if (!candidate.value) return;
  const anchor = document.createElement("a");
  anchor.href = candidate.value.url;
  anchor.download = `frame-${candidate.value.timestamp.toFixed(3)}.png`;
  anchor.click();
}
function keyboard(event: KeyboardEvent) {
  if ((event.target as HTMLElement).matches("input,select,textarea,button"))
    return;
  if (event.code === "Space") {
    event.preventDefault();
    void toggle();
  }
  if (event.code === "ArrowLeft" || event.code === "ArrowRight") {
    event.preventDefault();
    void seek(position.value, event.code === "ArrowLeft" ? -1 : 1);
  }
}
onBeforeUnmount(() => {
  ++loadRevision;
  pause();
  void decoded?.dispose();
  input?.dispose();
  if (candidate.value) URL.revokeObjectURL(candidate.value.url);
});
</script>
<template>
  <section
    class="player-panel"
    tabindex="0"
    aria-label="媒体预览"
    @keydown="keyboard"
  >
    <div class="panel-heading">
      <div class="flex items-center gap-2 min-w-0">
        <span class="live-dot" /><span class="truncate">{{
          asset?.name || "媒体预览"
        }}</span>
      </div>
      <span class="font-mono text-[10px] tracking-wider text-muted">{{
        asset ? bytes(asset.size) : "PREVIEW"
      }}</span>
    </div>
    <div ref="surface" class="player-surface">
      <template v-if="asset?.status === 'ready'">
        <img
          v-if="asset.kind === 'image'"
          :src="mediaUrl(asset.id)"
          :alt="asset.name"
          class="preview-media"
        />
        <template v-else-if="playable">
          <video
            v-show="!fallback"
            ref="video"
            :key="asset.id"
            :src="mediaUrl(asset.id)"
            class="preview-media"
            playsinline
            preload="metadata"
            @timeupdate="updateTime"
            @play="playing = true"
            @pause="playing = false"
            @ended="playing = false"
            @error="
              fallback = true;
              store.guarded(drawFrame);
            "
            @click="toggle"
          />
          <canvas
            v-show="fallback"
            ref="canvas"
            class="preview-media"
            @click="toggle"
          />
          <button
            v-if="!playing"
            class="play-overlay"
            aria-label="播放"
            @click="toggle"
          >
            <Play :size="25" fill="currentColor" />
          </button>
          <div class="media-corner">
            {{ asset.metadata.width }} × {{ asset.metadata.height }}
          </div>
        </template>
        <div v-else class="empty-media">
          <Film :size="34" :stroke-width="1" /><span>{{
            store.processing.has(asset.id)
              ? "正在分析媒体…"
              : asset.metadata.error || "等待媒体分析"
          }}</span>
        </div>
      </template>
      <div v-else-if="asset" class="empty-media">
        <span :class="{ spinner: asset.status === 'downloading' }" /><span>{{
          asset.status === "downloading"
            ? "等待下载后预览"
            : asset.error || "素材不可用"
        }}</span
        ><span v-if="asset.status === 'downloading'" class="text-muted text-xs"
          >{{ bytes(asset.downloaded)
          }}{{ asset.total ? " / " + bytes(asset.total) : "" }} ·
          {{ bytes(asset.speed) }}/s</span
        ><UiButton
          v-if="asset.status === 'downloading'"
          @click="
            store.guarded(() => api(`downloads/${asset.id}/cancel`, 'POST'))
          "
          >取消下载</UiButton
        >
      </div>
      <div v-else class="empty-media">
        <div class="empty-film"><Film :size="37" :stroke-width="1" /></div>
        <span class="text-[14px]">暂无素材</span
        ><UiButton variant="ghost" @click="emit('add')"
          ><ImagePlus :size="15" />添加视频</UiButton
        >
      </div>
    </div>
    <div class="player-controls">
      <div class="flex items-center gap-3">
        <button
          class="icon-btn"
          :disabled="!controlsReady"
          :aria-label="playing ? '暂停' : '播放'"
          @click="toggle"
        >
          <Pause v-if="playing" :size="18" /><Play v-else :size="18" /></button
        ><span class="time-code"
          >{{ time(position) }}
          <span class="text-muted">/ {{ time(duration) }}</span></span
        >
      </div>
      <div class="flex items-center gap-2">
        <button
          class="icon-btn"
          :aria-label="volume ? '静音' : '取消静音'"
          @click="changeVolume(volume ? 0 : 0.8)"
        >
          <Volume2 v-if="volume" :size="16" /><VolumeX
            v-else
            :size="16"
          /></button
        ><input
          class="volume-range"
          type="range"
          min="0"
          max="1"
          step=".01"
          :value="volume"
          aria-label="音量"
          @input="
            changeVolume(Number(($event.target as HTMLInputElement).value))
          "
        /><select
          class="speed-select"
          :value="rate"
          aria-label="倍速"
          @change="
            changeRate(Number(($event.target as HTMLSelectElement).value))
          "
        >
          <option v-for="speed in [0.5, 1, 1.5, 2]" :key="speed" :value="speed">
            {{ speed }}×
          </option></select
        ><button
          class="icon-btn"
          aria-label="全屏"
          :disabled="!asset"
          @click="surface?.requestFullscreen()"
        >
          <Expand :size="16" />
        </button>
      </div>
    </div>
    <div
      v-if="
        asset?.kind === 'video' &&
        asset.metadata.video_decodable &&
        !asset.metadata.audio_decodable
      "
      class="audio-warning"
    >
      当前音轨无法预览
    </div>
    <div class="timeline-area">
      <div class="timeline-header">
        <span class="eyebrow">时间轴</span>
        <div class="flex items-center gap-2">
          <button
            class="icon-btn small"
            aria-label="缩小时间轴"
            :disabled="zoom <= 1"
            @click="setZoom(zoom / 2)"
          >
            <ZoomOut :size="14" /></button
          ><span class="font-mono text-[10px] text-muted">{{ zoom }}×</span
          ><button
            class="icon-btn small"
            aria-label="放大时间轴"
            :disabled="!controlsReady || zoom >= 16"
            @click="setZoom(zoom * 2)"
          >
            <ZoomIn :size="14" />
          </button>
        </div>
      </div>
      <div class="timeline-strip" :class="{ 'is-empty': !thumbs.length }">
        <img v-for="id in thumbs" :key="id" :src="mediaUrl(id)" alt="" />
        <div v-if="!thumbs.length" class="timeline-placeholder" />
        <input
          class="timeline-seek"
          type="range"
          :min="rangeStart"
          :max="rangeStart + span || 1"
          step=".001"
          :value="position"
          :disabled="!controlsReady"
          aria-label="视频时间轴"
          @input="seek(Number(($event.target as HTMLInputElement).value))"
        />
        <div
          class="timeline-cursor"
          :style="{
            left: `${Math.max(0, Math.min(100, ((position - rangeStart) / (span || 1)) * 100))}%`,
          }"
        />
      </div>
      <div class="flex justify-between text-[10px] font-mono text-muted mt-2">
        <span v-for="n in 5" :key="n">{{
          time(rangeStart + (span * (n - 1)) / 4)
        }}</span>
      </div>
      <div class="frame-controls">
        <div class="flex items-center gap-2">
          <button
            class="icon-btn"
            aria-label="前一帧"
            :disabled="!controlsReady"
            @click="seek(position, -1)"
          >
            <ChevronLeft :size="17" /></button
          ><input
            class="time-input"
            type="number"
            min="0"
            :max="duration"
            step=".001"
            :value="Number(position.toFixed(3))"
            aria-label="定位时间（秒）"
            @change="seek(Number(($event.target as HTMLInputElement).value))"
          /><button
            class="icon-btn"
            aria-label="后一帧"
            :disabled="!controlsReady"
            @click="seek(position, 1)"
          >
            <ChevronRight :size="17" />
          </button>
        </div>
        <UiButton :disabled="!controlsReady" :busy="busy" @click="capture"
          ><Camera :size="15" />截取图片</UiButton
        >
      </div>
    </div>
    <UiModal :open="frameOpen" title="截取图片" wide @close="frameOpen = false"
      ><template v-if="candidate"
        ><img
          class="candidate-image"
          :src="candidate.url"
          alt="选中的实际视频帧"
        />
        <div class="flex justify-between mt-3 text-xs text-muted">
          <span>{{ candidate.width }} × {{ candidate.height }}</span
          ><span class="font-mono">{{ time(candidate.timestamp, true) }}</span>
        </div></template
      ><template #footer
        ><UiButton @click="exportFrame">导出图片</UiButton
        ><UiButton :busy="busy" @click="saveFrame('cover')"
          >设为视频封面</UiButton
        ><UiButton variant="primary" :busy="busy" @click="saveFrame('album')"
          >添加到相册</UiButton
        ></template
      ></UiModal
    >
  </section>
</template>

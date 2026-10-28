<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  ArrowDownToLine,
  Check,
  ChevronRight,
  CircleHelp,
  CloudUpload,
  FolderOpen,
  History,
  LayoutDashboard,
  ListVideo,
  Link2,
  Plus,
  RotateCcw,
  Send,
  Settings2,
  SlidersHorizontal,
  X,
} from "lucide-vue-next";
import { useWorkspace } from "./stores/workspace";
import { api } from "./lib/api";
import { analyzeAsset, disposeWorkers } from "./media/importer";
import type { Asset } from "./types";
import UiButton from "./components/UiButton.vue";
import UiModal from "./components/UiModal.vue";
import MediaPlayer from "./components/MediaPlayer.vue";
import AlbumRail from "./components/AlbumRail.vue";
import PublishInspector from "./components/PublishInspector.vue";
import TaskList from "./components/TaskList.vue";
import SettingsPage from "./components/SettingsPage.vue";
const store = useWorkspace();
const page = ref("editor"),
  source = ref("local"),
  urlOpen = ref(false),
  url = ref(""),
  headers = ref(""),
  downloading = ref(false);
const resetting = ref(false);
const help = ref(false),
  inspectorOpen = ref(false),
  dragging = ref(false);
const nav = [
  { id: "editor", label: "新建发布", icon: LayoutDashboard },
  { id: "queue", label: "任务队列", icon: ListVideo },
  { id: "history", label: "历史记录", icon: History },
  { id: "settings", label: "设置", icon: Settings2 },
];
const accountLabel = computed(
  () =>
    store.auth.user?.name ||
    (store.auth.state === "offline" ? "连接中断" : "未登录"),
);
watch(page, () => {
  if (store.online) void store.guarded(() => store.save(true));
});
async function register(paths: string[]) {
  if (!paths.length) return;
  const revision = store.draftRevision;
  await store.guarded(async () => {
    const result = await api<{
      assets: Asset[];
      failures: { name: string; message: string }[];
    }>("media/register", "POST", { paths });
    if (revision !== store.draftRevision) return;
    store.addAssets(result.assets);
    if (result.failures.length)
      store.error = result.failures
        .map((f) => `${f.name}：${f.message}`)
        .join("；");
    for (const asset of result.assets) void analyzeAsset(asset, store);
  }, revision);
}
async function chooseFiles() {
  if (!window.desktop) {
    store.error = "请从桌面客户端选择本地文件";
    return;
  }
  await register(await window.desktop.chooseFiles());
}
function dragLeave(event: DragEvent) {
  if (
    !(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node)
  )
    dragging.value = false;
}
async function drop(event: DragEvent) {
  dragging.value = false;
  if (!event.dataTransfer?.files.length) return;
  const paths = window.desktop?.droppedPaths(event.dataTransfer.files) || [];
  await register(paths);
}
async function download() {
  const revision = store.draftRevision;
  downloading.value = true;
  await store.guarded(async () => {
    let extra: Record<string, string> = {};
    if (headers.value.trim()) {
      const parsed: unknown = JSON.parse(headers.value);
      if (
        !parsed ||
        typeof parsed !== "object" ||
        Array.isArray(parsed) ||
        Object.values(parsed).some((v) => typeof v !== "string")
      )
        throw new Error("请求头应为 JSON 字符串键值对象");
      extra = parsed as Record<string, string>;
    }
    const asset = await api<Asset>("downloads", "POST", {
      url: url.value,
      headers: extra,
    });
    if (revision !== store.draftRevision) {
      await api(`downloads/${asset.id}/cancel`, "POST");
      return;
    }
    store.addAssets([asset]);
    url.value = "";
    headers.value = "";
    urlOpen.value = false;
    store.notify("下载已创建");
  }, revision);
  if (revision === store.draftRevision) downloading.value = false;
}
async function resetEditor() {
  if (resetting.value) return;
  resetting.value = true;
  const downloads = store.draft.items
    .map((item) => store.assets[item.media_id])
    .filter((asset) => asset?.status === "downloading");
  disposeWorkers();
  source.value = "local";
  url.value = "";
  headers.value = "";
  urlOpen.value = false;
  downloading.value = false;
  inspectorOpen.value = false;
  dragging.value = false;
  await store.guarded(async () => {
    const [, cancelled] = await Promise.all([
      store.resetDraft(),
      Promise.allSettled(
        downloads.map((asset) => api(`downloads/${asset.id}/cancel`, "POST")),
      ),
    ]);
    store.notify("已重置");
    if (cancelled.some((result) => result.status === "rejected"))
      store.error = "部分下载未能停止，请检查连接";
  });
  resetting.value = false;
}
watch(
  () => store.settings.theme,
  (theme) => {
    document.documentElement.dataset.theme = theme;
  },
  { immediate: true },
);
watch(
  () =>
    Object.values(store.assets)
      .filter(
        (a) =>
          a.kind === "video" &&
          a.status === "ready" &&
          !a.metadata.readable &&
          !a.metadata.error &&
          store.draft.items.some((i) => i.media_id === a.id),
      )
      .map((a) => a.id)
      .join(","),
  () => {
    for (const asset of Object.values(store.assets))
      if (
        asset.kind === "video" &&
        asset.status === "ready" &&
        !asset.metadata.readable &&
        !asset.metadata.error &&
        store.draft.items.some((i) => i.media_id === asset.id)
      )
        void analyzeAsset(asset, store);
  },
);
onMounted(() => {
  void store.boot();
});
onBeforeUnmount(() => {
  store.dispose();
  disposeWorkers();
});
</script>
<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-icon"><Send :size="21" :stroke-width="1.7" /></div>
        <span>Tg Netdisk</span>
      </div>
      <span class="sidebar-label">工作区</span>
      <nav>
        <button
          v-for="item in nav"
          :key="item.id"
          :class="['nav-item', { active: page === item.id }]"
          @click="page = item.id"
        >
          <component :is="item.icon" :size="18" :stroke-width="1.6" /><span>{{
            item.label
          }}</span
          ><span
            v-if="item.id === 'queue' && store.active.length"
            class="nav-count"
            >{{ store.active.length }}</span
          >
        </button>
      </nav>
      <div class="sidebar-bottom">
        <button class="nav-item" @click="help = true">
          <CircleHelp :size="17" :stroke-width="1.5" /><span>帮助</span></button
        ><button
          class="account-button"
          :class="{ active: page === 'account' }"
          @click="page = 'account'"
        >
          <div class="avatar">
            {{ store.auth.user?.name.slice(0, 1) || "T" }}
          </div>
          <div class="account-text">
            <strong>{{ accountLabel }}</strong
            ><span
              ><i
                :class="{ 'is-online': store.auth.state === 'authorized' }"
              />{{
                store.auth.state === "authorized" ? "已连接" : "账号与连接"
              }}</span
            >
          </div>
          <ChevronRight :size="13" class="text-muted" />
        </button>
        <div class="version-row">
          <span>v0.1.5</span
          ><span class="connection-status" :class="{ connected: store.online }"
            ><i />{{ store.online ? "本地服务已连接" : "未连接" }}</span
          >
        </div>
      </div>
    </aside>
    <main class="main-shell">
      <header class="topbar">
        <div class="breadcrumb">
          <span>Tg Netdisk</span><ChevronRight :size="12" /><strong>{{
            page === "editor"
              ? "新建发布"
              : page === "account"
                ? "账号与连接"
                : nav.find((i) => i.id === page)?.label
          }}</strong>
        </div>
        <div class="flex items-center gap-4">
          <span v-if="store.savedAt && page === 'editor'" class="saved-status"
            ><Check :size="12" />已保存 {{ store.savedAt }}</span
          ><button
            v-if="page === 'editor'"
            class="icon-btn configure-button"
            aria-label="打开发布设置"
            @click="inspectorOpen = !inspectorOpen"
          >
            <SlidersHorizontal :size="18" /></button
          ><span class="topbar-status"
            ><i />{{
              store.active.length ? `${store.active.length} 个任务` : "就绪"
            }}</span
          >
        </div>
      </header>
      <div
        v-if="page === 'editor'"
        class="editor-layout"
        :class="{ 'inspector-open': inspectorOpen }"
      >
        <section
          class="workspace"
          @dragover.prevent="dragging = true"
          @dragleave="dragLeave"
          @drop.prevent="drop"
        >
          <div class="workspace-title">
            <div>
              <span class="eyebrow">NEW POST</span>
              <h1>新建发布</h1>
            </div>
            <div class="source-switch">
              <button
                :class="{ active: source === 'local' }"
                @click="source = 'local'"
              >
                <FolderOpen :size="14" />本地文件</button
              ><button
                :class="{ active: source === 'url' }"
                @click="
                  source = 'url';
                  urlOpen = true;
                "
              >
                <Link2 :size="14" />视频直链
              </button>
            </div>
            <UiButton
              variant="ghost"
              :busy="resetting"
              :disabled="!store.online || store.loading"
              @click="resetEditor"
              ><RotateCcw :size="14" />重置</UiButton
            >
            <UiButton
              class="add-media-button"
              :disabled="!store.online"
              @click="source === 'url' ? (urlOpen = true) : chooseFiles()"
              ><Plus :size="15" />添加素材</UiButton
            >
          </div>
          <MediaPlayer
            :key="store.draftRevision"
            @add="chooseFiles"
          /><AlbumRail @add="chooseFiles" />
          <div v-if="dragging" class="drop-overlay">
            <CloudUpload :size="35" :stroke-width="1.2" /><span>添加素材</span>
          </div>
          <div class="workspace-bottom">
            <span
              ><span class="text-accent">{{
                store.draft.items.filter(
                  (i) => store.assets[i.media_id]?.kind === "video",
                ).length
              }}</span>
              视频 <span class="divider-dot">·</span>
              {{
                store.draft.items.filter(
                  (i) => store.assets[i.media_id]?.kind === "image",
                ).length
              }}
              图片</span
            ><span class="font-mono">{{
              store.loading
                ? "加载中…"
                : store.processing.size
                  ? "媒体分析中"
                  : ""
            }}</span>
          </div>
        </section>
        <button
          v-if="inspectorOpen"
          class="inspector-backdrop"
          aria-label="关闭发布设置"
          @click="inspectorOpen = false"
        /><PublishInspector :key="store.draftRevision" />
      </div>
      <TaskList
        v-else-if="page === 'queue' || page === 'history'"
        :key="page"
        :history="page === 'history'"
        @edit="page = 'editor'"
      />
      <SettingsPage v-else :key="page" :account="page === 'account'" />
    </main>
    <Transition name="toast"
      ><div v-if="store.error" class="toast toast-error" role="alert">
        <span>{{ store.error }}</span
        ><button
          class="icon-btn"
          aria-label="关闭提示"
          @click="store.error = ''"
        >
          <X :size="14" />
        </button></div></Transition
    ><Transition name="toast"
      ><div v-if="store.notice" class="toast toast-success" role="status">
        <Check :size="15" /><span>{{ store.notice }}</span>
      </div></Transition
    >
    <UiModal :open="urlOpen" title="添加视频直链" @close="urlOpen = false"
      ><form class="space-y-5" @submit.prevent="download">
        <label class="field-label block"
          >视频 URL<input
            v-model="url"
            class="field mt-3"
            type="url"
            placeholder="https://example.com/video.mp4"
            required
            autocomplete="off"
        /></label>
        <details class="advanced">
          <summary>高级选项</summary>
          <label class="field-label block mt-4"
            >请求头（JSON）<textarea
              v-model="headers"
              class="field mt-3 font-mono"
              rows="3"
              placeholder='{"Authorization":"Bearer …"}'
              style="-webkit-text-security: disc"
              spellcheck="false"
            />
          </label>
        </details>
      </form>
      <template #footer
        ><UiButton @click="urlOpen = false">取消</UiButton
        ><UiButton
          variant="primary"
          :busy="downloading"
          :disabled="!url.trim()"
          @click="download"
          ><ArrowDownToLine :size="15" />开始下载</UiButton
        ></template
      ></UiModal
    >
    <UiModal :open="help" title="帮助" @close="help = false"
      ><div class="help-content">
        <p>
          在“账号与连接”保存 API ID / Hash 后扫码登录。API 凭据可从
          my.telegram.org 获取；两步验证密码仅在登录时使用。
        </p>
        <p>
          相册限 2–10 项且至少包含一个视频；单项按单视频发送。相册布局由
          Telegram 决定，预览只表示内容和顺序。
        </p>
        <p>
          封面使用独立 video_cover 与缩略图适配，显示效果需要在真实 Telegram
          客户端核对。
        </p>
        <p>
          结果待确认时先查看频道，再记录消息 ID
          或确认未发布。无法确定时请保留待确认状态。
        </p>
        <p>播放器：空格播放 / 暂停，左右键逐帧。完整说明见项目 README。</p>
      </div></UiModal
    >
  </div>
</template>

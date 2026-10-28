import { computed, reactive, ref } from "vue";
import { defineStore } from "pinia";
import { api, initialize, subscribe } from "../lib/api";
import { activeStates, tag } from "../lib/format";
import type {
  Asset,
  Auth,
  Draft,
  Settings,
  Snapshot,
  PublishTask,
  Channel,
} from "../types";

function emptyDraft(channelId = ""): Draft {
  return {
    id: "current",
    title: "",
    description: "",
    tags: [],
    bold_title: true,
    channel_id: channelId,
    items: [],
  };
}

export const useWorkspace = defineStore("workspace", () => {
  const draft = reactive<Draft>(emptyDraft());
  const draftRevision = ref(0);
  const assets = ref<Record<string, Asset>>({}),
    tasks = ref<PublishTask[]>([]),
    channels = ref<Channel[]>([]);
  const auth = ref<Auth>({
    state: "unconfigured",
    user: null,
    caption_limit: 1024,
  });
  const settings = ref<Settings>({
    api_id: "",
    has_api_hash: false,
    has_telegram_proxy: false,
    has_download_proxy: false,
    default_channel: "",
    theme: "dark",
    close_behavior: "ask",
    download_dir: "",
    upload_concurrency: 4,
    data_dir: "",
  });
  const selectedId = ref(""),
    online = ref(false),
    loading = ref(true),
    notice = ref(""),
    error = ref("");
  const saving = ref(false),
    savedAt = ref(""),
    processing = ref<Set<string>>(new Set());
  const current = computed(() => assets.value[selectedId.value]);
  const active = computed(() =>
    tasks.value.filter((t) => activeStates.includes(t.state)),
  );
  let saveTimer: ReturnType<typeof setTimeout>,
    refreshTimer: ReturnType<typeof setTimeout>;
  let stopEvents: (() => void) | undefined;
  let stopFlush: (() => void) | undefined,
    stopBackend: (() => void) | undefined;
  let saveChain: Promise<unknown> = Promise.resolve();
  function notify(message: string) {
    notice.value = message;
    setTimeout(() => {
      if (notice.value === message) notice.value = "";
    }, 3500);
  }
  async function guarded<T>(
    operation: () => Promise<T>,
    revision?: number,
  ): Promise<T | undefined> {
    error.value = "";
    try {
      return await operation();
    } catch (e) {
      if (revision === undefined || revision === draftRevision.value)
        error.value = e instanceof Error ? e.message : "操作失败";
    }
  }
  async function refresh() {
    const snapshot = await api<Snapshot>("snapshot");
    assets.value = Object.fromEntries(
      snapshot.media.map((asset) => [asset.id, asset]),
    );
    tasks.value = snapshot.tasks;
    channels.value = snapshot.channels;
    auth.value = snapshot.auth;
    settings.value = snapshot.settings;
  }
  async function boot() {
    await guarded(async () => {
      await initialize();
      stopFlush = window.desktop?.onFlushDraft(async () => {
        if (loading.value) throw new Error("正在加载草稿");
        await save(true);
      });
      stopBackend = window.desktop?.onBackendStatus((status) => {
        if (!status.ready) {
          online.value = false;
          error.value = "本地服务已停止，请重新启动应用";
        }
      });
      const snapshot = await api<Snapshot>("snapshot");
      Object.assign(draft, snapshot.draft);
      if (!draft.channel_id)
        draft.channel_id = snapshot.settings.default_channel;
      await refresh();
      selectedId.value = draft.items[0]?.media_id || "";
      online.value = true;
      stopEvents = subscribe(
        () => {
          clearTimeout(refreshTimer);
          refreshTimer = setTimeout(() => {
            void guarded(refresh);
          }, 150);
        },
        (state) => {
          online.value = state;
        },
      );
    });
    loading.value = false;
  }
  async function save(silent = false) {
    clearTimeout(saveTimer);
    saving.value = true;
    const payload: Draft = JSON.parse(JSON.stringify(draft));
    const operation = saveChain
      .catch(() => {})
      .then(() => api("drafts/current", "PUT", payload));
    saveChain = operation;
    try {
      await operation;
      savedAt.value = new Date().toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
      });
      if (!silent) notify("草稿已保存");
    } finally {
      saving.value = operation !== saveChain;
    }
  }
  function autosave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      void guarded(() => save(true));
    }, 600);
  }
  async function resetDraft() {
    clearTimeout(saveTimer);
    draftRevision.value++;
    Object.assign(draft, emptyDraft(settings.value.default_channel));
    selectedId.value = "";
    processing.value.clear();
    error.value = "";
    notice.value = "";
    await save(true);
  }
  function select(id: string) {
    selectedId.value = id;
  }
  function remove(index: number) {
    const [item] = draft.items.splice(index, 1);
    if (item.media_id === selectedId.value)
      selectedId.value =
        draft.items[Math.min(index, draft.items.length - 1)]?.media_id || "";
    autosave();
  }
  function move(index: number, direction: number) {
    const target = index + direction;
    if (target < 0 || target >= draft.items.length) return;
    const [item] = draft.items.splice(index, 1);
    draft.items.splice(target, 0, item);
    autosave();
  }
  function addAssets(values: Asset[], afterId?: string) {
    let position = afterId
      ? draft.items.findIndex((i) => i.media_id === afterId) + 1
      : draft.items.length;
    for (const asset of values) {
      assets.value[asset.id] = asset;
      draft.items.splice(position++, 0, { media_id: asset.id, cover_id: null });
    }
    if (values.length) select(values[0].id);
    autosave();
  }
  function addTag(value: string) {
    const normalized = tag(value);
    if (!draft.tags.some((t) => t.toLowerCase() === normalized.toLowerCase())) {
      draft.tags.push(normalized);
      autosave();
    }
  }
  async function enqueue() {
    await save(true);
    await api<PublishTask>("tasks", "POST", JSON.parse(JSON.stringify(draft)));
    await refresh();
    notify("任务已加入队列");
  }
  async function copyTask(task: PublishTask) {
    Object.assign(draft, structuredClone(task.snapshot.draft));
    selectedId.value = draft.items[0]?.media_id || "";
    await save(true);
    notify("已复制为草稿");
  }
  function dispose() {
    stopEvents?.();
    stopFlush?.();
    stopBackend?.();
    clearTimeout(saveTimer);
    clearTimeout(refreshTimer);
  }
  return {
    draft,
    draftRevision,
    assets,
    tasks,
    channels,
    auth,
    settings,
    selectedId,
    online,
    loading,
    notice,
    error,
    current,
    active,
    saving,
    savedAt,
    processing,
    boot,
    refresh,
    guarded,
    notify,
    save,
    autosave,
    resetDraft,
    select,
    remove,
    move,
    addAssets,
    addTag,
    enqueue,
    copyTask,
    dispose,
  };
});

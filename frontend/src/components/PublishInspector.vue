<script setup lang="ts">
import { computed, ref } from "vue";
import { ArrowUpRight, Check, Hash, ImagePlus, Send, X } from "lucide-vue-next";
import { useWorkspace } from "../stores/workspace";
import { api, mediaUrl, webMode } from "../lib/api";
import { caption } from "../lib/format";
import type { Asset, Channel } from "../types";
import UiButton from "./UiButton.vue";
import UiModal from "./UiModal.vue";
import ServerFilePicker from "./ServerFilePicker.vue";
const store = useWorkspace();
const serverCover = ref(false),
  coverTargetId = ref("");
function serverCoverSelected(assets: Asset[]) {
  const cover = assets[0];
  const target = store.draft.items.find(
    (item) => item.media_id === coverTargetId.value,
  );
  if (cover?.kind === "image" && target) {
    store.assets[cover.id] = cover;
    target.cover_id = cover.id;
    store.autosave();
  }
}
const tagInput = ref(""),
  manualChannel = ref(false),
  busy = ref(false),
  preview = ref(false);
const text = computed(() =>
  caption(store.draft.title, store.draft.description, store.draft.tags),
);
const selectedItem = computed(() =>
  store.draft.items.find((item) => item.media_id === store.selectedId),
);
const coverId = computed(() => selectedItem.value?.cover_id);
const invalid = computed(() => {
  if (!store.online) return "本地服务未连接";
  if (store.auth.state !== "authorized") return "请先登录 Telegram";
  if (!store.draft.channel_id) return "请选择频道";
  if (!store.draft.items.length) return "请添加视频";
  if (store.draft.items.length > 10) return "超过 10 项，请拆分";
  if (text.value.length > store.auth.caption_limit) return "文案超过上限";
  if (
    !store.draft.items.some(
      (item) => store.assets[item.media_id]?.kind === "video",
    )
  )
    return "至少添加一个视频";
  if (
    store.draft.items.some((item) => {
      const asset = store.assets[item.media_id];
      return (
        !asset ||
        asset.status !== "ready" ||
        store.processing.has(asset.id) ||
        (asset.kind === "video" && !asset.metadata.video_decodable)
      );
    })
  )
    return "存在未就绪或不支持的素材";
  return "";
});
function addTag() {
  if (!tagInput.value.trim()) return;
  try {
    store.addTag(tagInput.value);
    tagInput.value = "";
  } catch (e) {
    store.error = String((e as Error).message);
  }
}
async function refreshChannels() {
  await store.guarded(async () => {
    store.channels = await api<Channel[]>("channels/refresh", "POST");
  });
}
async function resolveChannel() {
  const revision = store.draftRevision;
  await store.guarded(async () => {
    const value = await api<Channel>("channels/resolve", "POST", {
      channel_id: store.draft.channel_id,
    });
    await store.refresh();
    if (revision !== store.draftRevision) return;
    store.draft.channel_id = value.id;
    store.autosave();
    store.notify("频道已校验");
  }, revision);
}
async function chooseCover() {
  if (webMode()) {
    coverTargetId.value = selectedItem.value?.media_id || "";
    serverCover.value = true;
    return;
  }
  const revision = store.draftRevision;
  const targetId = selectedItem.value?.media_id;
  await store.guarded(async () => {
    const paths = await window.desktop?.chooseFiles();
    if (!paths?.length) return;
    const { assets, failures } = await api<{
      assets: Asset[];
      failures: { message: string }[];
    }>("media/register", "POST", { paths: [paths[0]] });
    if (revision !== store.draftRevision) return;
    const cover = assets[0];
    if (!cover || cover.kind !== "image")
      throw new Error(failures[0]?.message || "请选择图片作为封面");
    store.assets[cover.id] = cover;
    const target = store.draft.items.find((item) => item.media_id === targetId);
    if (target) {
      target.cover_id = cover.id;
      store.autosave();
    }
  }, revision);
}
async function enqueue() {
  busy.value = true;
  await store.guarded(async () => {
    await store.enqueue();
    preview.value = false;
  });
  busy.value = false;
}
</script>
<template>
  <aside class="inspector">
    <ServerFilePicker
      :open="serverCover"
      images-only
      single
      @close="serverCover = false"
      @selected="serverCoverSelected"
    />
    <div class="inspector-heading">
      <h2>发布设置</h2>
      <span class="eyebrow">{{
        store.draft.items.length > 1 ? "相册" : "单视频"
      }}</span>
    </div>
    <div class="inspector-scroll">
      <section class="form-section">
        <div class="flex justify-between items-center mb-3">
          <label class="field-label" for="channel"
            >目标频道 <span class="text-accent">*</span></label
          ><button class="text-button muted" @click="refreshChannels">
            刷新
          </button>
        </div>
        <select
          v-if="!manualChannel"
          id="channel"
          v-model="store.draft.channel_id"
          class="field"
          @change="store.autosave()"
        >
          <option value="">选择频道</option>
          <option
            v-for="channel in store.channels"
            :key="channel.id"
            :value="channel.id"
            :disabled="!channel.can_post"
          >
            {{ channel.name }}{{ channel.can_post ? "" : " · 无发帖权限" }}
          </option></select
        ><input
          v-else
          id="channel"
          v-model="store.draft.channel_id"
          class="field font-mono"
          placeholder="-100…"
          @input="store.autosave()"
        />
        <div class="flex justify-between mt-2">
          <button
            class="text-button muted"
            @click="manualChannel = !manualChannel"
          >
            {{ manualChannel ? "从列表选择" : "填写频道 ID" }}</button
          ><button
            class="text-button muted"
            :disabled="!store.draft.channel_id"
            @click="resolveChannel"
          >
            <Check :size="11" />校验
          </button>
        </div>
      </section>
      <section class="form-section space-y-5">
        <div>
          <label for="title" class="field-label mb-3 block">标题</label
          ><input
            id="title"
            v-model="store.draft.title"
            class="field"
            placeholder="添加标题"
            @input="store.autosave()"
          /><label class="check-label mt-2"
            ><input
              v-model="store.draft.bold_title"
              type="checkbox"
              @change="store.autosave()"
            />标题加粗</label
          >
        </div>
        <div>
          <label for="description" class="field-label mb-3 block">简介</label
          ><textarea
            id="description"
            v-model="store.draft.description"
            class="field resize-y"
            rows="4"
            placeholder="添加简介"
            @input="store.autosave()"
          />
        </div>
        <div>
          <label for="tag-input" class="field-label mb-3 block">话题标签</label>
          <div class="tag-field">
            <span
              v-for="(tag, index) in store.draft.tags"
              :key="tag"
              class="tag-chip"
              >{{ tag
              }}<button
                :aria-label="`删除标签 ${tag}`"
                @click="
                  store.draft.tags.splice(index, 1);
                  store.autosave();
                "
              >
                <X :size="11" /></button
            ></span>
            <div class="flex items-center gap-1 min-w-0">
              <Hash :size="13" class="text-muted" /><input
                id="tag-input"
                v-model="tagInput"
                placeholder="4k"
                class="tag-input"
                @keydown.enter.prevent="addTag"
                @blur="addTag"
              />
            </div>
          </div>
          <div class="mt-2 flex flex-wrap gap-2">
            <button
              v-for="old in [
                ...new Set(store.tasks.flatMap((t) => t.snapshot.draft.tags)),
              ]
                .filter((t) => !store.draft.tags.includes(t))
                .slice(0, 5)"
              :key="old"
              class="text-button muted"
              @click="store.addTag(old)"
            >
              {{ old }}
            </button>
          </div>
        </div>
      </section>
      <section class="form-section">
        <div class="flex justify-between mb-3">
          <span class="field-label">视频封面</span
          ><button
            v-if="coverId"
            class="text-button muted"
            @click="
              selectedItem!.cover_id = null;
              store.autosave();
            "
          >
            移除
          </button>
        </div>
        <button
          class="cover-picker"
          :disabled="store.current?.kind !== 'video'"
          @click="chooseCover"
        >
          <img
            v-if="coverId"
            :src="mediaUrl(coverId)"
            alt="视频封面"
          /><template v-else
            ><ImagePlus :size="19" :stroke-width="1.2" /><span
              >选择图片</span
            ></template
          >
        </button>
      </section>
      <section class="form-section preview-section">
        <div class="flex justify-between mb-4">
          <span class="field-label">预览</span
          ><button
            class="text-button muted"
            aria-label="展开预览"
            @click="preview = true"
          >
            <ArrowUpRight :size="14" />
          </button>
        </div>
        <div class="message-preview">
          <div class="message-channel">
            {{
              store.channels.find((c) => c.id === store.draft.channel_id)
                ?.name || "目标频道"
            }}
          </div>
          <div v-if="store.draft.items.length" class="message-media">
            <div
              v-for="(item, index) in store.draft.items.slice(0, 4)"
              :key="item.media_id"
            >
              <img
                v-if="
                  item.cover_id ||
                  store.assets[item.media_id]?.kind === 'image' ||
                  store.assets[item.media_id]?.metadata.thumbnails?.[0]
                "
                :src="
                  mediaUrl(
                    item.cover_id ||
                      (store.assets[item.media_id]?.kind === 'image'
                        ? item.media_id
                        : store.assets[item.media_id]?.metadata
                            .thumbnails?.[0]) ||
                      '',
                  )
                "
                alt=""
              /><span>{{ String(index + 1).padStart(2, "0") }}</span>
            </div>
          </div>
          <strong
            v-if="store.draft.title"
            :class="{ 'font-normal': !store.draft.bold_title }"
            >{{ store.draft.title }}</strong
          >
          <p v-if="store.draft.description" class="whitespace-pre-wrap mt-2">
            {{ store.draft.description }}
          </p>
          <p v-if="store.draft.tags.length" class="text-accent mt-2">
            {{ store.draft.tags.join(" ") }}
          </p>
          <span v-if="!text && !store.draft.items.length" class="text-muted"
            >暂无内容</span
          >
        </div>
        <div class="flex justify-between mt-3 text-[10px] text-muted">
          <span>{{ store.draft.items.length }} 项媒体</span
          ><span
            :class="{ 'text-danger': text.length > store.auth.caption_limit }"
            >{{ text.length }} / {{ store.auth.caption_limit }}</span
          >
        </div>
      </section>
    </div>
    <footer class="publish-footer">
      <span v-if="invalid" class="publish-hint">{{ invalid }}</span
      ><span v-else class="publish-hint text-accent">可加入队列</span>
      <div class="flex gap-2">
        <UiButton
          :busy="store.saving"
          :disabled="!store.online"
          @click="store.guarded(() => store.save())"
          >保存草稿</UiButton
        ><UiButton
          variant="primary"
          class="flex-1"
          :disabled="!!invalid"
          @click="preview = true"
          ><Send :size="14" />加入队列</UiButton
        >
      </div>
    </footer>
    <UiModal :open="preview" title="确认发布" @close="preview = false"
      ><div class="space-y-4">
        <p class="text-sm">
          {{
            store.channels.find((c) => c.id === store.draft.channel_id)?.name ||
            store.draft.channel_id ||
            "未选择频道"
          }}
        </p>
        <ol class="space-y-2">
          <li
            v-for="(item, index) in store.draft.items"
            :key="item.media_id"
            class="flex gap-3 text-xs"
          >
            <span class="text-accent font-mono">{{ index + 1 }}</span
            ><span class="truncate">{{
              store.assets[item.media_id]?.name
            }}</span
            ><span class="ml-auto text-muted">{{
              store.assets[item.media_id]?.kind === "video" ? "视频" : "图片"
            }}</span>
          </li>
        </ol>
        <pre class="caption-review">{{ text || "无文案" }}</pre>
        <p v-if="invalid" class="field-error">{{ invalid }}</p>
      </div>
      <template #footer
        ><UiButton @click="preview = false">返回编辑</UiButton
        ><UiButton
          variant="primary"
          :busy="busy"
          :disabled="!!invalid"
          @click="enqueue"
          >确认加入队列</UiButton
        ></template
      ></UiModal
    >
  </aside>
</template>

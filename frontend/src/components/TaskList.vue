<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Copy,
  RotateCcw,
  X,
  AlertTriangle,
  ListVideo,
  Trash2,
} from "lucide-vue-next";
import { useWorkspace } from "../stores/workspace";
import { api, mediaUrl } from "../lib/api";
import {
  activeStates,
  bytes,
  remainingTime,
  states,
  transferSpeed,
} from "../lib/format";
import type { PublishTask } from "../types";
import UiButton from "./UiButton.vue";
import UiModal from "./UiModal.vue";
const props = defineProps<{ history: boolean }>();
const emit = defineEmits<{ edit: [] }>();
const store = useWorkspace();
const clock = ref(Date.now());
const timer = setInterval(() => {
  clock.value = Date.now();
}, 1000);
onBeforeUnmount(() => clearInterval(timer));
const deleteTarget = ref<PublishTask | null>(null),
  deleting = ref(false);
const filter = ref("all"),
  detail = ref<PublishTask | null>(null),
  confirmOpen = ref(false);
const outcome = ref("succeeded"),
  ids = ref(""),
  checked = ref(false),
  busy = ref(false);
const visible = computed(() =>
  store.tasks
    .filter((t) =>
      props.history
        ? !activeStates.includes(t.state)
        : activeStates.includes(t.state),
    )
    .filter((t) => filter.value === "all" || t.state === filter.value),
);
async function action(task: PublishTask, command: string) {
  await store.guarded(async () => {
    await api(`tasks/${task.id}/${command}`, "POST");
    await store.refresh();
  });
}
watch(
  () => store.tasks,
  (tasks) => {
    if (detail.value)
      detail.value = tasks.find((task) => task.id === detail.value?.id) || null;
    if (deleteTarget.value) {
      const current = tasks.find((task) => task.id === deleteTarget.value?.id);
      deleteTarget.value =
        current && !activeStates.includes(current.state) ? current : null;
    }
  },
);
async function deleteRecord() {
  const task = deleteTarget.value;
  if (!task || deleting.value) return;
  deleting.value = true;
  await store.guarded(async () => {
    await api(
      `tasks/${task.id}${task.state === "unknown" ? "?confirm_unknown=true" : ""}`,
      "DELETE",
    );
    if (detail.value?.id === task.id) detail.value = null;
    deleteTarget.value = null;
    await store.refresh();
    store.notify("历史记录已删除");
  });
  deleting.value = false;
}
async function copyDraft(task: PublishTask) {
  await store.guarded(async () => {
    await store.copyTask(task);
    emit("edit");
    detail.value = null;
  });
}
function openConfirm(task: PublishTask) {
  detail.value = task;
  ids.value = "";
  checked.value = false;
  outcome.value = "succeeded";
  confirmOpen.value = true;
}
async function confirm() {
  busy.value = true;
  await store.guarded(async () => {
    if (!detail.value) return;
    const messages = ids.value
      .split(/[,，\s]+/)
      .filter(Boolean)
      .map(Number);
    if (messages.some((n) => !Number.isSafeInteger(n) || n <= 0))
      throw new Error("消息 ID 必须为正整数");
    await api(`tasks/${detail.value.id}/confirm`, "POST", {
      outcome: outcome.value,
      confirmed: checked.value,
      message_ids: messages,
    });
    await store.refresh();
    confirmOpen.value = false;
    detail.value = null;
    store.notify("核对结果已保存");
  });
  busy.value = false;
}
function progress(task: PublishTask) {
  return task.state === "succeeded"
    ? 100
    : Math.min(100, (task.progress.sent / (task.progress.total || 1)) * 100);
}
function thumb(task: PublishTask) {
  const item = task.snapshot.items[0];
  return (
    item?.cover_id ||
    (item?.asset.kind === "image"
      ? item.media_id
      : item?.asset.metadata.thumbnails?.[0])
  );
}
async function copyMessages(task: PublishTask) {
  await store.guarded(async () => {
    await navigator.clipboard.writeText(JSON.stringify(task.messages, null, 2));
    store.notify("消息信息已复制");
  });
}
</script>
<template>
  <div class="page-content">
    <div class="page-title-row">
      <div>
        <span class="eyebrow">{{ history ? "HISTORY" : "QUEUE" }}</span>
        <h1>
          {{ history ? "历史记录" : "任务队列"
          }}<span class="title-count">{{ visible.length }}</span>
        </h1>
      </div>
      <button class="text-button" @click="store.guarded(store.refresh)">
        刷新
      </button>
    </div>
    <div v-if="history" class="filter-tabs">
      <button
        v-for="option in [
          { value: 'all', label: '全部' },
          { value: 'succeeded', label: '已发布' },
          { value: 'failed', label: '失败' },
          { value: 'unknown', label: '待确认' },
          { value: 'cancelled', label: '已取消' },
        ]"
        :key="option.value"
        :class="{ active: filter === option.value }"
        @click="filter = option.value"
      >
        {{ option.label }}
      </button>
    </div>
    <div v-if="!visible.length" class="page-empty">
      <ListVideo :size="38" :stroke-width="1" /><span>{{
        history ? "暂无记录" : "暂无任务"
      }}</span
      ><UiButton @click="emit('edit')">新建发布</UiButton>
    </div>
    <div v-else class="task-list">
      <article v-for="task in visible" :key="task.id" class="task-card">
        <div class="task-thumbnail">
          <img
            v-if="thumb(task)"
            :src="mediaUrl(thumb(task)!)"
            alt=""
          /><ListVideo v-else :size="24" :stroke-width="1" />
        </div>
        <div class="task-main">
          <div class="flex justify-between items-start gap-3">
            <div class="min-w-0">
              <h3 class="truncate">
                {{
                  task.snapshot.draft.title ||
                  task.snapshot.items[0]?.asset.name ||
                  "发布任务"
                }}
              </h3>
              <p class="task-subtitle">
                {{ task.snapshot.channel.name }}<span>·</span
                >{{ task.snapshot.items.length }} 项<span>·</span
                >{{ new Date(task.created_at).toLocaleString("zh-CN") }}
              </p>
            </div>
            <span class="status-pill" :class="task.state"
              ><CheckCircle2
                v-if="task.state === 'succeeded'"
                :size="12"
              /><AlertTriangle
                v-else-if="task.state === 'unknown'"
                :size="12"
              /><Clock3 v-else :size="12" />{{ states[task.state] }}</span
            >
          </div>
          <template v-if="activeStates.includes(task.state)"
            ><div class="progress-track">
              <div
                :style="{ width: `${progress(task)}%` }"
                :class="{ indeterminate: task.state === 'publishing' }"
              />
            </div>
            <div class="task-transfer">
              <span
                >{{ bytes(task.progress.sent) }} /
                {{ bytes(task.progress.total) }}</span
              ><span>{{
                task.state === "publishing"
                  ? "等待发布结果"
                  : task.state === "waiting_retry"
                    ? `${task.retry_in || 0} 秒后重试`
                    : transferSpeed(task, clock)
              }}</span>
            </div></template
          >
          <div v-if="activeStates.includes(task.state)" class="task-eta">
            <Clock3 :size="12" /><span
              >剩余时间：{{ remainingTime(task, clock) }}</span
            >
          </div>
          <p v-if="task.error" class="task-error">{{ task.error }}</p>
          <div class="task-actions">
            <button class="text-button muted" @click="detail = task">
              <ArrowUpRight :size="13" />详情</button
            ><button
              v-if="activeStates.includes(task.state)"
              class="text-button muted"
              @click="action(task, 'cancel')"
            >
              <X :size="13" />取消</button
            ><button
              v-if="['failed', 'cancelled'].includes(task.state)"
              class="text-button"
              @click="action(task, 'retry')"
            >
              <RotateCcw :size="13" />重试</button
            ><button
              v-if="task.state === 'unknown'"
              class="text-button warning"
              @click="openConfirm(task)"
            >
              核对结果</button
            ><button
              v-if="history"
              class="text-button muted"
              @click="copyDraft(task)"
            >
              <Copy :size="13" />复制为草稿
            </button>
            <button
              v-if="history"
              class="text-button text-danger"
              @click="deleteTarget = task"
            >
              <Trash2 :size="13" />删除
            </button>
          </div>
        </div>
      </article>
    </div>
    <UiModal
      :open="!!detail && !confirmOpen && !deleteTarget"
      title="任务详情"
      wide
      @close="detail = null"
      ><template v-if="detail"
        ><dl class="detail-grid">
          <dt>状态</dt>
          <dd>{{ states[detail.state] }}</dd>
          <dt>频道</dt>
          <dd>
            {{ detail.snapshot.channel.name }}
            <span class="text-muted">{{ detail.snapshot.channel.id }}</span>
          </dd>
          <dt>操作标识</dt>
          <dd class="font-mono text-xs break-all">{{ detail.id }}</dd>
          <dt>创建时间</dt>
          <dd>{{ new Date(detail.created_at).toLocaleString("zh-CN") }}</dd>
        </dl>
        <div class="mt-5 space-y-2">
          <div
            v-for="(item, index) in detail.snapshot.items"
            :key="item.media_id"
            class="detail-item"
          >
            <span class="text-accent font-mono">{{ index + 1 }}</span>
            <div class="min-w-0">
              <div class="truncate">{{ item.asset.name }}</div>
              <span class="text-muted text-[10px] font-mono"
                >random_id: {{ item.random_id }}</span
              >
            </div>
            <span class="ml-auto font-mono text-xs">{{
              detail.messages[index]?.message_id || "—"
            }}</span>
          </div>
        </div>
        <pre class="caption-review mt-5">{{
          detail.snapshot.caption || "无文案"
        }}</pre>
        <p v-if="detail.error" class="field-error mt-4">{{ detail.error }}</p>
        <div v-if="detail.messages.length" class="mt-4 text-xs text-muted">
          grouped_id：{{ detail.messages[0]?.grouped_id || "—" }}
        </div></template
      ><template #footer
        ><UiButton
          v-if="history && detail"
          variant="danger"
          @click="deleteTarget = detail"
          >删除记录</UiButton
        ><UiButton v-if="detail?.messages.length" @click="copyMessages(detail)"
          >复制消息信息</UiButton
        ><UiButton
          v-if="detail?.state === 'unknown'"
          @click="openConfirm(detail)"
          >核对结果</UiButton
        ><UiButton v-if="detail" variant="primary" @click="copyDraft(detail)"
          >复制为草稿</UiButton
        ></template
      ></UiModal
    >
    <UiModal
      :open="confirmOpen"
      title="核对发布结果"
      @close="confirmOpen = false"
      ><div class="space-y-5">
        <p class="warning-box">
          请查看目标频道。未核对前不要重新发布，避免重复消息。
        </p>
        <UiButton @click="detail && action(detail, 'reconcile')"
          >查询关联结果</UiButton
        ><label class="field-label block"
          >核对结果<select v-model="outcome" class="field mt-2">
            <option value="succeeded">确认已发布</option>
            <option value="failed">确认未发布</option>
          </select></label
        ><label v-if="outcome === 'succeeded'" class="field-label block"
          >消息 ID（按素材顺序）<input
            v-model="ids"
            class="field mt-2 font-mono"
            placeholder="101, 102, 103" /></label
        ><label class="check-label"
          ><input
            v-model="checked"
            type="checkbox"
          />我已在频道中核对全部素材</label
        >
      </div>
      <template #footer
        ><UiButton @click="confirmOpen = false">返回</UiButton
        ><UiButton
          variant="primary"
          :busy="busy"
          :disabled="!checked"
          @click="confirm"
          >保存核对结果</UiButton
        ></template
      ></UiModal
    >
    <UiModal
      :open="!!deleteTarget"
      title="删除历史记录"
      @close="deleteTarget = null"
    >
      <p class="text-sm text-muted leading-7">
        删除这条本地记录？原文件和 Telegram 中的消息保留。
      </p>
      <p v-if="deleteTarget?.state === 'unknown'" class="warning-box mt-4">
        结果仍待确认，删除后将失去本地核对信息。
      </p>
      <template #footer>
        <UiButton :disabled="deleting" @click="deleteTarget = null"
          >取消</UiButton
        >
        <UiButton variant="danger" :busy="deleting" @click="deleteRecord">{{
          deleteTarget?.state === "unknown" ? "仍然删除" : "删除记录"
        }}</UiButton>
      </template>
    </UiModal>
  </div>
</template>

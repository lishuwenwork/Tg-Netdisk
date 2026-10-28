<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import {
  Check,
  FolderOpen,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Wifi,
} from "lucide-vue-next";
import { useWorkspace } from "../stores/workspace";
import { api } from "../lib/api";
import { bytes } from "../lib/format";
import type { Auth } from "../types";
import UiButton from "./UiButton.vue";
import UiModal from "./UiModal.vue";
const props = defineProps<{ account: boolean }>();
const store = useWorkspace();
interface UploadDiagnostics {
  crypto_backend: string;
  native_crypto: boolean;
  aes_mib_s?: number;
  part_size_kib: number;
  max_in_flight: number;
  connected: boolean;
  latency_ms: number | null;
  proxy_enabled: boolean;
  dc_id: number | null;
}
const diagnostics = ref<UploadDiagnostics | null>(null),
  diagnosticOpen = ref(false),
  diagnosticBusy = ref(false);
async function loadProxies() {
  const value = await api<{ telegram_proxy: string; download_proxy: string }>(
    "settings/proxies",
  );
  if (!form.telegram_proxy) form.telegram_proxy = value.telegram_proxy;
  if (!form.download_proxy) form.download_proxy = value.download_proxy;
}
async function diagnoseUpload() {
  diagnosticBusy.value = true;
  await store.guarded(async () => {
    diagnostics.value = await api<UploadDiagnostics>("diagnostics/upload");
    diagnosticOpen.value = true;
  });
  diagnosticBusy.value = false;
}
function openLogs() {
  void window.desktop?.showLogs();
}
const form = reactive({
  api_id: "",
  api_hash: "",
  telegram_proxy: "",
  download_proxy: "",
  theme: "dark",
  close_behavior: "ask",
  default_channel: "",
  download_dir: "",
  upload_concurrency: 4,
});
const removeTelegramProxy = ref(false),
  removeDownloadProxy = ref(false),
  password = ref(""),
  busy = ref(false),
  logout = ref(false);
const cache = ref({ reclaimable: 0, protected: 0, removed: 0 }),
  now = ref(Date.now());
const timer = setInterval(() => {
  now.value = Date.now();
}, 1000);
onBeforeUnmount(() => clearInterval(timer));
watch(
  () => JSON.stringify(store.settings),
  () => {
    const value = store.settings;
    Object.assign(form, {
      api_id: value.api_id,
      theme: value.theme,
      close_behavior: value.close_behavior,
      default_channel: value.default_channel,
      download_dir: value.download_dir,
      upload_concurrency: value.upload_concurrency ?? 4,
    });
  },
  { immediate: true },
);
const remaining = computed(() =>
  Math.max(
    0,
    Math.round(
      (new Date(store.auth.expires || 0).getTime() - now.value) / 1000,
    ),
  ),
);
const authLabels: Record<Auth["state"], string> = {
  unconfigured: "未配置",
  logged_out: "未登录",
  waiting_qr: "等待扫码",
  qr_expired: "二维码已过期",
  password_required: "需要两步验证",
  authorized: "已登录",
  offline: "连接中断",
};
async function save() {
  busy.value = true;
  await store.guarded(async () => {
    await api("settings", "PUT", {
      api_id: form.api_id,
      api_hash: form.api_hash || undefined,
      telegram_proxy: removeTelegramProxy.value
        ? ""
        : form.telegram_proxy || undefined,
      download_proxy: removeDownloadProxy.value
        ? ""
        : form.download_proxy || undefined,
      default_channel: form.default_channel,
      theme: form.theme,
      close_behavior: form.close_behavior,
      download_dir: form.download_dir,
      upload_concurrency: form.upload_concurrency,
    });
    form.api_hash = "";
    if (removeTelegramProxy.value) form.telegram_proxy = "";
    if (removeDownloadProxy.value) form.download_proxy = "";
    removeTelegramProxy.value = false;
    removeDownloadProxy.value = false;
    await store.refresh();
    if (props.account) await loadProxies();
    store.notify("设置已保存");
  });
  busy.value = false;
}
async function qr() {
  busy.value = true;
  await store.guarded(async () => {
    store.auth = await api<Auth>("auth/qr", "POST");
  });
  busy.value = false;
}
async function verify() {
  busy.value = true;
  const value = password.value;
  password.value = "";
  await store.guarded(async () => {
    store.auth = await api<Auth>("auth/password", "POST", { password: value });
    await store.refresh();
  });
  busy.value = false;
}
async function test(target: string) {
  await store.guarded(async () => {
    await api(`settings/test/${target}`, "POST");
    store.notify("连接正常");
  });
}
async function cacheStats() {
  await store.guarded(async () => {
    cache.value = await api("cache");
  });
}
async function clean() {
  await store.guarded(async () => {
    const result = await api<typeof cache.value>("cache/clean", "POST");
    store.notify(`已清理 ${bytes(result.removed)}`);
    await cacheStats();
    await store.refresh();
  });
}
async function chooseDirectory() {
  const folder = await window.desktop?.chooseDirectory();
  if (folder) form.download_dir = folder;
}
void cacheStats();
if (props.account) void store.guarded(loadProxies);
</script>
<template>
  <div class="page-content settings-page">
    <div class="page-title-row">
      <div>
        <span class="eyebrow">{{
          account ? "ACCOUNT & CONNECTION" : "PREFERENCES"
        }}</span>
        <h1>{{ account ? "账号与连接" : "设置" }}</h1>
      </div>
      <UiButton
        variant="primary"
        :busy="busy"
        :disabled="!store.online"
        @click="save"
        ><Check :size="15" />保存设置</UiButton
      >
    </div>
    <template v-if="account"
      ><div class="settings-columns">
        <section class="settings-card">
          <h2>应用凭据</h2>
          <div class="space-y-5 mt-6">
            <label class="field-label block"
              >API ID<input
                v-model="form.api_id"
                class="field mt-3 font-mono"
                inputmode="numeric"
                placeholder="12345678"
                autocomplete="off" /></label
            ><label class="field-label block"
              >API Hash<input
                v-model="form.api_hash"
                class="field mt-3 font-mono"
                type="password"
                :placeholder="
                  store.settings.has_api_hash ? '已保存 · 留空保留' : 'API Hash'
                "
                autocomplete="new-password"
            /></label>
          </div>
        </section>
        <section class="settings-card">
          <div class="flex justify-between">
            <h2>Telegram 账号</h2>
            <span
              class="status-pill"
              :class="{ succeeded: store.auth.state === 'authorized' }"
              ><ShieldCheck :size="12" />{{
                authLabels[store.auth.state]
              }}</span
            >
          </div>
          <div class="login-body">
            <template v-if="store.auth.state === 'authorized'"
              ><div class="account-avatar">
                {{ store.auth.user?.name.slice(0, 1) }}
              </div>
              <strong>{{ store.auth.user?.name }}</strong
              ><span class="text-xs text-muted">{{ store.auth.user?.id }}</span
              ><UiButton variant="ghost" @click="logout = true"
                >退出登录</UiButton
              ></template
            ><template v-else-if="store.auth.state === 'password_required'"
              ><form class="w-full space-y-4" @submit.prevent="verify">
                <label class="field-label block"
                  >两步验证密码<input
                    v-model="password"
                    class="field mt-3"
                    type="password"
                    autocomplete="current-password" /></label
                ><UiButton
                  variant="primary"
                  :busy="busy"
                  :disabled="!password"
                  @click="verify"
                  >验证</UiButton
                >
              </form></template
            ><template v-else
              ><img
                v-if="store.auth.qr && remaining > 0"
                :src="store.auth.qr"
                alt="Telegram 登录二维码"
                class="qr-image"
              /><span
                v-if="store.auth.state === 'waiting_qr'"
                class="text-xs text-muted"
                >{{
                  remaining > 0 ? `${remaining} 秒后过期` : "二维码已过期"
                }}</span
              ><UiButton :busy="busy" :disabled="!store.online" @click="qr"
                ><RefreshCw :size="14" />{{
                  store.auth.qr ? "刷新二维码" : "扫码登录"
                }}</UiButton
              ><button
                v-if="
                  ['waiting_qr', 'password_required'].includes(store.auth.state)
                "
                class="text-button muted"
                @click="
                  store.guarded(async () => {
                    store.auth = await api<Auth>('auth/cancel', 'POST');
                  })
                "
              >
                取消登录
              </button></template
            >
          </div>
        </section>
      </div>
      <section class="settings-card mt-5">
        <h2>连接代理</h2>
        <div class="settings-columns mt-6">
          <div class="space-y-3">
            <label class="field-label block"
              >Telegram 代理<input
                v-model="form.telegram_proxy"
                class="field mt-3 font-mono"
                type="text"
                placeholder="socks5://127.0.0.1:10808"
                autocomplete="off"
                spellcheck="false"
            /></label>
            <div class="flex justify-between">
              <label
                v-if="store.settings.has_telegram_proxy"
                class="check-label"
                ><input
                  v-model="removeTelegramProxy"
                  type="checkbox"
                />移除代理</label
              ><button
                class="text-button muted ml-auto"
                @click="test('telegram')"
              >
                <Wifi :size="13" />测试连接
              </button>
              <button
                class="text-button muted ml-3"
                :disabled="diagnosticBusy"
                @click="diagnoseUpload"
              >
                {{ diagnosticBusy ? "诊断中…" : "上传诊断" }}
              </button>
            </div>
          </div>
          <div class="space-y-3">
            <label class="field-label block"
              >下载代理<input
                v-model="form.download_proxy"
                class="field mt-3 font-mono"
                type="text"
                placeholder="http://127.0.0.1:10808"
                autocomplete="off"
                spellcheck="false"
            /></label>
            <div class="flex justify-between">
              <label
                v-if="store.settings.has_download_proxy"
                class="check-label"
                ><input
                  v-model="removeDownloadProxy"
                  type="checkbox"
                />移除代理</label
              ><button
                class="text-button muted ml-auto"
                @click="test('download')"
              >
                <Wifi :size="13" />测试连接
              </button>
            </div>
          </div>
        </div>
      </section></template
    >
    <template v-else
      ><section class="settings-card">
        <h2>常规</h2>
        <div class="settings-fields">
          <label class="field-label"
            >主题<select v-model="form.theme" class="field" aria-label="主题">
              <option value="dark">深色</option>
              <option value="light">浅色</option>
            </select></label
          ><label class="field-label"
            >关闭窗口<select
              v-model="form.close_behavior"
              class="field"
              aria-label="关闭窗口"
            >
              <option value="ask">退出前检查任务</option>
              <option value="hide">后台运行</option>
            </select></label
          ><label class="field-label"
            >默认频道<select
              v-model="form.default_channel"
              class="field"
              aria-label="默认频道"
            >
              <option value="">未设置</option>
              <option
                v-for="channel in store.channels.filter((c) => c.can_post)"
                :key="channel.id"
                :value="channel.id"
              >
                {{ channel.name }}
              </option>
            </select></label
          ><label class="field-label"
            >上传并发数<select
              v-model="form.upload_concurrency"
              class="field"
              aria-label="上传并发数"
              aria-describedby="upload-concurrency-help"
            >
              <option v-for="count in 10" :key="count" :value="count">
                {{ count }}
              </option>
            </select>
            <span
              id="upload-concurrency-help"
              class="text-xs text-muted leading-5"
              >范围 1～10，默认 4；保存后从下一个文件上传开始生效。</span
            ></label
          ><label class="field-label"
            >下载目录
            <div class="flex gap-2">
              <input
                v-model="form.download_dir"
                class="field flex-1"
                placeholder="默认缓存目录"
              /><button
                class="icon-btn"
                aria-label="选择下载目录"
                @click="chooseDirectory"
              >
                <FolderOpen :size="17" />
              </button></div
          ></label>
        </div>
      </section>
      <section class="settings-card mt-5">
        <div class="flex justify-between items-center">
          <h2>缓存</h2>
          <button class="text-button muted" @click="cacheStats">刷新</button>
        </div>
        <div class="cache-stats">
          <div>
            <span>可清理</span><strong>{{ bytes(cache.reclaimable) }}</strong>
          </div>
          <div>
            <span>正在引用</span><strong>{{ bytes(cache.protected) }}</strong>
          </div>
          <UiButton @click="clean"><Trash2 :size="14" />清理缓存</UiButton>
        </div>
      </section>
      <section class="settings-card mt-5">
        <h2>日志与数据</h2>
        <div class="flex flex-wrap justify-between gap-4 mt-5">
          <span class="text-muted text-xs break-all">{{
            store.settings.data_dir || "—"
          }}</span
          ><UiButton @click="openLogs"
            ><FolderOpen :size="14" />打开日志</UiButton
          >
        </div>
      </section></template
    >
    <UiModal :open="logout" title="退出登录" @close="logout = false"
      ><p class="text-sm text-muted leading-7">
        将注销当前 Telegram 会话。原视频、草稿和历史记录保留。
      </p>
      <template #footer
        ><UiButton @click="logout = false">取消</UiButton
        ><UiButton
          variant="danger"
          @click="
            store.guarded(async () => {
              store.auth = await api<Auth>('auth/logout', 'POST');
              logout = false;
            })
          "
          >退出登录</UiButton
        ></template
      ></UiModal
    >
    <UiModal
      :open="diagnosticOpen"
      title="上传诊断"
      @close="diagnosticOpen = false"
    >
      <dl v-if="diagnostics" class="detail-grid">
        <dt>加密加速</dt>
        <dd>
          {{ diagnostics.native_crypto ? "已启用" : "未启用" }} ·
          {{ diagnostics.crypto_backend }}
        </dd>
        <dt>加密计算</dt>
        <dd>{{ diagnostics.aes_mib_s ?? "—" }} MiB/s</dd>
        <dt>上传分块</dt>
        <dd>{{ diagnostics.part_size_kib }} KiB</dd>
        <dt>并行分块</dt>
        <dd>{{ diagnostics.max_in_flight }}</dd>
        <dt>连接代理</dt>
        <dd>{{ diagnostics.proxy_enabled ? "已使用" : "直连" }}</dd>
        <dt>线路延迟</dt>
        <dd>
          {{
            diagnostics.latency_ms == null
              ? "未测得"
              : diagnostics.latency_ms + " ms"
          }}
        </dd>
        <dt>连接状态</dt>
        <dd>{{ diagnostics.connected ? "已连接" : "未连接" }}</dd>
      </dl>
      <p class="mt-5 text-xs text-muted">加密计算速度不等于实际上传速度。</p>
    </UiModal>
  </div>
</template>

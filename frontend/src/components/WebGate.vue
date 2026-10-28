<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { LockKeyhole, Send } from "lucide-vue-next";
import App from "../App.vue";
import { webMode } from "../lib/api";
import UiButton from "./UiButton.vue";
const web = webMode(),
  authenticated = ref(!web),
  loading = ref(web),
  busy = ref(false),
  password = ref(""),
  error = ref("");
function expired() {
  authenticated.value = false;
  password.value = "";
}
async function check() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch("/api/web/session", {
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("服务不可用");
    authenticated.value = (
      (await response.json()) as { authenticated: boolean }
    ).authenticated;
  } catch {
    error.value = "无法连接服务，请检查服务器状态";
  } finally {
    loading.value = false;
  }
}
async function login() {
  busy.value = true;
  error.value = "";
  const value = password.value;
  password.value = "";
  try {
    const response = await fetch("/api/web/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: value }),
    });
    const result = (await response.json()) as {
      message?: string;
      authenticated?: boolean;
    };
    if (!response.ok) throw new Error(result.message || "登录失败");
    authenticated.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "连接失败";
  } finally {
    busy.value = false;
  }
}
onMounted(() => {
  if (web) {
    window.addEventListener("tg-session-expired", expired);
    void check();
  }
});
onBeforeUnmount(() =>
  window.removeEventListener("tg-session-expired", expired),
);
</script>
<template>
  <App v-if="authenticated" />
  <main v-else class="web-login">
    <form class="web-login-card" @submit.prevent="login">
      <div class="brand">
        <div class="brand-icon"><Send :size="21" /></div>
        <span>Tg Netdisk</span>
      </div>
      <div v-if="loading" class="flex justify-center py-8">
        <span class="spinner" />
      </div>
      <template v-else
        ><label for="web-password" class="field-label block mb-3"
          >访问密码</label
        ><input
          id="web-password"
          v-model="password"
          class="field"
          type="password"
          autocomplete="current-password"
          required
          autofocus
        />
        <p v-if="error" class="field-error mt-4" role="alert">{{ error }}</p>
        <UiButton
          variant="primary"
          class="w-full mt-6"
          :busy="busy"
          :disabled="!password"
          @click="login"
          ><LockKeyhole :size="14" />登录</UiButton
        ><button
          v-if="error"
          class="text-button muted mt-4"
          type="button"
          @click="check"
        >
          重新连接
        </button></template
      >
    </form>
  </main>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useMessage } from "naive-ui";

import { api, ApiError } from "../api";
import { formatBytes } from "../format";
import { zhCN } from "../locales/zh-CN";

const message = useMessage();
const suffix = ref("");
const password = ref("");
const generatedKey = ref("");
const recorded = ref(false);
const busy = ref(false);
const error = ref("");
const currentPassword = ref("");
const newPassword = ref("");
const passwordConfirmation = ref("");

onMounted(async () => { suffix.value = (await api.apiKey()).suffix; });

async function rotate(): Promise<void> {
  if (!password.value || !confirm("旧 APIkey 将立即失效，所有 Android 客户端均需重新配置。是否继续？")) return;
  busy.value = true;
  try {
    const result = await api.rotateApiKey(password.value);
    generatedKey.value = result.api_key;
    suffix.value = result.suffix;
    password.value = "";
    recorded.value = false;
  } catch (reason) { error.value = reason instanceof ApiError ? reason.message : zhCN.requestFailed; }
  finally { busy.value = false; }
}

function closeKey(): void {
  if (!recorded.value) return;
  generatedKey.value = "";
}

async function cleanup(): Promise<void> {
  busy.value = true;
  try {
    const preview = await api.cleanupPreview();
    if (!confirm(`预计释放 ${formatBytes(preview.estimated_bytes)}，涉及 ${preview.file_count + preview.cache_file_count} 项。是否清理？`)) return;
    const result = await api.cleanup(preview.confirmation_id);
    message.success(`实际释放 ${formatBytes(result.released_bytes)}，失败 ${result.failure_count} 项`);
  } catch (reason) { error.value = reason instanceof ApiError ? reason.message : zhCN.requestFailed; }
  finally { busy.value = false; }
}

async function changePassword(): Promise<void> {
  if (!currentPassword.value || newPassword.value !== passwordConfirmation.value) { error.value = "请填写当前密码，并确保两次新密码一致。"; return; }
  busy.value = true;
  try {
    await api.changePassword(currentPassword.value, newPassword.value, passwordConfirmation.value);
    location.assign("/login");
  } catch (reason) { error.value = reason instanceof ApiError ? reason.message : zhCN.requestFailed; }
  finally { busy.value = false; }
}
</script>

<template>
  <main class="admin-page settings-page">
    <header class="admin-heading"><div><p class="section-index">CONFIG / 07</p><h1>{{ zhCN.settings }}</h1><p>服务端身份、缓存与版本</p></div></header>
    <p v-if="error" class="detail-error">{{ error }}</p>
    <section class="settings-grid">
      <article><span>01</span><h2>修改管理员密码</h2><p>密码首尾空白属于密码本身。修改成功后，所有 Web 会话会立即撤销。</p><label>当前密码<input v-model="currentPassword" type="password" autocomplete="current-password" /></label><label>新密码<input v-model="newPassword" type="password" autocomplete="new-password" /></label><label>再次输入新密码<input v-model="passwordConfirmation" type="password" autocomplete="new-password" /></label><button class="quiet-button" type="button" :disabled="busy" @click="changePassword">保存新密码</button></article>
      <article><span>02</span><h2>{{ zhCN.apiKeyManagement }}</h2><p>当前 APIkey 末尾为 <strong class="mono">••••{{ suffix }}</strong>。完整旧 key 无法再次查看。</p><label>当前管理员密码<input v-model="password" type="password" autocomplete="current-password" /></label><button class="danger-button" type="button" :disabled="busy || !password" @click="rotate">{{ zhCN.rotateApiKey }}</button></article>
      <article><span>03</span><h2>服务端缓存</h2><p>清理无效封面、过期临时文件，以及不再对应现有内容的元数据。有效内容读取不受影响。</p><button class="quiet-button" type="button" :disabled="busy" @click="cleanup">{{ zhCN.cleanupCache }}</button></article>
      <article><span>04</span><h2>Dokura</h2><p>API v1 · 本地内容库<br />首版只运行一个服务进程。</p><a href="https://github.com/" rel="noreferrer">项目 GitHub ↗</a></article>
    </section>
    <dialog :open="Boolean(generatedKey)" class="key-dialog"><p class="section-index">ONE-TIME SECRET</p><h2>请立即记录新的 APIkey</h2><code>{{ generatedKey }}</code><p>关闭后无法再次查看，只能重新生成。</p><label><input v-model="recorded" type="checkbox" /> 我已经安全记录此 APIkey</label><button class="primary-button" type="button" :disabled="!recorded" @click="closeKey">确认并关闭</button></dialog>
  </main>
</template>

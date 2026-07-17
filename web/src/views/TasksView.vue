<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useMessage } from "naive-ui";

import { api, ApiError } from "../api";
import { formatDate } from "../format";
import { zhCN } from "../locales/zh-CN";
import type { TaskItem } from "../types";

const message = useMessage();
const items = ref<TaskItem[]>([]);
const waiting = ref(0);
const loading = ref(true);
const error = ref("");
let timer: ReturnType<typeof setInterval> | undefined;

const groups = computed(() => ({
  active: items.value.filter((item) => item.status === "analyzing"),
  waiting: items.value.filter((item) => ["waiting_stable", "retry_wait"].includes(item.status)),
  history: items.value.filter((item) => !["analyzing", "waiting_stable", "retry_wait"].includes(item.status)),
}));

async function load(silent = false): Promise<void> {
  if (!silent) loading.value = true;
  try {
    const result = await api.tasks();
    items.value = result.items;
    waiting.value = result.waiting_count;
    error.value = "";
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : zhCN.requestFailed;
  } finally {
    loading.value = false;
  }
}

async function scan(): Promise<void> {
  const result = await api.scan();
  message.success(result.accepted ? "扫描已提交" : "扫描已在队列中");
  await load(true);
}

async function retryFailed(): Promise<void> {
  if (!confirm("将为所有处理失败的 ZIP 开启新一轮重试，是否继续？")) return;
  const result = await api.retryFailed();
  message.success(`已加入 ${result.added} 项，跳过 ${result.skipped} 项`);
  await load(true);
}

onMounted(() => {
  void load();
  timer = setInterval(() => void load(true), 2000);
});
onBeforeUnmount(() => { if (timer) clearInterval(timer); });
</script>

<template>
  <main class="admin-page">
    <header class="admin-heading"><div><p class="section-index">QUEUE / 05</p><h1>{{ zhCN.tasks }}</h1><p>每 2 秒更新 · 离开本页后停止轮询</p></div><div class="admin-heading-actions"><button class="quiet-button" type="button" @click="retryFailed">{{ zhCN.retryAllFailed }}</button><button class="primary-button" type="button" @click="scan">{{ zhCN.rescan }} <span>↻</span></button></div></header>
    <p v-if="error" class="detail-error">{{ error }}</p>
    <section class="queue-summary"><strong>{{ waiting }}</strong><span>项等待处理</span><i :class="{ active: !loading }"></i></section>
    <section v-for="(group, key) in groups" :key="key" class="admin-section">
      <header><h2>{{ key === 'active' ? '正在执行' : key === 'waiting' ? '等待队列' : '最近完成与失败' }}</h2><span>{{ group.length }}</span></header>
      <div v-if="group.length" class="task-table">
        <article v-for="task in group" :key="task.id">
          <span class="task-status" :data-status="task.status">{{ task.status }}</span>
          <div><RouterLink v-if="task.file_id" :to="`/files/${task.file_id}`">{{ task.relative_path || task.file_id }}</RouterLink><strong v-else>{{ task.relative_path || '系统任务' }}</strong><small class="mono">{{ task.id }}</small></div>
          <dl><div><dt>优先级</dt><dd>{{ task.priority }}</dd></div><div><dt>重试</dt><dd>{{ task.retry_count }} / {{ task.max_retries }}</dd></div><div><dt>更新时间</dt><dd>{{ formatDate(task.updated_at) }}</dd></div></dl>
          <p v-if="task.last_error">{{ task.last_error }}</p>
        </article>
      </div>
      <p v-else class="admin-empty">没有项目</p>
    </section>
  </main>
</template>

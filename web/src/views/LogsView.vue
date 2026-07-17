<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api, ApiError } from "../api";
import { zhCN } from "../locales/zh-CN";

const levels = ref<string[]>([]);
const items = ref<{ level: string; message: string }[]>([]);
const error = ref("");
const writeError = ref<string | null>(null);

async function load(): Promise<void> {
  try {
    const result = await api.logs(levels.value);
    items.value = result.items;
    writeError.value = result.write_error;
    error.value = "";
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : zhCN.requestFailed;
  }
}

function toggle(level: string): void {
  levels.value = levels.value.includes(level) ? levels.value.filter((item) => item !== level) : [...levels.value, level];
  void load();
}

onMounted(load);
</script>

<template>
  <main class="admin-page logs-page">
    <header class="admin-heading"><div><p class="section-index">SYSTEM LOG / 06</p><h1>{{ zhCN.logs }}</h1><p>当前与已轮转日志的最终 1,000 条</p></div><a class="primary-button" href="/api/v1/admin/logs/archive">{{ zhCN.downloadArchive }} <span>↓</span></a></header>
    <div class="log-toolbar"><span>级别筛选</span><button v-for="level in ['ERROR', 'WARNING', 'INFO']" :key="level" type="button" :class="{ selected: levels.includes(level) }" @click="toggle(level)">{{ level }}</button><button type="button" @click="load">刷新</button></div>
    <p v-if="writeError" class="detail-error">日志写入异常：{{ writeError }}</p><p v-if="error" class="detail-error">{{ error }}</p>
    <section class="log-console" aria-live="polite"><p v-for="(item, index) in items" :key="index" :data-level="item.level"><span>{{ item.level }}</span>{{ item.message }}</p><div v-if="!items.length" class="admin-empty">没有符合条件的日志</div></section>
  </main>
</template>

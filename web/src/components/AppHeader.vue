<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "../api";
import { zhCN } from "../locales/zh-CN";
import type { ThemeMode } from "../types";

const props = defineProps<{ theme: ThemeMode }>();
const emit = defineEmits<{ theme: [mode: ThemeMode] }>();
const route = useRoute();
const router = useRouter();
const context = computed(() => ({ catalog: zhCN.library, detail: zhCN.details, settings: zhCN.settings, tasks: zhCN.tasks, logs: zhCN.logs }[String(route.name)] ?? ""));

async function logout(): Promise<void> {
  try {
    await api.logout();
  } finally {
    await router.replace({ name: "login" });
  }
}
</script>

<template>
  <header class="app-header">
    <RouterLink class="wordmark" to="/" :aria-label="`${zhCN.brand} ${zhCN.library}`">
      <span class="wordmark-mark" aria-hidden="true">D</span>
      <span>{{ zhCN.brand }}<small>{{ zhCN.library }}</small></span>
    </RouterLink>
    <div class="header-context" aria-hidden="true">
      <span></span>{{ context }}
    </div>
    <div class="header-actions">
      <nav class="admin-nav" :aria-label="zhCN.management"><RouterLink to="/tasks">{{ zhCN.tasks }}</RouterLink><RouterLink to="/logs">{{ zhCN.logs }}</RouterLink><RouterLink to="/settings">{{ zhCN.settings }}</RouterLink></nav>
      <label class="compact-select">
        <span class="sr-only">{{ zhCN.theme }}</span>
        <select :value="props.theme" @change="emit('theme', ($event.target as HTMLSelectElement).value as ThemeMode)">
          <option value="system">{{ zhCN.themeSystem }}</option>
          <option value="light">{{ zhCN.themeLight }}</option>
          <option value="dark">{{ zhCN.themeDark }}</option>
        </select>
      </label>
      <button class="quiet-button" type="button" @click="logout">{{ zhCN.logout }}</button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { darkTheme, dateZhCN, lightTheme, NConfigProvider, NMessageProvider, zhCN as naiveZhCN } from "naive-ui";
import { useRoute, useRouter } from "vue-router";

import { api, ApiError } from "./api";
import AppHeader from "./components/AppHeader.vue";
import StatePanel from "./components/StatePanel.vue";
import { zhCN } from "./locales/zh-CN";
import type { ThemeMode } from "./types";

const route = useRoute();
const router = useRouter();
const theme = ref<ThemeMode>((localStorage.getItem("dokura-theme") as ThemeMode) || "system");
const systemDark = ref(matchMedia("(prefers-color-scheme: dark)").matches);
const sessionState = ref<"checking" | "authenticated" | "anonymous">("checking");
const immersive = computed(() => route.meta.immersive === true);
const resolvedDark = computed(() => theme.value === "dark" || (theme.value === "system" && systemDark.value));
const media = matchMedia("(prefers-color-scheme: dark)");

function onSystemTheme(event: MediaQueryListEvent): void {
  systemDark.value = event.matches;
}

function setTheme(value: ThemeMode): void {
  theme.value = value;
  localStorage.setItem("dokura-theme", value);
}

async function checkSession(): Promise<void> {
  if (route.meta.public) {
    sessionState.value = "anonymous";
    return;
  }
  sessionState.value = "checking";
  try {
    await api.session();
    sessionState.value = "authenticated";
  } catch (error) {
    sessionState.value = "anonymous";
    if (error instanceof ApiError && error.status === 401) {
      await router.replace({ name: "login", query: { redirect: route.fullPath } });
    }
  }
}

watch(() => route.fullPath, () => {
  if (route.meta.public) sessionState.value = "anonymous";
  else if (sessionState.value !== "authenticated") void checkSession();
});
watch(resolvedDark, (dark) => document.documentElement.dataset.theme = dark ? "dark" : "light", { immediate: true });

onMounted(() => {
  media.addEventListener("change", onSystemTheme);
  void checkSession();
});
onBeforeUnmount(() => media.removeEventListener("change", onSystemTheme));
</script>

<template>
  <NConfigProvider :theme="resolvedDark ? darkTheme : lightTheme" :locale="naiveZhCN" :date-locale="dateZhCN">
    <NMessageProvider>
      <div v-if="sessionState === 'checking'" class="boot-screen">
        <StatePanel :title="zhCN.loading" kind="loading" />
      </div>
      <RouterView v-else-if="route.meta.public" />
      <div v-else-if="sessionState === 'authenticated'" :class="['app-frame', { immersive }]">
        <AppHeader v-if="!immersive" :theme="theme" @theme="setTheme" />
        <RouterView />
      </div>
    </NMessageProvider>
  </NConfigProvider>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, ApiError, originalUrl } from "../api";
import StatePanel from "../components/StatePanel.vue";
import { zhCN } from "../locales/zh-CN";
import type { FileDetail } from "../types";

const route = useRoute();
const router = useRouter();
const detail = ref<FileDetail>();
const detailError = ref("");
const imageState = ref<"loading" | "ready" | "error" | "unavailable">("loading");
const imageKey = ref(0);
const pageNumber = computed(() => Number(route.params.page));
const total = computed(() => detail.value?.page_count ?? 0);
const validPage = computed(() => Math.max(1, Math.min(pageNumber.value || 1, total.value || 1)));
const from = computed(() => typeof route.query.from === "string" && route.query.from.startsWith("/files/") ? route.query.from : `/files/${route.params.id}`);
let controller: AbortController | undefined;

async function loadDetail(): Promise<void> {
  controller?.abort();
  controller = new AbortController();
  detailError.value = "";
  try {
    detail.value = await api.detail(String(route.params.id), controller.signal);
    document.title = zhCN.pageDocumentTitle(detail.value.name, validPage.value);
    if (pageNumber.value !== validPage.value) await go(validPage.value, true);
    else resetImage();
  } catch (reason) {
    if ((reason as Error).name !== "AbortError") {
      detailError.value = reason instanceof ApiError ? reason.message : zhCN.connectFailed;
    }
  }
}

function resetImage(): void {
  imageState.value = detail.value?.pages.find((page) => page.number === validPage.value)?.unavailable ? "unavailable" : "loading";
  imageKey.value += 1;
  document.title = detail.value ? zhCN.pageDocumentTitle(detail.value.name, validPage.value) : zhCN.brand;
}

async function go(page: number, replace = false): Promise<void> {
  if (!detail.value || page < 1 || page > detail.value.page_count) return;
  const target = { name: "reader", params: { id: detail.value.id, page }, query: route.query };
  await (replace ? router.replace(target) : router.push(target));
}

function back(): void {
  void router.push(from.value);
}

function onKey(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null;
  if (target?.matches("input, select, textarea, button")) return;
  if (event.key === "ArrowLeft") void go(validPage.value - 1);
  else if (event.key === "ArrowRight") void go(validPage.value + 1);
  else if (event.key === "Home") { event.preventDefault(); void go(1); }
  else if (event.key === "End") { event.preventDefault(); void go(total.value); }
  else if (event.key === "Escape") back();
}

watch(() => route.params.id, () => void loadDetail(), { immediate: true });
watch(() => route.params.page, (_page, previous) => {
  if (previous !== undefined && detail.value) resetImage();
});
onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => {
  controller?.abort();
  window.removeEventListener("keydown", onKey);
  document.title = "Dokura";
});
</script>

<template>
  <main class="reader-page">
    <header class="reader-header">
      <button type="button" @click="back">← <span>{{ zhCN.backToDetails }}</span></button>
      <p v-if="detail">{{ detail.name }}</p>
      <span>DOKURA / READER</span>
    </header>

    <StatePanel v-if="detailError" :title="zhCN.notFound" :message="detailError" kind="error" :action="zhCN.backToLibrary" @action="router.push('/')" />
    <template v-else-if="detail">
      <section class="reader-canvas" aria-live="polite">
        <div v-if="imageState === 'loading'" class="reader-placeholder"><i></i><span>{{ zhCN.readingPage(validPage) }}</span></div>
        <StatePanel v-else-if="imageState === 'unavailable'" :title="zhCN.unavailable" kind="unavailable" :action="zhCN.backToDetails" @action="back" />
        <StatePanel v-else-if="imageState === 'error'" :title="zhCN.imageFailed" kind="error" :action="zhCN.retryImage" @action="resetImage" />
        <img
          v-if="imageState !== 'unavailable'"
          :key="imageKey"
          :src="originalUrl(detail.id, validPage)"
          :alt="zhCN.pageImageAlt(validPage)"
          :class="{ visible: imageState === 'ready' }"
          @load="imageState = 'ready'"
          @error="imageState = 'error'"
        />
        <button class="reader-arrow previous" type="button" :disabled="validPage <= 1" :aria-label="zhCN.previousPage" @click="go(validPage - 1)">←</button>
        <button class="reader-arrow next" type="button" :disabled="validPage >= total" :aria-label="zhCN.nextPage" @click="go(validPage + 1)">→</button>
      </section>
      <footer class="reader-controls">
        <span>{{ String(validPage).padStart(3, "0") }}</span>
        <input :value="validPage" type="range" min="1" :max="total" :aria-label="zhCN.pageSlider(validPage, total)" @input="go(Number(($event.target as HTMLInputElement).value), true)" />
        <span>{{ String(total).padStart(3, "0") }}</span>
      </footer>
    </template>
  </main>
</template>

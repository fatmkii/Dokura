<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError, previewUrl } from "../api";
import { zhCN } from "../locales/zh-CN";

const props = defineProps<{ fileId: string; page: number; unavailable?: boolean }>();
const emit = defineEmits<{ open: [page: number] }>();

const root = ref<HTMLElement>();
const imageUrl = ref("");
const state = ref<"idle" | "loading" | "ready" | "error" | "unavailable">(props.unavailable ? "unavailable" : "idle");
let observer: IntersectionObserver | undefined;
let controller: AbortController | undefined;
let objectUrl = "";

function previewSize(): number {
  const pixels = (root.value?.clientWidth ?? 200) * window.devicePixelRatio;
  if (pixels <= 256) return 256;
  if (pixels <= 512) return 512;
  return 768;
}

async function load(): Promise<void> {
  if (state.value !== "idle" && state.value !== "error") return;
  state.value = "loading";
  controller = new AbortController();
  try {
    const response = await fetch(previewUrl(props.fileId, props.page, previewSize()), {
      credentials: "same-origin",
      signal: controller.signal,
    });
    if (!response.ok) {
      if (response.status === 410) state.value = "unavailable";
      else throw new ApiError(response.status, zhCN.previewFailed);
      return;
    }
    objectUrl = URL.createObjectURL(await response.blob());
    imageUrl.value = objectUrl;
    state.value = "ready";
  } catch (error) {
    if ((error as Error).name !== "AbortError") state.value = "error";
    else state.value = "idle";
  } finally {
    controller = undefined;
  }
}

onMounted(async () => {
  await nextTick();
  observer = new IntersectionObserver(
    ([entry]) => {
      if (entry.isIntersecting) void load();
      else if (state.value === "loading") controller?.abort();
    },
    { rootMargin: "0px" },
  );
  if (root.value) observer.observe(root.value);
});

onBeforeUnmount(() => {
  observer?.disconnect();
  controller?.abort();
  if (objectUrl) URL.revokeObjectURL(objectUrl);
});
</script>

<template>
  <button ref="root" class="preview-tile" type="button" :aria-label="zhCN.readPage(page)" @click="state === 'ready' && emit('open', page)">
    <span class="preview-frame">
      <img v-if="state === 'ready'" :src="imageUrl" :alt="zhCN.pagePreviewAlt(page)" />
      <span v-else-if="state === 'unavailable'" class="preview-state unavailable">{{ zhCN.unavailable }}</span>
      <span v-else-if="state === 'error'" class="preview-state error" @click.stop="load">{{ zhCN.previewFailed }}<small>{{ zhCN.retry }}</small></span>
      <span v-else class="preview-state loading" aria-hidden="true"><i></i></span>
    </span>
    <span class="preview-number">{{ String(page).padStart(3, "0") }}</span>
  </button>
</template>

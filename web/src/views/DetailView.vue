<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useMessage } from "naive-ui";
import { useRoute, useRouter } from "vue-router";

import { api, ApiError, coverUrl } from "../api";
import LazyPreview from "../components/LazyPreview.vue";
import RatingPicker from "../components/RatingPicker.vue";
import StatePanel from "../components/StatePanel.vue";
import { categoryLabel, formatBytes, formatDate, statusLabel } from "../format";
import { zhCN } from "../locales/zh-CN";
import type { FileDetail } from "../types";

const route = useRoute();
const router = useRouter();
const message = useMessage();
const detail = ref<FileDetail>();
const loading = ref(true);
const error = ref("");
const missing = ref(false);
let controller: AbortController | undefined;

const backTarget = computed(() => typeof route.query.from === "string" && route.query.from.startsWith("/") ? route.query.from : "/");
const groupedTags = computed(() => {
  const groups: Record<string, string[]> = { author: [], parody: [], language: [], other: [] };
  for (const tag of detail.value?.tags ?? []) (groups[tag.category] ?? groups.other).push(tag.value);
  return groups;
});

async function load(): Promise<void> {
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = "";
  missing.value = false;
  try {
    detail.value = await api.detail(String(route.params.id), controller.signal);
    document.title = `${detail.value.name} — Dokura`;
  } catch (reason) {
    if ((reason as Error).name === "AbortError") return;
    if (reason instanceof ApiError && (reason.status === 404 || reason.status === 403)) missing.value = true;
    else if (reason instanceof ApiError && reason.status === 401) await router.replace({ name: "login", query: { redirect: route.fullPath } });
    else error.value = reason instanceof ApiError ? reason.message : zhCN.connectFailed;
  } finally {
    loading.value = false;
  }
}

async function updateRating(value: number): Promise<void> {
  if (!detail.value) return;
  const previous = detail.value.rating;
  detail.value.rating = value;
  try {
    const saved = await api.rating(detail.value.id, value);
    detail.value.rating = saved.rating;
  } catch {
    detail.value.rating = previous;
    message.error(zhCN.saveRatingFailed);
  }
}

function read(page: number): void {
  if (!detail.value) return;
  void router.push({ name: "reader", params: { id: detail.value.id, page }, query: { from: route.fullPath } });
}

watch(() => route.params.id, load, { immediate: true });
onBeforeUnmount(() => {
  controller?.abort();
  document.title = "Dokura";
});
</script>

<template>
  <main class="detail-page">
    <StatePanel v-if="loading" :title="zhCN.loading" kind="loading" />
    <StatePanel v-else-if="missing" :title="zhCN.notFound" :message="zhCN.notFoundBody" kind="error" :action="zhCN.backToLibrary" @action="router.push(backTarget)" />
    <StatePanel v-else-if="error" :title="zhCN.loadFailed" :message="error" kind="error" :action="zhCN.retry" @action="load" />
    <template v-else-if="detail">
      <nav class="detail-back"><button type="button" @click="router.push(backTarget)">← {{ zhCN.backToLibrary }}</button><span>{{ detail.relative_path }}</span></nav>

      <section class="detail-hero">
        <div class="detail-cover">
          <img v-if="detail.cover_status === 'ready'" :src="coverUrl(detail.id)" :alt="zhCN.coverAlt(detail.name)" />
          <span v-else>NO<br />COVER</span>
          <i>{{ String(detail.page_count).padStart(3, "0") }} PAGES</i>
        </div>
        <div class="detail-intro">
          <p class="section-index">FILE / {{ detail.id.slice(0, 8).toUpperCase() }}</p>
          <h1>{{ detail.name }}</h1>
          <p class="detail-path">{{ detail.relative_path }}</p>
          <div class="hero-tags">
            <span v-for="tag in detail.tags" :key="tag.id"><small>{{ categoryLabel(tag.category) }}</small>{{ tag.value }}</span>
            <span v-if="!detail.tags.length"><small>{{ zhCN.tags }}</small>{{ zhCN.unrecognized }}</span>
          </div>
          <div class="detail-actions">
            <RatingPicker :model-value="detail.rating" @update:model-value="updateRating" />
            <button class="primary-button" type="button" :disabled="detail.page_count === 0" @click="read(1)">{{ zhCN.browseFromFirst }}<span>→</span></button>
          </div>
        </div>
        <dl class="detail-summary">
          <div><dt>{{ zhCN.status }}</dt><dd><span class="status-badge" :data-status="detail.status">{{ statusLabel(detail.status) }}</span></dd></div>
          <div><dt>{{ zhCN.size }}</dt><dd>{{ formatBytes(detail.size) }}<small>{{ detail.size.toLocaleString('zh-CN') }} B</small></dd></div>
          <div><dt>{{ zhCN.pageCount }}</dt><dd>{{ detail.page_count }}<small>{{ zhCN.unavailableCount }} {{ detail.unavailable_page_count }}</small></dd></div>
          <div><dt>{{ zhCN.modified }}</dt><dd>{{ formatDate(detail.modified_ns) }}<small :title="new Date(detail.modified_ns / 1_000_000).toISOString()">{{ zhCN.viewIsoTime }}</small></dd></div>
        </dl>
      </section>

      <section class="metadata-section" aria-labelledby="metadata-title">
        <header><p class="section-index">METADATA / 02</p><h2 id="metadata-title">{{ zhCN.metadata }}</h2></header>
        <div class="metadata-groups">
          <dl>
            <h3>{{ zhCN.parsedMetadata }}</h3>
            <div><dt>{{ zhCN.creator }}</dt><dd>{{ groupedTags.author.join('、') || detail.creator_raw || zhCN.unrecognized }}</dd></div>
            <div><dt>{{ zhCN.original }}</dt><dd>{{ groupedTags.parody.join('、') || zhCN.unrecognized }}</dd></div>
            <div><dt>{{ zhCN.language }}</dt><dd>{{ groupedTags.language.join('、') || zhCN.unrecognized }}</dd></div>
            <div><dt>{{ zhCN.otherTags }}</dt><dd>{{ detail.unclassified_tags.join('、') || zhCN.unrecognized }}</dd></div>
            <div><dt>{{ zhCN.confidence }}</dt><dd>{{ detail.parse_confidence == null ? zhCN.unrecognized : `${Math.round(detail.parse_confidence * 100)}%` }}</dd></div>
            <div><dt>{{ zhCN.warning }}</dt><dd>{{ detail.parse_warnings.join('；') || zhCN.none }}</dd></div>
          </dl>
          <dl>
            <h3>{{ zhCN.technicalMetadata }}</h3>
            <div><dt>{{ zhCN.uuid }}</dt><dd class="mono">{{ detail.id }}</dd></div>
            <div><dt>{{ zhCN.deviceInode }}</dt><dd class="mono">{{ detail.device ?? zhCN.unrecognized }} / {{ detail.inode ?? zhCN.unrecognized }}</dd></div>
            <div><dt>{{ zhCN.firstSeen }}</dt><dd :title="detail.created_at">{{ formatDate(detail.created_at) }}</dd></div>
            <div><dt>{{ zhCN.lastAnalyzed }}</dt><dd :title="detail.updated_at">{{ formatDate(detail.updated_at) }}</dd></div>
            <div><dt>{{ zhCN.parserVersion }}</dt><dd>{{ detail.parser_version }}</dd></div>
            <div><dt>{{ zhCN.coverStatus }}</dt><dd>{{ detail.cover_status }}</dd></div>
            <div><dt>{{ zhCN.cacheUsage }}</dt><dd>{{ formatBytes(detail.cover_cache_bytes) }}<small>{{ zhCN.serverCacheHint }}</small></dd></div>
          </dl>
        </div>
        <p v-if="detail.last_error" class="detail-error" role="status">{{ detail.last_error }}</p>
      </section>

      <section class="preview-section" aria-labelledby="preview-title">
        <header><div><p class="section-index">PAGES / 03</p><h2 id="preview-title">{{ zhCN.pages }}</h2></div><p>{{ zhCN.previewHint }}</p></header>
        <div v-if="detail.pages.length" class="preview-grid">
          <LazyPreview v-for="page in detail.pages" :key="page.number" :file-id="detail.id" :page="page.number" :unavailable="page.unavailable" @open="read" />
        </div>
        <StatePanel v-else :title="zhCN.empty" kind="empty" />
      </section>
    </template>
  </main>
</template>

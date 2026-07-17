<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useMessage } from "naive-ui";
import { useRoute, useRouter } from "vue-router";

import { api, ApiError, coverUrl } from "../api";
import { catalogQuery, parseCatalogState } from "../catalog-state";
import RatingPicker from "../components/RatingPicker.vue";
import StatePanel from "../components/StatePanel.vue";
import { formatBytes, formatDate, statusLabel } from "../format";
import { zhCN } from "../locales/zh-CN";
import type { CatalogResponse, CatalogState, FileItem, Tag } from "../types";

const route = useRoute();
const router = useRouter();
const message = useMessage();
const state = ref<CatalogState>(parseCatalogState(route.query));
const searchInput = ref(state.value.query);
const result = ref<CatalogResponse>();
const tags = ref<Tag[]>([]);
const loading = ref(true);
const error = ref("");
const previousVersion = ref("");
const versionChanged = ref(false);
const showDefaultPassword = ref(sessionStorage.getItem("dokura-default-password") === "true");
let requestController: AbortController | undefined;
let searchTimer: ReturnType<typeof setTimeout> | undefined;

const breadcrumbs = computed(() => {
  const parts = state.value.path ? state.value.path.split("/") : [];
  return [{ name: zhCN.library, path: "" }, ...parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join("/") }))];
});
const activeFilterCount = computed(() => state.value.tagIds.length + (state.value.ratingMin !== 0 || state.value.ratingMax !== 5 ? 1 : 0));
const directories = computed(() => result.value?.items.filter((item) => item.kind === "directory") ?? []);
const files = computed(() => result.value?.items.filter((item) => item.kind === "file") ?? []);

function dismissDefaultPassword(): void {
  sessionStorage.removeItem("dokura-default-password");
  showDefaultPassword.value = false;
}

async function load(): Promise<void> {
  requestController?.abort();
  requestController = new AbortController();
  loading.value = true;
  error.value = "";
  try {
    const [catalog, tagResult] = await Promise.all([
      api.catalog(state.value, requestController.signal),
      api.tags(state.value.path, state.value.scope, requestController.signal),
    ]);
    if (previousVersion.value && previousVersion.value !== catalog.result_version) versionChanged.value = true;
    previousVersion.value = catalog.result_version;
    result.value = catalog;
    tags.value = tagResult.items.filter((tag) => ["author", "parody", "language"].includes(tag.category));
  } catch (reason) {
    if ((reason as Error).name !== "AbortError") {
      if (reason instanceof ApiError && reason.status === 401) {
        await router.replace({ name: "login", query: { redirect: route.fullPath } });
        return;
      }
      error.value = reason instanceof ApiError ? reason.message : zhCN.connectFailed;
    }
  } finally {
    if (!requestController?.signal.aborted) loading.value = false;
  }
}

function replaceState(patch: Partial<CatalogState>, resetPage = true): void {
  const next = { ...state.value, ...patch };
  if (resetPage && patch.page == null) next.page = 1;
  void router.push({ name: "catalog", query: catalogQuery(next) });
}

function setSearch(value: string): void {
  searchInput.value = value;
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => replaceState({ query: value }, true), 300);
}

function openDirectory(path: string): void {
  replaceState({ path, page: 1 }, false);
}

function toggleTag(id: number): void {
  const selected = state.value.tagIds.includes(id)
    ? state.value.tagIds.filter((value) => value !== id)
    : [...state.value.tagIds, id];
  replaceState({ tagIds: selected });
}

async function updateRating(item: FileItem, rating: number): Promise<void> {
  const previous = item.rating;
  item.rating = rating;
  try {
    const saved = await api.rating(item.id, rating);
    item.rating = saved.rating;
  } catch {
    item.rating = previous;
    message.error(zhCN.saveRatingFailed);
  }
}

function clearFilters(): void {
  replaceState({ tagIds: [], ratingMin: 0, ratingMax: 5 });
}

function setRatingMin(value: number): void {
  replaceState({ ratingMin: value, ratingMax: Math.max(value, state.value.ratingMax) });
}

function setRatingMax(value: number): void {
  replaceState({ ratingMax: value, ratingMin: Math.min(value, state.value.ratingMin) });
}

watch(() => route.query, (query) => {
  const parsed = parseCatalogState(query);
  const canonical = router.resolve({ name: "catalog", query: catalogQuery(parsed) }).fullPath;
  if (canonical !== route.fullPath) {
    void router.replace(canonical);
    return;
  }
  state.value = parsed;
  searchInput.value = state.value.query;
  void load();
}, { deep: true, immediate: true });

onBeforeUnmount(() => {
  requestController?.abort();
  if (searchTimer) clearTimeout(searchTimer);
});
</script>

<template>
  <main class="catalog-page">
    <div v-if="showDefaultPassword" class="security-notice" role="status">
      <span>!</span>{{ zhCN.defaultPassword }}
      <button type="button" :aria-label="zhCN.closeNotice" @click="dismissDefaultPassword">×</button>
    </div>

    <section class="catalog-heading">
      <div>
        <p class="section-index">ARCHIVE / 01</p>
        <h1>{{ state.path ? state.path.split('/').at(-1) : zhCN.library }}</h1>
        <nav class="breadcrumbs" :aria-label="zhCN.breadcrumbLabel">
          <template v-for="(crumb, index) in breadcrumbs" :key="crumb.path">
            <button type="button" :aria-current="index === breadcrumbs.length - 1 ? 'page' : undefined" @click="openDirectory(crumb.path)">{{ crumb.name }}</button>
            <span v-if="index < breadcrumbs.length - 1">/</span>
          </template>
        </nav>
      </div>
      <div class="result-count"><strong>{{ result?.total ?? "—" }}</strong><span>{{ zhCN.itemCount }}</span></div>
    </section>

    <section class="catalog-tools" :aria-label="zhCN.searchAndFilter">
      <label class="search-field">
        <span aria-hidden="true">⌕</span>
        <input :value="searchInput" type="search" :placeholder="zhCN.search" :aria-label="zhCN.search" @input="setSearch(($event.target as HTMLInputElement).value)" />
        <small>300 ms</small>
      </label>
      <label class="tool-field">{{ zhCN.currentDirectory }}
        <select :value="state.scope" @change="replaceState({ scope: ($event.target as HTMLSelectElement).value as CatalogState['scope'] })">
          <option value="current">{{ zhCN.currentDirectory }}</option><option value="recursive">{{ zhCN.recursive }}</option>
        </select>
      </label>
      <label class="tool-field">{{ zhCN.sort }}
        <select :value="state.sort" @change="replaceState({ sort: ($event.target as HTMLSelectElement).value as CatalogState['sort'] })">
          <option value="name">{{ zhCN.name }}</option><option value="size">{{ zhCN.size }}</option><option value="modified">{{ zhCN.modified }}</option><option value="rating">{{ zhCN.rating }}</option>
        </select>
      </label>
      <button class="direction-button" type="button" :aria-label="state.direction === 'asc' ? zhCN.ascending : zhCN.descending" @click="replaceState({ direction: state.direction === 'asc' ? 'desc' : 'asc' })">
        {{ state.direction === "asc" ? "↑" : "↓" }}
      </button>
    </section>

    <section class="filter-strip" :aria-label="zhCN.filterConditions">
      <span class="filter-label">{{ zhCN.filter }} <b>{{ activeFilterCount }}</b></span>
      <div class="tag-options">
        <button v-for="tag in tags" :key="tag.id" type="button" :class="{ selected: state.tagIds.includes(tag.id) }" :aria-pressed="state.tagIds.includes(tag.id)" @click="toggleTag(tag.id)">
          {{ tag.category }}:{{ tag.value }} <small>{{ tag.uses }}</small>
        </button>
      </div>
      <div class="rating-filter">
        <label>{{ zhCN.minimum }} <select :value="state.ratingMin" @change="setRatingMin(Number(($event.target as HTMLSelectElement).value))"><option v-for="n in 6" :key="n - 1" :value="n - 1">{{ n - 1 }}</option></select></label>
        <span>—</span>
        <label>{{ zhCN.maximum }} <select :value="state.ratingMax" @change="setRatingMax(Number(($event.target as HTMLSelectElement).value))"><option v-for="n in 6" :key="n - 1" :value="n - 1">{{ n - 1 }}</option></select></label>
      </div>
      <button v-if="activeFilterCount" class="clear-button" type="button" @click="clearFilters">{{ zhCN.clearFilters }}</button>
    </section>

    <div v-if="versionChanged" class="version-notice" role="status">{{ zhCN.listUpdated }}<button type="button" @click="versionChanged = false; replaceState({ page: 1 }, false)">{{ zhCN.refresh }}</button></div>

    <StatePanel v-if="loading && !result" :title="zhCN.loading" kind="loading" />
    <StatePanel v-else-if="error" :title="zhCN.loadFailed" :message="error" kind="error" :action="zhCN.retry" @action="load" />
    <StatePanel v-else-if="!result?.items.length" :title="activeFilterCount || state.query ? zhCN.emptyFiltered : zhCN.empty" kind="empty" />
    <section v-else class="catalog-list" :aria-busy="loading">
      <button v-for="item in directories" :key="`dir-${item.relative_path}`" class="directory-row" type="button" @click="openDirectory(item.relative_path)">
        <span class="folder-icon" aria-hidden="true"></span><strong>{{ item.name }}</strong><small>{{ item.relative_path }}</small><i>→</i>
      </button>
      <article v-for="item in files" :key="item.id" class="file-row">
        <RouterLink class="file-cover" :to="{ name: 'detail', params: { id: item.id }, query: { from: route.fullPath } }" :aria-label="zhCN.viewFile(item.name)">
          <img v-if="item.cover_status === 'ready'" :src="coverUrl(item.id)" alt="" loading="lazy" /><span v-else>ZIP</span>
        </RouterLink>
        <div class="file-main">
          <div class="file-title-line"><RouterLink :to="{ name: 'detail', params: { id: item.id }, query: { from: route.fullPath } }">{{ item.name }}</RouterLink><span class="status-badge" :data-status="item.status">{{ statusLabel(item.status) }}</span></div>
          <p>{{ item.display_path }}</p>
          <div class="file-tags"><span v-for="tag in item.tags" :key="tag.id">{{ tag.category }}:{{ tag.value }}</span><span v-if="!item.tags.length">{{ zhCN.unrecognized }}</span></div>
        </div>
        <div class="file-facts"><span>{{ formatBytes(item.size) }}</span><span>{{ formatDate(item.modified_ns) }}</span></div>
        <RatingPicker :model-value="item.rating" @update:model-value="updateRating(item, $event)" />
        <RouterLink class="row-arrow" :to="{ name: 'detail', params: { id: item.id }, query: { from: route.fullPath } }" :aria-label="zhCN.viewDetails">→</RouterLink>
      </article>
    </section>

    <nav v-if="result && result.pages > 1" class="pagination" :aria-label="zhCN.paginationLabel">
      <button type="button" :disabled="state.page <= 1" @click="replaceState({ page: state.page - 1 }, false)">{{ zhCN.previousPage }}</button>
      <span><strong>{{ state.page }}</strong> / {{ result.pages }}</span>
      <button type="button" :disabled="state.page >= result.pages" @click="replaceState({ page: state.page + 1 }, false)">{{ zhCN.nextPage }}</button>
      <label>{{ zhCN.perPage }} <select :value="state.perPage" @change="replaceState({ perPage: Number(($event.target as HTMLSelectElement).value) })"><option :value="25">25</option><option :value="50">50</option><option :value="100">100</option></select></label>
    </nav>
  </main>
</template>

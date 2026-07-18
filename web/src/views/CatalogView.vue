<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { NSelect, useMessage, type SelectOption } from "naive-ui";
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
const selected = ref(new Set<string>());
const snapshot = ref<{ id: string; count: number }>();
const managing = ref(false);
let requestController: AbortController | undefined;
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let loadedTagScope = "";

const breadcrumbs = computed(() => {
  const parts = state.value.path ? state.value.path.split("/") : [];
  return [{ name: zhCN.library, path: "" }, ...parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join("/") }))];
});
const activeFilterCount = computed(() => state.value.tagIds.length + (state.value.ratingMin !== 0 || state.value.ratingMax !== 5 ? 1 : 0));
const directories = computed(() => result.value?.items.filter((item) => item.kind === "directory") ?? []);
const files = computed(() => result.value?.items.filter((item) => item.kind === "file") ?? []);
const allPageSelected = computed(() => files.value.length > 0 && files.value.every((item) => selected.value.has(item.id)));
const selectedCount = computed(() => snapshot.value?.count ?? selected.value.size);
const tagOptions = computed<Record<"source" | "artist" | "language", SelectOption[]>>(() => ({
  source: optionsFor("source"),
  artist: optionsFor("artist"),
  language: optionsFor("language"),
}));
const selectedTagIds = computed<Record<"source" | "artist" | "language", number[]>>(() => ({
  source: selectedFor("source"),
  artist: selectedFor("artist"),
  language: selectedFor("language"),
}));

function optionsFor(category: string): SelectOption[] {
  return tags.value
    .filter((tag) => tag.category === category)
    .map((tag) => ({ label: tag.uses == null ? tag.value : `${tag.value} (${tag.uses})`, value: tag.id }));
}

function selectedFor(category: string): number[] {
  const ids = new Set(tags.value.filter((tag) => tag.category === category).map((tag) => tag.id));
  return state.value.tagIds.filter((id) => ids.has(id));
}

function filterTagOption(pattern: string, option: SelectOption): boolean {
  return String(option.label ?? "").toLocaleLowerCase().includes(pattern.toLocaleLowerCase());
}

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
    const tagScope = `${state.value.path}\u0000${state.value.scope}`;
    const tagRequest = loadedTagScope === tagScope
      ? Promise.resolve({ items: tags.value })
      : api.tags(state.value.path, state.value.scope, requestController.signal);
    const [catalog, tagResult] = await Promise.all([
      api.catalog(state.value, requestController.signal),
      tagRequest,
    ]);
    if (previousVersion.value && previousVersion.value !== catalog.result_version) versionChanged.value = true;
    previousVersion.value = catalog.result_version;
    result.value = catalog;
    tags.value = tagResult.items;
    loadedTagScope = tagScope;
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

function setTagCategory(category: string, values: Array<string | number>): void {
  const categoryIds = new Set(tags.value.filter((tag) => tag.category === category).map((tag) => tag.id));
  const otherIds = state.value.tagIds.filter((id) => !categoryIds.has(id));
  const selected = values.map(Number).filter((id) => Number.isInteger(id) && id > 0);
  replaceState({ tagIds: [...new Set([...otherIds, ...selected])] });
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

function toggleFile(id: string): void {
  const next = new Set(selected.value);
  next.has(id) ? next.delete(id) : next.add(id);
  selected.value = next;
}

function togglePage(): void {
  const next = new Set(selected.value);
  for (const item of files.value) allPageSelected.value ? next.delete(item.id) : next.add(item.id);
  selected.value = next;
}

async function selectAllResults(): Promise<void> {
  managing.value = true;
  try {
    const result = await api.selection(state.value);
    snapshot.value = { id: result.id, count: result.count };
    selected.value = new Set();
  } catch (reason) { message.error(reason instanceof ApiError ? reason.message : zhCN.requestFailed); }
  finally { managing.value = false; }
}

async function clearSelection(): Promise<void> {
  if (snapshot.value) await api.clearSelection();
  snapshot.value = undefined;
  selected.value = new Set();
}

async function moveSelected(): Promise<void> {
  const target = prompt("请输入 Content 内已有的目标文件夹相对路径；根目录留空。", state.value.path);
  if (target == null) return;
  managing.value = true;
  try {
    const result = snapshot.value ? await api.moveSelection(target) : await api.moveFiles([...selected.value], target);
    message.success(`移动成功 ${result.success_count} 项，失败 ${result.failure_count} 项`);
    if (result.failed.length) message.warning(result.failed.map((item) => item.reason).join("；"));
    await clearSelection(); await load();
  } catch (reason) { message.error(reason instanceof ApiError ? reason.message : zhCN.requestFailed); }
  finally { managing.value = false; }
}

async function deleteSelected(): Promise<void> {
  if (!snapshot.value) { message.warning("批量永久删除前请先选择全部筛选结果，确保服务端建立选择快照。"); return; }
  managing.value = true;
  try {
    let preview = await api.deletePreview();
    if (!confirm(`将永久删除 ${preview.file_count} 个 ZIP，共 ${formatBytes(preview.total_bytes)}。此操作无法撤销，是否继续？`)) return;
    let result = await api.deleteSelection(preview.snapshot_id, preview.file_count, preview.total_bytes);
    if (result.reconfirmation_required) {
      if (!confirm(`选择统计已变化：现在为 ${result.file_count} 个 ZIP，共 ${formatBytes(result.total_bytes ?? 0)}。请重新确认永久删除。`)) return;
      result = await api.deleteSelection(result.snapshot_id ?? preview.snapshot_id, result.file_count ?? 0, result.total_bytes ?? 0);
    }
    message.success(`永久删除成功 ${result.success_count} 项，失败 ${result.failure_count} 项`);
    await clearSelection(); await load();
  } catch (reason) { message.error(reason instanceof ApiError ? reason.message : zhCN.requestFailed); }
  finally { managing.value = false; }
}

async function createFolder(): Promise<void> {
  const name = prompt("新文件夹名称");
  if (!name) return;
  try { await api.createDirectory(state.value.path, name); message.success("文件夹已创建"); await load(); }
  catch (reason) { message.error(reason instanceof ApiError ? reason.message : zhCN.requestFailed); }
}

async function renameFolder(path: string, currentName: string): Promise<void> {
  const name = prompt("新的文件夹名称", currentName);
  if (!name || name === currentName) return;
  try { await api.renameDirectory(path, name); message.success("文件夹已重命名"); await load(); }
  catch (reason) { message.error(reason instanceof ApiError ? reason.message : zhCN.requestFailed); }
}

async function moveFolder(path: string): Promise<void> {
  const target = prompt("目标文件夹相对路径；根目录留空。", state.value.path);
  if (target == null) return;
  try { await api.moveDirectory(path, target); message.success("文件夹已移动"); await load(); }
  catch (reason) { message.error(reason instanceof ApiError ? reason.message : zhCN.requestFailed); }
}

async function deleteFolder(path: string): Promise<void> {
  if (!confirm("仅实际为空的文件夹可以删除。是否继续？")) return;
  try { await api.deleteDirectory(path); message.success("空文件夹已删除"); await load(); }
  catch (reason) { message.error(reason instanceof ApiError ? reason.message : zhCN.requestFailed); }
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

onMounted(async () => {
  try {
    const restored = await api.selectionStatus();
    if (restored.active && restored.id) snapshot.value = { id: restored.id, count: restored.count };
  } catch { /* Session handling remains owned by App.vue. */ }
});

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
      <div class="tag-selects">
        <label class="tag-select-field"><span>来源</span>
          <NSelect :value="selectedTagIds.source" :options="tagOptions.source" multiple filterable clearable :filter="filterTagOption" :max-tag-count="1" placeholder="选择来源" @update:value="setTagCategory('source', $event)" />
        </label>
        <label class="tag-select-field"><span>作者</span>
          <NSelect :value="selectedTagIds.artist" :options="tagOptions.artist" multiple filterable clearable :filter="filterTagOption" :max-tag-count="1" placeholder="选择作者" @update:value="setTagCategory('artist', $event)" />
        </label>
        <label class="tag-select-field"><span>语言</span>
          <NSelect :value="selectedTagIds.language" :options="tagOptions.language" multiple filterable clearable :filter="filterTagOption" :max-tag-count="1" placeholder="选择语言" @update:value="setTagCategory('language', $event)" />
        </label>
      </div>
      <div class="rating-filter">
        <label>{{ zhCN.minimum }} <select :value="state.ratingMin" @change="setRatingMin(Number(($event.target as HTMLSelectElement).value))"><option v-for="n in 6" :key="n - 1" :value="n - 1">{{ n - 1 }}</option></select></label>
        <span>—</span>
        <label>{{ zhCN.maximum }} <select :value="state.ratingMax" @change="setRatingMax(Number(($event.target as HTMLSelectElement).value))"><option v-for="n in 6" :key="n - 1" :value="n - 1">{{ n - 1 }}</option></select></label>
      </div>
      <button v-if="activeFilterCount" class="clear-button" type="button" @click="clearFilters">{{ zhCN.clearFilters }}</button>
      <button class="clear-button folder-create" type="button" @click="createFolder">＋ {{ zhCN.createFolder }}</button>
    </section>

    <div v-if="versionChanged" class="version-notice" role="status">{{ zhCN.listUpdated }}<button type="button" @click="versionChanged = false; replaceState({ page: 1 }, false)">{{ zhCN.refresh }}</button></div>

    <StatePanel v-if="loading && !result" :title="zhCN.loading" kind="loading" />
    <StatePanel v-else-if="error" :title="zhCN.loadFailed" :message="error" kind="error" :action="zhCN.retry" @action="load" />
    <StatePanel v-else-if="!result?.items.length" :title="activeFilterCount || state.query ? zhCN.emptyFiltered : zhCN.empty" kind="empty" />
    <section v-else class="catalog-list" :aria-busy="loading">
      <div v-if="files.length" class="selection-row"><label><input type="checkbox" :checked="allPageSelected" @change="togglePage" /> {{ zhCN.selectPage }}</label><button type="button" @click="selectAllResults">{{ zhCN.selectAllResults }} {{ result?.total }}</button></div>
      <div v-for="item in directories" :key="`dir-${item.relative_path}`" class="directory-row">
        <button class="directory-open" type="button" @click="openDirectory(item.relative_path)"><span class="folder-icon" aria-hidden="true"></span><strong>{{ item.name }}</strong></button>
        <div class="row-management"><button type="button" @click="renameFolder(item.relative_path, item.name)">{{ zhCN.rename }}</button><button type="button" @click="moveFolder(item.relative_path)">{{ zhCN.move }}</button><button class="danger-link" type="button" @click="deleteFolder(item.relative_path)">{{ zhCN.permanentDelete }}</button><i>→</i></div>
      </div>
      <article v-for="item in files" :key="item.id" class="file-row">
        <label class="row-check"><input type="checkbox" :checked="selected.has(item.id)" :aria-label="`${zhCN.select} ${item.name}`" @change="toggleFile(item.id)" /></label>
        <RouterLink class="file-cover" :to="{ name: 'detail', params: { id: item.id }, query: { from: route.fullPath } }" :aria-label="zhCN.viewFile(item.name)">
          <img v-if="item.cover_status === 'complete'" :src="coverUrl(item.id)" alt="" loading="lazy" /><span v-else>ZIP</span>
        </RouterLink>
        <div class="file-main">
          <div class="file-title-line"><RouterLink :to="{ name: 'detail', params: { id: item.id }, query: { from: route.fullPath } }">{{ item.name }}</RouterLink><span class="status-badge" :data-status="item.status">{{ statusLabel(item.status) }}</span></div>
          <div class="file-tags"><span v-for="tag in item.tags" :key="tag.id">{{ tag.category }}:{{ tag.value }}</span><span v-if="!item.tags.length">{{ zhCN.unrecognized }}</span></div>
        </div>
        <div class="file-facts"><span>{{ formatBytes(item.size) }}</span><span>{{ formatDate(item.modified_ns) }}</span></div>
        <RatingPicker :model-value="item.rating" @update:model-value="updateRating(item, $event)" />
        <RouterLink class="row-arrow" :to="{ name: 'detail', params: { id: item.id }, query: { from: route.fullPath } }" :aria-label="zhCN.viewDetails">→</RouterLink>
      </article>
    </section>

    <aside v-if="selectedCount" class="batch-bar" aria-live="polite"><div><strong>{{ selectedCount }}</strong><span>{{ snapshot ? '个快照项目' : '个当前选择' }}</span></div><p v-if="snapshot">选择快照可跨分页恢复，30 分钟无操作后过期。</p><button type="button" :disabled="managing" @click="moveSelected">{{ zhCN.move }}</button><button class="danger-button" type="button" :disabled="managing" @click="deleteSelected">{{ zhCN.permanentDelete }}</button><button class="batch-close" type="button" :aria-label="zhCN.cancelSelection" @click="clearSelection">×</button></aside>

    <nav v-if="result && result.pages > 1" class="pagination" :aria-label="zhCN.paginationLabel">
      <button type="button" :disabled="state.page <= 1" @click="replaceState({ page: state.page - 1 }, false)">{{ zhCN.previousPage }}</button>
      <span><strong>{{ state.page }}</strong> / {{ result.pages }}</span>
      <button type="button" :disabled="state.page >= result.pages" @click="replaceState({ page: state.page + 1 }, false)">{{ zhCN.nextPage }}</button>
      <label>{{ zhCN.perPage }} <select :value="state.perPage" @change="replaceState({ perPage: Number(($event.target as HTMLSelectElement).value) })"><option :value="25">25</option><option :value="50">50</option><option :value="100">100</option></select></label>
    </nav>
  </main>
</template>

package com.dokura.app

import android.app.Application
import android.net.ConnectivityManager
import android.net.Network
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.dokura.app.data.AppSettings
import com.dokura.app.data.CatalogItemDto
import com.dokura.app.data.CatalogQuery
import com.dokura.app.data.ConnectionSettings
import com.dokura.app.data.CredentialStore
import com.dokura.app.data.DokuraDatabase
import com.dokura.app.data.FileDetailDto
import com.dokura.app.data.RatingBody
import com.dokura.app.data.ReadingProgress
import com.dokura.app.data.SettingsStore
import com.dokura.app.data.ThemeMode
import com.dokura.app.data.ReadingDirection
import com.dokura.app.cache.ClearCacheResult
import com.dokura.app.cache.ImageCache
import com.dokura.app.reader.ReaderController
import com.dokura.app.data.TagCandidateDto
import com.dokura.app.network.ConnectionTestResult
import com.dokura.app.network.NetworkClient
import com.dokura.app.network.retryRead
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import retrofit2.HttpException

data class CatalogUiState(
    val query: CatalogQuery = CatalogQuery(),
    val items: List<CatalogItemDto> = emptyList(),
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val page: Int = 0,
    val pages: Int = 1,
    val resultVersion: String? = null,
    val listChanged: Boolean = false,
    val error: String? = null,
)

data class DetailUiState(
    val loading: Boolean = false,
    val item: FileDetailDto? = null,
    val error: String? = null,
    val savingRating: Boolean = false,
    val startPage: Int = 1,
)

data class DirectorySnapshot(val state: CatalogUiState, val firstVisibleItem: Int)

class DokuraViewModel(application: Application) : AndroidViewModel(application) {
    private val settingsStore = SettingsStore(application)
    private val credentials = CredentialStore(application)
    private val database = DokuraDatabase.create(application)
    private val progressDao = database.readingProgress()
    val imageCache = ImageCache(
        application,
        database.cache(),
        limitBytes = { settings.value.cacheLimitGb * 1024L * 1024L * 1024L },
    )
    private val connectivity = application.getSystemService(ConnectivityManager::class.java)
    private val _catalog = MutableStateFlow(CatalogUiState())
    private val _detail = MutableStateFlow(DetailUiState())
    private val _connectionTest = MutableStateFlow<ConnectionTestResult?>(null)
    private val _tags = MutableStateFlow<List<TagCandidateDto>>(emptyList())
    private val directoryStack = ArrayDeque<DirectorySnapshot>()
    private var catalogJob: Job? = null
    private var searchJob: Job? = null
    private var detailJob: Job? = null
    private var currentDetailId: String? = null
    private var catalogVisible = false
    private var detailVisible = false
    private var searchVersion = 0L

    val settings: StateFlow<AppSettings> = settingsStore.settings.stateIn(
        viewModelScope,
        SharingStarted.Eagerly,
        AppSettings(),
    )
    val recent: StateFlow<List<ReadingProgress>> = progressDao.recent().stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        emptyList(),
    )
    val catalog = _catalog.asStateFlow()
    val detail = _detail.asStateFlow()
    val connectionTest = _connectionTest.asStateFlow()
    val tags = _tags.asStateFlow()
    val cacheBytes = imageCache.totalBytes.stateIn(viewModelScope, SharingStarted.Eagerly, 0L)
    val reader = ReaderController(application, viewModelScope, progressDao, imageCache, ::imageUrl, ::imageHeaders)
    val readerState = reader.state
    val apiKeyConfigured: Boolean get() = credentials.readApiKey().isNotBlank()

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            if (catalogVisible && _catalog.value.error != null) loadCatalog(reset = true)
            if (detailVisible && _detail.value.error != null) currentDetailId?.let(::loadDetail)
        }
    }

    init {
        connectivity.registerDefaultNetworkCallback(networkCallback)
        viewModelScope.launch { imageCache.reconcile() }
    }

    override fun onCleared() {
        reader.stop()
        connectivity.unregisterNetworkCallback(networkCallback)
        super.onCleared()
    }

    fun saveConnection(settings: ConnectionSettings, apiKey: String) = viewModelScope.launch {
        settingsStore.saveConnection(settings)
        if (apiKey.isNotBlank()) credentials.saveApiKey(apiKey)
        _connectionTest.value = null
    }

    fun testConnection(settings: ConnectionSettings, apiKey: String) = viewModelScope.launch {
        _connectionTest.value = null
        _connectionTest.value = NetworkClient.test(settings, apiKey.ifBlank(credentials::readApiKey))
    }

    fun clearConnectionResult() { _connectionTest.value = null }
    fun setTheme(value: ThemeMode) = viewModelScope.launch { settingsStore.setTheme(value) }
    fun setPreviewColumns(value: Int) = viewModelScope.launch { settingsStore.setColumns(value) }
    fun setCoverWidth(value: Int) = viewModelScope.launch { settingsStore.setCoverWidth(value) }
    fun setReadingDirection(value: ReadingDirection) = viewModelScope.launch { settingsStore.setReadingDirection(value) }
    fun setKeepScreenOn(value: Boolean) = viewModelScope.launch { settingsStore.setKeepScreenOn(value) }
    fun setCacheLimitGb(value: Int) = viewModelScope.launch {
        settingsStore.setCacheLimitGb(value)
        imageCache.enforceLimit(value * 1024L * 1024L * 1024L)
    }
    fun clearImageCache(onComplete: (ClearCacheResult) -> Unit) = viewModelScope.launch {
        reader.prepareCacheClear()
        onComplete(imageCache.clear())
    }

    fun loadCatalog(reset: Boolean = false) {
        val current = _catalog.value
        if (!reset && (current.loading || current.loadingMore || current.page >= current.pages)) return
        catalogJob?.cancel()
        val requestedVersion = ++searchVersion
        val nextPage = if (reset) 1 else current.page + 1
        catalogJob = viewModelScope.launch {
            _catalog.value = if (reset) current.copy(loading = true, loadingMore = false, error = null) else current.copy(loadingMore = true, error = null)
            val response = runCatching {
                val query = _catalog.value.query
                retryRead {
                    requireApi().catalog(
                        query.path, nextPage, 40, query.search,
                        if (query.recursive) "recursive" else "current",
                        query.tagIds, query.tagMode,
                        query.ratingMin, query.ratingMax, query.sort, query.direction,
                    )
                }
            }
            if (requestedVersion != searchVersion) return@launch
            response.onSuccess { page ->
                val old = if (reset) emptyList() else _catalog.value.items
                val merged = mergeCatalogItems(old, page.items)
                val oldVersion = if (reset) null else _catalog.value.resultVersion
                _catalog.value = _catalog.value.copy(
                    items = merged,
                    loading = false,
                    loadingMore = false,
                    page = page.page,
                    pages = page.pages.coerceAtLeast(1),
                    resultVersion = page.resultVersion,
                    listChanged = _catalog.value.listChanged || (oldVersion != null && oldVersion != page.resultVersion),
                )
            }.onFailure { error ->
                _catalog.value = _catalog.value.copy(
                    loading = false,
                    loadingMore = false,
                    error = userMessage(error),
                )
            }
        }
    }

    fun search(value: String) {
        searchJob?.cancel()
        catalogJob?.cancel()
        val requestedVersion = ++searchVersion
        _catalog.value = _catalog.value.copy(query = _catalog.value.query.copy(search = value))
        searchJob = viewModelScope.launch {
            delay(300)
            if (requestedVersion == searchVersion) loadCatalog(reset = true)
        }
    }

    fun catalogVisible() { catalogVisible = true }
    fun catalogHidden() {
        catalogVisible = false
        catalogJob?.cancel()
        searchJob?.cancel()
    }

    fun loadTags() = viewModelScope.launch {
        val query = _catalog.value.query
        runCatching { retryRead { requireApi().tags(query.path, if (query.recursive) "recursive" else "current") } }
            .onSuccess { _tags.value = it.items }
    }

    fun applyFilters(
        ratingMin: Int,
        ratingMax: Int,
        sort: String,
        direction: String,
        recursive: Boolean,
        tagIds: List<Long>,
        tagMode: String,
    ) {
        _catalog.value = _catalog.value.copy(
            query = _catalog.value.query.copy(
                ratingMin = ratingMin,
                ratingMax = ratingMax,
                sort = sort,
                direction = direction,
                recursive = recursive,
                tagIds = tagIds,
                tagMode = tagMode,
            ),
        )
        loadCatalog(reset = true)
    }

    fun enterDirectory(path: String, firstVisibleItem: Int) {
        directoryStack.addLast(DirectorySnapshot(_catalog.value, firstVisibleItem))
        _catalog.value = CatalogUiState(query = _catalog.value.query.copy(path = path))
        loadCatalog(reset = true)
    }

    fun leaveDirectory(): Int? {
        val snapshot = directoryStack.removeLastOrNull() ?: return null
        catalogJob?.cancel()
        searchVersion++
        _catalog.value = snapshot.state
        return snapshot.firstVisibleItem
    }

    fun navigateBreadcrumb(path: String) {
        while (directoryStack.isNotEmpty() && _catalog.value.query.path != path) {
            val snapshot = directoryStack.removeLast()
            _catalog.value = snapshot.state
        }
        if (_catalog.value.query.path != path) {
            directoryStack.clear()
            _catalog.value = CatalogUiState(query = _catalog.value.query.copy(path = path))
            loadCatalog(reset = true)
        }
    }

    fun loadDetail(id: String) {
        currentDetailId = id
        detailJob?.cancel()
        detailJob = viewModelScope.launch {
            _detail.value = DetailUiState(loading = true)
            runCatching { retryRead { requireApi().detail(id) } }
                .onSuccess { item ->
                    val saved = progressDao.get(id)?.page?.coerceIn(1, item.pageCount.coerceAtLeast(1)) ?: 1
                    _detail.value = DetailUiState(item = item, startPage = saved)
                }
                .onFailure { error ->
                    if (shouldDeleteLocalState(error)) progressDao.delete(id)
                    _detail.value = DetailUiState(error = userMessage(error))
                }
        }
    }

    fun closeDetail() {
        detailVisible = false
        detailJob?.cancel()
        _detail.value = DetailUiState()
    }

    fun detailVisible() { detailVisible = true }

    fun startReader(page: Int) {
        _detail.value.item?.let { reader.start(it, page) }
    }

    fun stopReader() = reader.stop()
    fun appBackgrounded() {
        reader.onBackground()
        viewModelScope.launch { imageCache.flushAccesses() }
    }
    fun onMemoryPressure() = reader.onMemoryPressure()

    fun setRating(value: Int) {
        val item = _detail.value.item ?: return
        val previous = item.rating
        _detail.value = _detail.value.copy(item = item.copy(rating = value), savingRating = true, error = null)
        viewModelScope.launch {
            runCatching { retryRead { requireApi().setRating(item.id, RatingBody(value)) } }
                .onSuccess { result ->
                    _detail.value = _detail.value.copy(
                        item = _detail.value.item?.copy(rating = result.rating),
                        savingRating = false,
                    )
                }.onFailure { error ->
                    _detail.value = _detail.value.copy(
                        item = _detail.value.item?.copy(rating = previous),
                        savingRating = false,
                        error = "评分保存失败：${userMessage(error)}",
                    )
                }
        }
    }

    fun imageUrl(path: String): String? = NetworkClient.baseUrl(settings.value.connection)?.plus(path)
    fun imageHeaders(): Map<String, String> = credentials.readApiKey().takeIf { it.isNotBlank() }
        ?.let { mapOf("Authorization" to "Bearer $it", "X-Dokura-Client-ID" to "android") }
        ?: emptyMap()

    private fun requireApi() = NetworkClient.api(settings.value.connection, credentials::readApiKey)
        ?: throw IllegalArgumentException("请先配置有效的服务端地址")

    private fun userMessage(error: Throwable): String = when (error) {
        is HttpException -> when (error.code()) {
            401, 403 -> "APIkey 无效，请在设置中更新"
            404 -> "文件不存在"
            else -> "服务端返回错误（${error.code()}）"
        }
        is java.io.IOException -> "无法连接服务端"
        is IllegalArgumentException -> error.message ?: "连接设置无效"
        else -> "请求失败，请重试"
    }
}

internal fun mergeCatalogItems(
    current: List<CatalogItemDto>,
    incoming: List<CatalogItemDto>,
): List<CatalogItemDto> {
    val seen = current.mapTo(mutableSetOf()) { it.id ?: "directory:${it.relativePath}" }
    return current + incoming.filter { seen.add(it.id ?: "directory:${it.relativePath}") }
}

internal fun shouldDeleteLocalState(error: Throwable): Boolean = error is HttpException && error.code() == 404

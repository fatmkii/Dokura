package com.dokura.app.reader

import android.app.ActivityManager
import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Rect
import com.dokura.app.cache.ImageCache
import com.dokura.app.data.CacheCategory
import com.dokura.app.data.FileDetailDto
import com.dokura.app.data.ReadingProgress
import com.dokura.app.data.ReadingProgressDao
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class ReaderUiState(
    val item: FileDetailDto? = null,
    val page: Int = 1,
    val pendingPage: Int? = null,
    val bitmap: Bitmap? = null,
    val regionBitmap: Bitmap? = null,
    val loading: Boolean = false,
    val unavailable: Boolean = false,
    val error: String? = null,
    val controlsVisible: Boolean = true,
    val sessionId: Long = 0,
)

class ReaderController(
    application: Application,
    private val scope: CoroutineScope,
    private val progress: ReadingProgressDao,
    private val cache: ImageCache,
    private val imageUrl: (String) -> String?,
    private val headers: () -> Map<String, String>,
) {
    private val _state = MutableStateFlow(ReaderUiState())
    val state = _state.asStateFlow()
    private val downloader = ReaderDownloader(cache)
    private val activityManager = application.getSystemService(ActivityManager::class.java)
    private val decoder = ReaderImageDecoder(ReaderPolicies.bitmapBudget(activityManager.memoryClass, activityManager.isLowRamDevice) / 2)
    private var loadJob: Job? = null
    private var regionJob: Job? = null
    private var stableJob: Job? = null
    private var prefetch: PrefetchQueue? = null
    private var lastDisplayedPage: Int? = null
    private var lastRecentWrite = 0L
    private var currentFile: java.io.File? = null

    fun start(item: FileDetailDto, requestedPage: Int) {
        val page = requestedPage.coerceIn(1, item.pageCount.coerceAtLeast(1))
        prefetch = PrefetchQueue(
            scope, cache, downloader,
            url = { number -> imageUrl("api/v1/files/${item.id}/pages/$number/original?purpose=prefetch") },
            headers = headers,
        )
        lastRecentWrite = 0L
        _state.value = ReaderUiState(item = item, page = page, sessionId = System.nanoTime())
        load(page)
    }

    fun goTo(page: Int) {
        val item = _state.value.item ?: return
        val target = page.coerceIn(1, item.pageCount)
        if (target == _state.value.page && (_state.value.bitmap != null || _state.value.unavailable)) return
        load(target)
    }

    fun retry() = load(_state.value.pendingPage ?: _state.value.page)
    fun toggleControls() { _state.value = _state.value.copy(controlsVisible = !_state.value.controlsVisible) }

    private fun load(page: Int) {
        val item = _state.value.item ?: return
        val previous = _state.value
        val preserveCurrent = page != previous.page && (previous.bitmap != null || previous.unavailable)
        scope.launch { cache.protect("reader-current", emptySet()) }
        loadJob?.cancel()
        regionJob?.cancel()
        if (!preserveCurrent) stableJob?.cancel()
        if (preserveCurrent) {
            _state.value = previous.copy(pendingPage = page, loading = true, error = null)
        } else {
            currentFile = null
            previous.bitmap?.recycle()
            previous.regionBitmap?.recycle()
            _state.value = previous.copy(page = page, pendingPage = null, bitmap = null, regionBitmap = null, unavailable = false, loading = true, error = null)
        }
        val unavailable = item.pages.firstOrNull { it.number == page }?.unavailable == true
        if (unavailable) {
            if (preserveCurrent) {
                previous.bitmap?.recycle()
                previous.regionBitmap?.recycle()
            }
            _state.value = _state.value.copy(page = page, pendingPage = null, bitmap = null, regionBitmap = null, loading = false, unavailable = true)
            displayed(page)
            scope.launch { prefetch?.update(item, page) }
            return
        }
        loadJob = scope.launch {
            val key = ImageCache.key(CacheCategory.ORIGINAL, item.id, page)
            cache.protect("reader-current", setOf(key))
            runCatching {
                val url = requireNotNull(imageUrl("api/v1/files/${item.id}/pages/$page/original?purpose=current"))
                val downloaded = downloader.download(key, url, headers(), item.contentVersion, "current", retry = true)
                val bitmap = withContext(Dispatchers.Default) { decoder.decodeFit(downloaded.file, 2048, 2048) }
                val regionFile = downloaded.file.takeUnless { downloaded.temporary }
                if (downloaded.temporary) downloaded.file.delete()
                regionFile to bitmap
            }.onSuccess { (file, bitmap) ->
                if (_state.value.page == page || _state.value.pendingPage == page) {
                    if (_state.value.pendingPage == page) {
                        _state.value.bitmap?.recycle()
                        _state.value.regionBitmap?.recycle()
                    }
                    currentFile = file
                    _state.value = _state.value.copy(page = page, pendingPage = null, bitmap = bitmap, regionBitmap = null, unavailable = false, loading = false)
                    displayed(page)
                    prefetch?.update(item, page)
                } else bitmap.recycle()
            }.onFailure { error ->
                if (_state.value.page == page || _state.value.pendingPage == page) {
                    _state.value = _state.value.copy(loading = false, error = if (error is IOException) "无法连接服务端或图片读取失败" else "图片读取失败")
                }
            }
        }
    }

    fun showViewport(zoom: Float, centerX: Float, centerY: Float, targetWidth: Int, targetHeight: Int) {
        if (zoom <= 1.01f) {
            regionJob?.cancel()
            _state.value.regionBitmap?.recycle()
            _state.value = _state.value.copy(regionBitmap = null)
            return
        }
        val file = currentFile ?: return
        val page = _state.value.page
        regionJob?.cancel()
        regionJob = scope.launch {
            runCatching {
                withContext(Dispatchers.Default) {
                    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    BitmapFactory.decodeFile(file.path, bounds)
                    require(bounds.outWidth > 0 && bounds.outHeight > 0)
                    val targetRatio = targetWidth.toFloat() / targetHeight.coerceAtLeast(1)
                    var regionWidth = (bounds.outWidth / zoom).toInt().coerceAtLeast(1)
                    var regionHeight = (bounds.outHeight / zoom).toInt().coerceAtLeast(1)
                    if (regionWidth.toFloat() / regionHeight > targetRatio) regionWidth = (regionHeight * targetRatio).toInt()
                    else regionHeight = (regionWidth / targetRatio).toInt()
                    regionWidth = regionWidth.coerceIn(1, bounds.outWidth)
                    regionHeight = regionHeight.coerceIn(1, bounds.outHeight)
                    val left = (centerX.coerceIn(0f, 1f) * bounds.outWidth - regionWidth / 2).toInt().coerceIn(0, bounds.outWidth - regionWidth)
                    val top = (centerY.coerceIn(0f, 1f) * bounds.outHeight - regionHeight / 2).toInt().coerceIn(0, bounds.outHeight - regionHeight)
                    decoder.decodeRegion(file, Rect(left, top, left + regionWidth, top + regionHeight))
                }
            }.onSuccess { region ->
                if (_state.value.page == page) {
                    _state.value.regionBitmap?.recycle()
                    _state.value = _state.value.copy(regionBitmap = region)
                } else region.recycle()
            }
        }
    }

    private fun displayed(page: Int) {
        lastDisplayedPage = page
        stableJob?.cancel()
        stableJob = scope.launch {
            delay(ProgressPolicy.STABLE_DISPLAY_MS)
            val item = _state.value.item
            if (item != null && _state.value.page == page && (_state.value.bitmap != null || _state.value.unavailable)) save(item, page, exiting = false)
        }
    }

    private suspend fun save(item: FileDetailDto, page: Int, exiting: Boolean) {
        val existing = progress.get(item.id)
        val now = System.currentTimeMillis()
        val updateRecent = ProgressPolicy.shouldUpdateRecent(existing != null, lastRecentWrite, now, exiting)
        runCatching {
            progress.upsert(
                ReadingProgress(
                    fileId = item.id,
                    page = page,
                    lastReadAt = if (updateRecent) now else existing?.lastReadAt ?: now,
                    fileName = item.name,
                    relativePath = item.relativePath,
                    progressUpdatedAt = now,
                ),
            )
            if (updateRecent) {
                lastRecentWrite = now
                progress.trimRecent()
            }
        }
    }

    fun stop() {
        val displayed = lastDisplayedPage
        val item = _state.value.item
        val queue = prefetch
        loadJob?.cancel()
        regionJob?.cancel()
        stableJob?.cancel()
        scope.launch {
            queue?.stop()
            cache.protect("reader-current", emptySet())
            if (displayed != null && item != null) save(item, displayed, exiting = true)
        }
        prefetch = null
        _state.value.bitmap?.recycle()
        _state.value.regionBitmap?.recycle()
        _state.value = ReaderUiState()
        lastDisplayedPage = null
    }

    fun onBackground() {
        val item = _state.value.item ?: return
        lastDisplayedPage?.let { page -> scope.launch { save(item, page, exiting = true) } }
    }

    fun onMemoryPressure() {
        regionJob?.cancel()
        _state.value.regionBitmap?.recycle()
        _state.value = _state.value.copy(regionBitmap = null)
        scope.launch { prefetch?.stop() }
    }

    suspend fun prepareCacheClear() {
        prefetch?.stop()
    }
}

package com.dokura.app.reader

import com.dokura.app.cache.ImageCache
import com.dokura.app.data.CacheCategory
import com.dokura.app.data.FileDetailDto
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

class PrefetchQueue(
    private val scope: CoroutineScope,
    private val cache: ImageCache,
    private val downloader: ReaderDownloader,
    private val url: (Int) -> String?,
    private val headers: () -> Map<String, String>,
) {
    private val jobs = mutableMapOf<Int, Job>()
    private val failed = mutableSetOf<Int>()
    private var generation = 0

    suspend fun update(item: FileDetailDto, current: Int) {
        generation++
        val thisGeneration = generation
        val unavailable = item.pages.filter { it.unavailable }.mapTo(mutableSetOf()) { it.number }
        failed.remove(current)
        val wanted = ReaderPolicies.prefetchPages(current, item.pageCount, unavailable).filterNot { it in failed }
        jobs.filterKeys { it !in wanted }.values.forEach(Job::cancel)
        jobs.keys.retainAll(wanted.toSet())
        val currentKey = ImageCache.key(CacheCategory.ORIGINAL, item.id, current)
        val queuedKeys = wanted.mapTo(mutableSetOf()) { ImageCache.key(CacheCategory.ORIGINAL, item.id, it) }
        queuedKeys += currentKey
        cache.protect("reader-prefetch", queuedKeys)
        wanted.forEach { page ->
            if (jobs.size >= MAX_PREFETCH_REQUESTS || page in jobs) return@forEach
            val key = ImageCache.key(CacheCategory.ORIGINAL, item.id, page)
            if (cache.file(key, item.contentVersion) != null) return@forEach
            val pageUrl = url(page) ?: return@forEach
            jobs[page] = scope.launch {
                try {
                    val result = downloader.download(key, pageUrl, headers(), item.contentVersion, "prefetch", retry = false)
                    if (result.temporary) result.file.delete()
                } catch (_: Throwable) {
                    // Prefetch failures are intentionally silent; current-page loading retries separately.
                    failed += page
                } finally {
                    jobs.remove(page)
                    if (generation == thisGeneration) update(item, current)
                }
            }
        }
    }

    suspend fun stop() {
        generation++
        jobs.values.forEach(Job::cancel)
        jobs.clear()
        failed.clear()
        cache.protect("reader-prefetch", emptySet())
    }

    companion object {
        const val MAX_NETWORK_REQUESTS = 3
        const val MAX_PREFETCH_REQUESTS = MAX_NETWORK_REQUESTS - 1
    }
}

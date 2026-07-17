package com.dokura.app.cache

import android.content.Context
import com.dokura.app.data.CacheCategory
import com.dokura.app.data.CacheDao
import com.dokura.app.data.CacheEntry
import java.io.File
import java.util.UUID
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

data class ClearCacheResult(val releasedBytes: Long, val failures: Int)

/** Disk cache whose Room index is the capacity source of truth during normal operation. */
class ImageCache(
    context: Context,
    private val dao: CacheDao,
    private val limitBytes: () -> Long,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) {
    private val root = File(context.cacheDir, "images")
    private val mutation = Mutex()
    private val protectionOwners = mutableMapOf<String, Set<String>>()
    private val accessScope = CoroutineScope(SupervisorJob() + io)
    private val pendingAccesses = mutableMapOf<String, Long>()
    private var accessFlushJob: Job? = null
    private var writeGeneration = 0L
    private val tempGenerations = mutableMapOf<String, Long>()

    val totalBytes: Flow<Long> = dao.totalBytes()

    suspend fun file(key: String, contentVersion: String): File? = withContext(io) {
        val entry = dao.get(key) ?: return@withContext null
        val candidate = File(root, entry.relativePath)
        if (entry.contentVersion != contentVersion || !candidate.isFile) {
            mutation.withLock {
                candidate.delete()
                dao.delete(key)
            }
            null
        } else {
            recordAccess(key)
            candidate
        }
    }

    suspend fun newTemp(key: String): File = mutation.withLock {
        withContext(io) {
            root.mkdirs()
            val file = File(root, "tmp/${safeName(key)}-${UUID.randomUUID()}.part")
            file.parentFile?.mkdirs()
            dao.upsert(CacheEntry("temp:${file.name}", CacheCategory.TEMP, relative(file), 0, "", System.currentTimeMillis()))
            tempGenerations[file.path] = writeGeneration
            file
        }
    }

    suspend fun updateTempSize(file: File) = mutation.withLock {
        val key = "temp:${file.name}"
        dao.get(key)?.let { dao.upsert(it.copy(bytes = file.length())) }
    }

    suspend fun commit(
        temp: File,
        key: String,
        category: CacheCategory,
        contentVersion: String,
    ): File? = mutation.withLock {
        withContext(io) {
            if (tempGenerations.remove(temp.path) != writeGeneration) {
                dao.delete("temp:${temp.name}")
                return@withContext null
            }
            val destination = File(root, "${category.name.lowercase()}/${safeName(key)}")
            destination.parentFile?.mkdirs()
            Files.move(
                temp.toPath(),
                destination.toPath(),
                StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING,
            )
            dao.delete("temp:${temp.name}")
            dao.upsert(CacheEntry(key, category, relative(destination), destination.length(), contentVersion, System.currentTimeMillis()))
            evictLocked(limitBytes())
            destination
        }
    }

    suspend fun abandon(temp: File) = mutation.withLock {
        withContext(io) {
            tempGenerations.remove(temp.path)
            temp.delete()
            dao.delete("temp:${temp.name}")
        }
    }

    suspend fun protect(owner: String, keys: Set<String>) = mutation.withLock {
        if (keys.isEmpty()) protectionOwners.remove(owner) else protectionOwners[owner] = keys
    }

    suspend fun protect(keys: Set<String>) = protect("default", keys)

    private suspend fun recordAccess(key: String) = mutation.withLock {
        pendingAccesses[key] = System.currentTimeMillis()
        if (pendingAccesses.size >= 100) {
            flushAccessesLocked()
        } else if (accessFlushJob == null) {
            accessFlushJob = accessScope.launch {
                delay(30_000)
                mutation.withLock { flushAccessesLocked() }
            }
        }
    }

    suspend fun flushAccesses() = mutation.withLock { flushAccessesLocked() }

    private suspend fun flushAccessesLocked() {
        val updates = pendingAccesses.mapNotNull { (key, timestamp) -> dao.get(key)?.copy(lastAccessAt = timestamp) }
        if (updates.isNotEmpty()) dao.upsert(updates)
        pendingAccesses.clear()
        accessFlushJob?.cancel()
        accessFlushJob = null
    }

    suspend fun enforceLimit(limit: Long = limitBytes()): Boolean = mutation.withLock { evictLocked(limit) }

    /** Returns false when protected files prevent reaching the configured limit. */
    private suspend fun evictLocked(limit: Long): Boolean {
        flushAccessesLocked()
        var total = dao.totalBytesNow()
        if (total <= limit) return true
        for (category in EVICTION_ORDER) {
            for (entry in dao.oldest(category)) {
                if (protectionOwners.values.any { entry.key in it }) continue
                val file = File(root, entry.relativePath)
                if (file.delete() || !file.exists()) {
                    dao.delete(entry.key)
                    total -= entry.bytes
                    if (total <= limit) return true
                }
            }
        }
        return total <= limit
    }

    suspend fun reconcile() = mutation.withLock {
        withContext(io) {
            root.mkdirs()
            val indexed = dao.all().associateBy { it.relativePath }
            for (entry in indexed.values) {
                val file = File(root, entry.relativePath)
                if (entry.category == CacheCategory.TEMP) {
                    file.delete()
                    dao.delete(entry.key)
                } else if (!file.isFile) dao.delete(entry.key)
                else if (file.length() != entry.bytes) dao.upsert(entry.copy(bytes = file.length()))
            }
            root.walkTopDown().filter(File::isFile).chunked(100).forEach { batch ->
                batch.forEach { file ->
                    val path = relative(file)
                    if (path !in indexed) {
                        val category = categoryFor(path)
                        if (category == CacheCategory.TEMP) file.delete()
                        else dao.upsert(CacheEntry("recovered:$path", category, path, file.length(), "", file.lastModified()))
                    }
                }
            }
            evictLocked(limitBytes())
        }
    }

    suspend fun clear(): ClearCacheResult = mutation.withLock {
        withContext(io) {
            val before = dao.totalBytesNow()
            writeGeneration++
            tempGenerations.clear()
            pendingAccesses.clear()
            var failures = 0
            dao.all().forEach { entry ->
                val file = File(root, entry.relativePath)
                if ((file.delete() || !file.exists())) dao.delete(entry.key) else failures++
            }
            root.walkBottomUp().filter { it != root }.forEach { if (it.exists() && !it.delete() && it.isFile) failures++ }
            val after = dao.totalBytesNow()
            ClearCacheResult((before - after).coerceAtLeast(0), failures)
        }
    }

    private fun relative(file: File) = file.relativeTo(root).invariantSeparatorsPath

    companion object {
        val EVICTION_ORDER = listOf(CacheCategory.TEMP, CacheCategory.PREVIEW, CacheCategory.ORIGINAL, CacheCategory.COVER)

        fun key(category: CacheCategory, fileId: String, page: Int? = null, size: Int? = null): String =
            listOf(category.name.lowercase(), fileId, page, size).filterNotNull().joinToString(":")

        private fun safeName(value: String) = value.replace(Regex("[^A-Za-z0-9._-]"), "_")
        private fun categoryFor(path: String) = when (path.substringBefore('/')) {
            "preview" -> CacheCategory.PREVIEW
            "original" -> CacheCategory.ORIGINAL
            "cover" -> CacheCategory.COVER
            else -> CacheCategory.TEMP
        }
    }
}

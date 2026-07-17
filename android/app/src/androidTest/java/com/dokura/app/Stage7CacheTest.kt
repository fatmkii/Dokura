package com.dokura.app

import android.content.Context
import android.content.ContextWrapper
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.dokura.app.cache.ImageCache
import com.dokura.app.data.CacheCategory
import com.dokura.app.data.DokuraDatabase
import com.dokura.app.data.ReadingProgress
import com.dokura.app.reader.ReaderDownloader
import java.io.File
import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.first
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class Stage7CacheTest {
    private lateinit var database: DokuraDatabase
    private lateinit var context: Context
    private lateinit var cacheRoot: File
    private var limit = Long.MAX_VALUE

    @Before fun createDatabaseAndIsolatedCache() {
        val base = ApplicationProvider.getApplicationContext<Context>()
        cacheRoot = File(base.cacheDir, "stage7-${UUID.randomUUID()}").apply { mkdirs() }
        context = object : ContextWrapper(base) { override fun getCacheDir(): File = cacheRoot }
        database = Room.inMemoryDatabaseBuilder(context, DokuraDatabase::class.java).build()
    }

    @After fun closeDatabaseAndDeleteTemporaryCache() {
        database.close()
        cacheRoot.deleteRecursively()
    }

    @Test fun categoryEvictionHonorsProtectionAndExactIndexedBytes() = runBlocking {
        val cache = ImageCache(context, database.cache(), { limit })
        write(cache, "preview", CacheCategory.PREVIEW, 10)
        write(cache, "original", CacheCategory.ORIGINAL, 10)
        write(cache, "cover", CacheCategory.COVER, 10)
        assertEquals(30, database.cache().totalBytesNow())

        cache.protect(setOf("original", "cover"))
        limit = 15
        assertFalse(cache.enforceLimit())
        assertNull(database.cache().get("preview"))
        assertNotNull(database.cache().get("original"))
        assertNotNull(database.cache().get("cover"))

        cache.protect(emptySet())
        assertTrue(cache.enforceLimit())
        assertNull(database.cache().get("original"))
        assertNotNull(database.cache().get("cover"))
        assertEquals(10, database.cache().totalBytesNow())
    }

    @Test fun clearDeletesOnlyImageCacheAndKeepsReadingProgress() = runBlocking {
        val cache = ImageCache(context, database.cache(), { limit })
        database.readingProgress().upsert(ReadingProgress("file", 7, 123, "name", "path"))
        write(cache, "cover", CacheCategory.COVER, 20)
        val result = cache.clear()
        assertEquals(20, result.releasedBytes)
        assertEquals(0, result.failures)
        assertEquals(7, database.readingProgress().get("file")?.page)
    }

    @Test fun reconciliationRecoversUnindexedDiskBytesAfterAbnormalExit() = runBlocking {
        val orphan = File(cacheRoot, "images/original/orphan").apply {
            parentFile?.mkdirs()
            writeBytes(ByteArray(37))
        }
        val cache = ImageCache(context, database.cache(), { limit })
        cache.reconcile()
        assertTrue(orphan.exists())
        assertEquals(37, database.cache().totalBytesNow())
    }

    @Test fun failedNetworkRequestLeavesNeitherUsableFileNorTemporaryIndex() = runBlocking {
        val cache = ImageCache(context, database.cache(), { limit })
        val client = OkHttpClient.Builder().addInterceptor { throw IOException("offline") }.build()
        val downloader = ReaderDownloader(cache, client)
        runCatching { downloader.download("original", "http://127.0.0.1/image", emptyMap(), "v1", "current", retry = false) }
        assertEquals(0, database.cache().totalBytesNow())
        assertTrue(database.cache().all().isEmpty())
        assertTrue(File(cacheRoot, "images").walkTopDown().none { it.isFile })
    }

    @Test fun recentListTrimsToOneHundredWithoutDeletingOlderPageProgress() = runBlocking {
        repeat(102) { index ->
            database.readingProgress().upsert(ReadingProgress("file-$index", index + 1, index.toLong() + 1, "name", "path"))
        }
        database.readingProgress().trimRecent()
        assertEquals(100, database.readingProgress().recent().first().size)
        assertEquals(1, database.readingProgress().get("file-0")?.page)
        assertEquals(0L, database.readingProgress().get("file-0")?.lastReadAt)
    }

    @Test fun downloadStartedBeforeClearCannotBecomeAUsableCacheEntryAfterClear() = runBlocking {
        val cache = ImageCache(context, database.cache(), { limit })
        val temp = cache.newTemp("late")
        temp.writeBytes(ByteArray(12))
        cache.updateTempSize(temp)
        cache.clear()
        assertNull(cache.commit(temp, "late", CacheCategory.ORIGINAL, "v1"))
        assertNull(database.cache().get("late"))
        assertEquals(0, database.cache().totalBytesNow())
    }

    private suspend fun write(cache: ImageCache, key: String, category: CacheCategory, bytes: Int) {
        val temp = cache.newTemp(key)
        temp.writeBytes(ByteArray(bytes))
        cache.updateTempSize(temp)
        cache.commit(temp, key, category, "v1")
    }
}

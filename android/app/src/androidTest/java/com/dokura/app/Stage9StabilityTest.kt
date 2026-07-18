package com.dokura.app

import android.content.Context
import android.content.ContextWrapper
import android.os.Debug
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.dokura.app.cache.ImageCache
import com.dokura.app.data.CacheCategory
import com.dokura.app.data.DokuraDatabase
import com.dokura.app.reader.ReaderDownloader
import com.dokura.app.reader.ReaderImageDecoder
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.util.UUID
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Release-only endurance test. Normal stage 7 instrumentation skips it. */
@RunWith(AndroidJUnit4::class)
class Stage9StabilityTest {
    @Test fun continuousReadingCacheLimitClearAndNetworkRecovery() = runBlocking {
        val arguments = InstrumentationRegistry.getArguments()
        assumeTrue("仅由阶段 9 显式启用", arguments.getString("stage9") == "true")
        val urls = requireNotNull(arguments.getString("imageUrls")) { "缺少 imageUrls" }
            .split(',').filter(String::isNotBlank)
        require(urls.isNotEmpty()) { "imageUrls 不能为空" }
        val apiKey = requireNotNull(arguments.getString("apiKey")) { "缺少 apiKey" }
        val durationMs = arguments.getString("durationMs")?.toLongOrNull() ?: 3_600_000L
        val cacheBytes = arguments.getString("cacheBytes")?.toLongOrNull() ?: 20L * 1024 * 1024 * 1024

        val base = ApplicationProvider.getApplicationContext<Context>()
        val root = File(base.cacheDir, "stage9-${UUID.randomUUID()}").apply { mkdirs() }
        val context = object : ContextWrapper(base) { override fun getCacheDir(): File = root }
        val database = Room.inMemoryDatabaseBuilder(context, DokuraDatabase::class.java).build()
        try {
            val cache = ImageCache(context, database.cache(), { cacheBytes })
            val client = OkHttpClient.Builder().addInterceptor { chain ->
                chain.proceed(chain.request().newBuilder().header("Authorization", "Bearer $apiKey").build())
            }.build()
            val downloader = ReaderDownloader(cache, client)
            val decoder = ReaderImageDecoder(96L * 1024 * 1024)
            val baselinePss = Debug.getPss()
            var peakPss = baselinePss
            var worstHotPageMs = 0L
            val end = System.currentTimeMillis() + durationMs
            var index = 0
            while (System.currentTimeMillis() < end) {
                val url = urls[index % urls.size]
                val key = "stage9-${index % urls.size}"
                val version = "release-v1"
                val downloaded = downloader.download(key, url, emptyMap(), version, "current", retry = true)
                val bitmap = decoder.decodeFit(downloaded.file, 1080, 1920)
                bitmap.recycle()
                val hotStart = System.nanoTime()
                downloader.download(key, url, emptyMap(), version, "current", retry = false)
                worstHotPageMs = maxOf(worstHotPageMs, (System.nanoTime() - hotStart) / 1_000_000)
                peakPss = maxOf(peakPss, Debug.getPss())
                index++
            }
            assertTrue("Android 热缓存翻页超过 300ms: $worstHotPageMs", worstHotPageMs <= 300)
            assertTrue("位图内存疑似无界增长: baseline=$baselinePss peak=$peakPss", peakPss <= baselinePss + 196_608)

            val nearLimit = cache.newTemp("near-20gb")
            RandomAccessFile(nearLimit, "rw").use { it.setLength(cacheBytes - 1024 * 1024) }
            cache.updateTempSize(nearLimit)
            cache.commit(nearLimit, "near-20gb", CacheCategory.ORIGINAL, "release-v1")
            assertTrue(database.cache().totalBytesNow() >= cacheBytes - 1024 * 1024)
            val cleared = cache.clear()
            assertEquals(0, cleared.failures)
            assertEquals(0, database.cache().totalBytesNow())

            val offline = ReaderDownloader(cache, OkHttpClient.Builder().addInterceptor { throw IOException("offline") }.build())
            runCatching { offline.download("recovery", urls.first(), emptyMap(), "v1", "current", retry = false) }
            downloader.download("recovery", urls.first(), emptyMap(), "v1", "current", retry = true)
            assertTrue(database.cache().get("recovery") != null)
        } finally {
            database.close()
            root.deleteRecursively()
        }
    }
}

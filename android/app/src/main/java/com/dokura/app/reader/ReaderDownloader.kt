package com.dokura.app.reader

import com.dokura.app.cache.ImageCache
import com.dokura.app.data.CacheCategory
import java.io.File
import java.io.IOException
import kotlin.coroutines.resume
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.runBlocking
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response

data class DownloadedImage(val file: File, val temporary: Boolean)

class ReaderDownloader(
    private val cache: ImageCache,
    private val client: OkHttpClient = sharedClient,
) {
    suspend fun download(
        key: String,
        url: String,
        headers: Map<String, String>,
        contentVersion: String,
        purpose: String,
        retry: Boolean,
        category: CacheCategory = CacheCategory.ORIGINAL,
    ): DownloadedImage {
        cache.file(key, contentVersion)?.let { return DownloadedImage(it, temporary = false) }
        var last: Throwable? = null
        val delays = if (retry) listOf(0L, 1_000L, 2_000L, 5_000L) else listOf(0L)
        delays.forEach { wait ->
            if (wait > 0) delay(wait)
            try {
                return downloadOnce(key, url, headers, contentVersion, purpose, category)
            } catch (error: IOException) {
                last = error
            }
        }
        throw last ?: IOException("图片读取失败")
    }

    private suspend fun downloadOnce(
        key: String,
        url: String,
        headers: Map<String, String>,
        contentVersion: String,
        purpose: String,
        category: CacheCategory,
    ): DownloadedImage {
        val temp = cache.newTemp(key)
        return try {
            val request = Request.Builder().url(url).apply {
                headers.forEach { (name, value) -> header(name, value) }
                header("X-Dokura-Image-Purpose", purpose)
            }.build()
            fetch(request, temp) { cache.updateTempSize(temp) }
            cache.updateTempSize(temp)
            requireSupportedImage(temp)
            val committed = cache.commit(temp, key, category, contentVersion)
            DownloadedImage(committed ?: temp, temporary = committed == null)
        } catch (error: Throwable) {
            cache.abandon(temp)
            throw error
        }
    }

    private suspend fun fetch(request: Request, target: File, onProgress: suspend () -> Unit): Unit = suspendCancellableCoroutine { continuation ->
        val call = client.newCall(request)
        continuation.invokeOnCancellation { call.cancel(); target.delete() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (continuation.isActive) continuation.resumeWith(Result.failure(e))
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (!it.isSuccessful) {
                        if (continuation.isActive) continuation.resumeWith(Result.failure(IOException("HTTP ${it.code}")))
                        return
                    }
                    try {
                        target.outputStream().buffered().use { output ->
                            it.body.byteStream().use { input ->
                                val buffer = ByteArray(64 * 1024)
                                var sinceUpdate = 0
                                while (true) {
                                    val count = input.read(buffer)
                                    if (count < 0) break
                                    output.write(buffer, 0, count)
                                    sinceUpdate += count
                                    if (sinceUpdate >= 512 * 1024) {
                                        output.flush()
                                        runBlocking { onProgress() }
                                        sinceUpdate = 0
                                    }
                                }
                            }
                        }
                        if (continuation.isActive) continuation.resume(Unit)
                    } catch (error: IOException) {
                        if (continuation.isActive) continuation.resumeWith(Result.failure(error))
                    }
                }
            }
        })
    }

    companion object {
        private val sharedClient = OkHttpClient()

        fun requireSupportedImage(file: File) {
            val prefix = file.inputStream().use { input -> ByteArray(8).also { input.read(it) } }
            val suffix = file.inputStream().use { input ->
                input.skip((file.length() - 8).coerceAtLeast(0))
                input.readBytes()
            }
            val jpeg = prefix[0] == 0xff.toByte() && prefix[1] == 0xd8.toByte() && prefix[2] == 0xff.toByte() &&
                suffix.size >= 2 && suffix[suffix.lastIndex - 1] == 0xff.toByte() && suffix.last() == 0xd9.toByte()
            val pngEnd = byteArrayOf(0x49, 0x45, 0x4e, 0x44, 0xae.toByte(), 0x42, 0x60, 0x82.toByte())
            val png = prefix.contentEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) && suffix.contentEquals(pngEnd)
            if (!jpeg && !png) throw IOException("服务端返回的不是受支持的 JPEG/PNG")
        }
    }
}

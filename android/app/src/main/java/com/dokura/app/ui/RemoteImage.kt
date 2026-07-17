package com.dokura.app.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import com.dokura.app.UiText
import com.dokura.app.cache.ImageCache
import com.dokura.app.data.CacheCategory
import com.dokura.app.reader.ReaderDownloader
import java.io.File
import java.io.IOException
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import kotlinx.coroutines.launch

private val imageClient = OkHttpClient()

@Composable
fun RemoteImage(
    url: String?,
    headers: Map<String, String>,
    description: String?,
    modifier: Modifier = Modifier,
    cache: ImageCache? = null,
    cacheKey: String? = null,
    category: CacheCategory = CacheCategory.PREVIEW,
    contentVersion: String = "",
) {
    val scope = rememberCoroutineScope()
    DisposableEffect(cache, cacheKey) {
        if (cache != null && cacheKey != null) scope.launch { cache.protect("visible:$cacheKey", setOf(cacheKey)) }
        onDispose {
            if (cache != null && cacheKey != null) scope.launch { cache.protect("visible:$cacheKey", emptySet()) }
        }
    }
    var bytes by remember(url, headers) { mutableStateOf<ByteArray?>(null) }
    var diskFile by remember(url, headers) { mutableStateOf<File?>(null) }
    var temporaryFile by remember(url, headers) { mutableStateOf(false) }
    var failed by remember(url, headers) { mutableStateOf(false) }
    LaunchedEffect(url, headers) {
        bytes = null
        diskFile = null
        temporaryFile = false
        failed = false
        if (url == null) {
            failed = true
            return@LaunchedEffect
        }
        runCatching {
            if (cache != null && cacheKey != null) {
                ReaderDownloader(cache).download(cacheKey, url, headers, contentVersion, if (category == CacheCategory.PREVIEW) "preview" else "cover", retry = true, category = category)
            } else {
                val request = Request.Builder().url(url).apply { headers.forEach { (name, value) -> header(name, value) } }.build()
                fetchBytes(request)
            }
        }.onSuccess { result ->
            if (result is com.dokura.app.reader.DownloadedImage) {
                diskFile = result.file
                temporaryFile = result.temporary
            } else bytes = result as ByteArray
        }
            .onFailure { failed = true }
    }
    Box(modifier.background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
        val bitmap = remember(bytes, diskFile) {
            diskFile?.let {
                BitmapFactory.decodeFile(it.path).also { _ -> if (temporaryFile) it.delete() }
            } ?: bytes?.let { BitmapFactory.decodeByteArray(it, 0, it.size) }
        }
        when {
            bitmap != null -> Image(
                bitmap = bitmap.asImageBitmap(),
                contentDescription = description,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Fit,
            )
            failed -> Text(UiText.NoCover, style = MaterialTheme.typography.labelSmall)
            else -> CircularProgressIndicator()
        }
    }
}

private suspend fun fetchBytes(request: Request): ByteArray = suspendCancellableCoroutine { continuation ->
    val call = imageClient.newCall(request)
    continuation.invokeOnCancellation { call.cancel() }
    call.enqueue(object : Callback {
        override fun onFailure(call: Call, e: IOException) {
            if (continuation.isActive) continuation.resumeWith(Result.failure(e))
        }

        override fun onResponse(call: Call, response: Response) {
            response.use {
                if (!it.isSuccessful) {
                    if (continuation.isActive) continuation.resumeWith(Result.failure(IOException("HTTP ${it.code}")))
                } else {
                    val body = it.body.bytes()
                    if (continuation.isActive) continuation.resume(body)
                }
            }
        }
    })
}

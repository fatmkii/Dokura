package com.dokura.app.network

import com.dokura.app.AppContract
import com.dokura.app.data.ConnectionSettings
import com.google.gson.GsonBuilder
import com.google.gson.Gson
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.delay
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

sealed interface ConnectionTestResult {
    data class Success(val serverVersion: String) : ConnectionTestResult
    data object InvalidAddress : ConnectionTestResult
    data object TimedOut : ConnectionTestResult
    data object NotDokura : ConnectionTestResult
    data object InvalidApiKey : ConnectionTestResult
    data class IncompatibleVersion(val version: String) : ConnectionTestResult
    data object Unreachable : ConnectionTestResult
}

object NetworkClient {
    fun baseUrl(settings: ConnectionSettings): String? {
        if (settings.address.isBlank() || settings.port !in 1..65535) return null
        val raw = settings.address.trim().trimEnd('/')
        val withScheme = if (raw.startsWith("http://") || raw.startsWith("https://")) raw else "http://$raw"
        val parsed = withScheme.toHttpUrlOrNull() ?: return null
        if (parsed.encodedPath != "/" || parsed.query != null || parsed.fragment != null) return null
        return parsed.newBuilder().port(settings.port).build().toString()
    }

    fun okHttp(apiKey: () -> String, timeoutSeconds: Long = 30): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(timeoutSeconds, TimeUnit.SECONDS)
        .readTimeout(timeoutSeconds, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            val key = apiKey()
            val request = chain.request().newBuilder().apply {
                if (key.isNotBlank()) header("Authorization", "Bearer $key")
                header("X-Dokura-Client-ID", "android")
            }.build()
            chain.proceed(request)
        }
        .build()

    fun api(settings: ConnectionSettings, apiKey: () -> String, timeoutSeconds: Long = 30): DokuraApi? {
        val url = baseUrl(settings) ?: return null
        return Retrofit.Builder()
            .baseUrl(url)
            .client(okHttp(apiKey, timeoutSeconds))
            .addConverterFactory(GsonConverterFactory.create(GsonBuilder().create()))
            .build()
            .create(DokuraApi::class.java)
    }

    suspend fun test(settings: ConnectionSettings, apiKey: String, timeoutSeconds: Long = 10): ConnectionTestResult {
        val service = api(settings, { apiKey }, timeoutSeconds) ?: return ConnectionTestResult.InvalidAddress
        val identity = try {
            val response = service.identity()
            if (!response.isSuccessful) return ConnectionTestResult.NotDokura
            val body = response.body()?.string() ?: return ConnectionTestResult.NotDokura
            runCatching { Gson().fromJson(body, com.dokura.app.data.IdentityResponse::class.java) }
                .getOrNull() ?: return ConnectionTestResult.NotDokura
        } catch (_: SocketTimeoutException) {
            return ConnectionTestResult.TimedOut
        } catch (_: IOException) {
            return ConnectionTestResult.Unreachable
        }
        if (identity.service != "Dokura") return ConnectionTestResult.NotDokura
        if (identity.apiVersion != AppContract.ApiVersion) {
            return ConnectionTestResult.IncompatibleVersion(identity.apiVersion)
        }
        return try {
            service.catalog("", 1, 1, "", "current", emptyList(), "all", 0, 5, "name", "asc")
            ConnectionTestResult.Success(identity.serverVersion)
        } catch (_: SocketTimeoutException) {
            ConnectionTestResult.TimedOut
        } catch (error: HttpException) {
            if (error.code() == 401 || error.code() == 403) ConnectionTestResult.InvalidApiKey else ConnectionTestResult.Unreachable
        } catch (_: IOException) {
            ConnectionTestResult.Unreachable
        }
    }
}

suspend fun <T> retryRead(block: suspend () -> T): T {
    val waits = longArrayOf(1_000, 2_000, 5_000)
    var last: Throwable? = null
    repeat(waits.size + 1) { attempt ->
        try {
            return block()
        } catch (error: Throwable) {
            if (error is kotlinx.coroutines.CancellationException) throw error
            val retryable = error is IOException || (error is HttpException && error.code() >= 500)
            if (!retryable || attempt == waits.size) throw error
            last = error
            delay(waits[attempt])
        }
    }
    throw last ?: IllegalStateException("请求失败")
}

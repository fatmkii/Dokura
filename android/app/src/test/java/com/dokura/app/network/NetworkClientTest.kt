package com.dokura.app.network

import com.dokura.app.data.ConnectionSettings
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class NetworkClientTest {
    private lateinit var server: MockWebServer

    @Before fun start() { server = MockWebServer().also { it.start() } }
    @After fun stop() { server.shutdown() }

    private fun settings() = ConnectionSettings("http://${server.hostName}", server.port)
    private fun json(body: String, status: Int = 200) = MockResponse()
        .setResponseCode(status)
        .setBody(body)
        .setHeader("Content-Type", "application/json")

    @Test fun rejectsInvalidAddressWithoutNetworkCall() = runTest {
        assertEquals(ConnectionTestResult.InvalidAddress, NetworkClient.test(ConnectionSettings("http://bad/path", 80), "secret"))
    }

    @Test fun distinguishesNonDokuraService() = runTest {
        server.enqueue(json("""{"service":"Other","server_version":"1","api_version":"1"}"""))
        assertEquals(ConnectionTestResult.NotDokura, NetworkClient.test(settings(), "secret"))
    }

    @Test fun malformedIdentityIsNotDokura() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("<html>not dokura</html>"))
        assertEquals(ConnectionTestResult.NotDokura, NetworkClient.test(settings(), "secret"))
    }

    @Test fun distinguishesInvalidApiKey() = runTest {
        server.enqueue(json("""{"service":"Dokura","server_version":"0.1","api_version":"1"}"""))
        server.enqueue(json("{}", 401))
        assertEquals(ConnectionTestResult.InvalidApiKey, NetworkClient.test(settings(), "secret"))
    }

    @Test fun distinguishesIncompatibleApiVersion() = runTest {
        server.enqueue(json("""{"service":"Dokura","server_version":"0.1","api_version":"2"}"""))
        assertEquals(ConnectionTestResult.IncompatibleVersion("2"), NetworkClient.test(settings(), "secret"))
    }

    @Test fun distinguishesTimeout() = runTest {
        server.enqueue(json("""{"service":"Dokura","server_version":"0.1","api_version":"1"}""").setHeadersDelay(2, TimeUnit.SECONDS))
        assertEquals(ConnectionTestResult.TimedOut, NetworkClient.test(settings(), "secret", timeoutSeconds = 1))
    }

    @Test fun returnsServerVersionAfterReadAuthorizationSucceeds() = runTest {
        server.enqueue(json("""{"service":"Dokura","server_version":"0.1.0","api_version":"1"}"""))
        server.enqueue(json("""{"items":[],"page":1,"per_page":1,"total":0,"pages":0,"result_version":"v1"}"""))
        assertEquals(ConnectionTestResult.Success("0.1.0"), NetworkClient.test(settings(), "secret"))
        server.takeRequest()
        assertEquals("Bearer secret", server.takeRequest().headers["Authorization"])
    }

    @Test fun retriesReadThreeTimesWithSpecifiedDelays() = runTest {
        var attempts = 0
        val value = retryRead {
            attempts++
            if (attempts < 4) throw java.io.IOException("offline")
            "ok"
        }
        assertEquals("ok", value)
        assertEquals(4, attempts)
        assertEquals(8_000, testScheduler.currentTime)
    }
}

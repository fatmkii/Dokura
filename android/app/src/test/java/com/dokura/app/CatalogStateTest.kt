package com.dokura.app

import com.dokura.app.data.CatalogItemDto
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import com.dokura.app.ui.previewTier

class CatalogStateTest {
    @Test fun changingPageVersionStillDeduplicatesFilesByUuid() {
        val first = CatalogItemDto("file", "same-id", "旧名称", "a.zip")
        val repeated = CatalogItemDto("file", "same-id", "新名称", "moved/a.zip")
        val next = CatalogItemDto("file", "new-id", "新文件", "b.zip")
        assertEquals(listOf(first, next), mergeCatalogItems(listOf(first), listOf(repeated, next)))
    }

    @Test fun onlyExplicitNotFoundRemovesLocalState() {
        assertTrue(shouldDeleteLocalState(httpError(404)))
        assertFalse(shouldDeleteLocalState(httpError(401)))
        assertFalse(shouldDeleteLocalState(httpError(503)))
        assertFalse(shouldDeleteLocalState(java.io.IOException("offline")))
    }

    @Test fun previewTierNeverUndersizesAndCapsAt768() {
        assertEquals(256, previewTier(180f))
        assertEquals(512, previewTier(400f))
        assertEquals(768, previewTier(700f))
        assertEquals(768, previewTier(1200f))
    }

    private fun httpError(code: Int): HttpException = HttpException(
        Response.error<Unit>(
            code,
            "{}".toResponseBody("application/json".toMediaType()),
        ),
    )
}

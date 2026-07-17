package com.dokura.app.cache

import com.dokura.app.data.CacheCategory
import org.junit.Assert.assertEquals
import org.junit.Test

class ImageCachePolicyTest {
    @Test fun evictionCategoryOrderIsTemporaryPreviewOriginalCover() {
        assertEquals(
            listOf(CacheCategory.TEMP, CacheCategory.PREVIEW, CacheCategory.ORIGINAL, CacheCategory.COVER),
            ImageCache.EVICTION_ORDER,
        )
    }

    @Test fun cacheKeysSeparateImageKindsAndVariants() {
        assertEquals("cover:file", ImageCache.key(CacheCategory.COVER, "file"))
        assertEquals("preview:file:7:512", ImageCache.key(CacheCategory.PREVIEW, "file", 7, 512))
        assertEquals("original:file:7", ImageCache.key(CacheCategory.ORIGINAL, "file", 7))
    }
}

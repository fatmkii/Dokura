package com.dokura.app.reader

import org.junit.Assert.assertEquals
import org.junit.Test

class ReaderImageDecoderTest {
    @Test fun sampleIncreasesBeforeEstimatedArgbBitmapExceedsBudget() {
        val mib = 1024L * 1024L
        assertEquals(1, ReaderImageDecoder.sampleForBudget(4_000, 4_000, 64L * mib))
        assertEquals(2, ReaderImageDecoder.sampleForBudget(8_000, 8_000, 64L * mib))
        assertEquals(4, ReaderImageDecoder.sampleForBudget(16_000, 16_000, 64L * mib))
    }
}

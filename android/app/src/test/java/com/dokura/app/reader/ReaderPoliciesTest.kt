package com.dokura.app.reader

import com.dokura.app.data.ReadingDirection
import org.junit.Assert.assertEquals
import org.junit.Test

class ReaderPoliciesTest {
    @Test fun prefetchWindowIsThreeBeforeAndTenAfterWithNextPageFirst() {
        assertEquals(
            listOf(6, 4, 7, 3, 8, 2, 9, 10, 11, 12, 13, 14, 15),
            ReaderPolicies.prefetchPages(current = 5, total = 20),
        )
    }

    @Test fun prefetchSkipsUnavailableAndNeverReversesForReadingDirection() {
        assertEquals(listOf(4, 2, 5), ReaderPolicies.prefetchPages(3, 5, setOf(1)))
    }

    @Test fun edgeTapsAndSwipesRespectDirectionButZoomedDragNeverTurnsPage() {
        assertEquals(ReaderAction.NEXT, ReaderPolicies.edgeTap(.9f, ReadingDirection.LEFT_TO_RIGHT))
        assertEquals(ReaderAction.NEXT, ReaderPolicies.edgeTap(.1f, ReadingDirection.RIGHT_TO_LEFT))
        assertEquals(ReaderAction.NEXT, ReaderPolicies.swipe(-100f, ReadingDirection.LEFT_TO_RIGHT, 1f))
        assertEquals(ReaderAction.NEXT, ReaderPolicies.swipe(100f, ReadingDirection.RIGHT_TO_LEFT, 1f))
        assertEquals(ReaderAction.NONE, ReaderPolicies.swipe(-100f, ReadingDirection.LEFT_TO_RIGHT, 2f))
    }

    @Test fun bitmapBudgetsMatchNormalAndLowRamRules() {
        val mib = 1024L * 1024L
        assertEquals(128L * mib, ReaderPolicies.bitmapBudget(512, lowRam = false))
        assertEquals(256L * mib, ReaderPolicies.bitmapBudget(4096, lowRam = false))
        assertEquals((512L * mib * 15) / 100, ReaderPolicies.bitmapBudget(512, lowRam = true))
        assertEquals(128L * mib, ReaderPolicies.bitmapBudget(4096, lowRam = true))
    }

    @Test fun prefetchAlwaysLeavesCurrentPageSlot() {
        assertEquals(3, PrefetchQueue.MAX_NETWORK_REQUESTS)
        assertEquals(2, PrefetchQueue.MAX_PREFETCH_REQUESTS)
    }

    @Test fun progressAndRecentTimersHaveDistinctRules() {
        assertEquals(500L, ProgressPolicy.STABLE_DISPLAY_MS)
        assertEquals(true, ProgressPolicy.shouldUpdateRecent(false, 0, 1_000, exiting = false))
        assertEquals(false, ProgressPolicy.shouldUpdateRecent(true, 1_000, 60_999, exiting = false))
        assertEquals(true, ProgressPolicy.shouldUpdateRecent(true, 1_000, 61_000, exiting = false))
        assertEquals(true, ProgressPolicy.shouldUpdateRecent(true, 60_999, 61_000, exiting = true))
    }
}

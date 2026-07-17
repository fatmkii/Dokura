package com.dokura.app.reader

import com.dokura.app.data.ReadingDirection
import kotlin.math.min

enum class ReaderAction { PREVIOUS, NEXT, TOGGLE_CONTROLS, NONE }

object ReaderPolicies {
    fun prefetchPages(current: Int, total: Int, unavailable: Set<Int> = emptySet()): List<Int> {
        val candidates = (1..10).flatMap { distance ->
            listOf(current + distance, current - distance).filter {
                it in 1..total && it !in unavailable && (it > current || current - it <= 3)
            }
        }
        return candidates.distinct()
    }

    fun edgeTap(xFraction: Float, direction: ReadingDirection): ReaderAction = when {
        xFraction in 0f..<.3f -> if (direction == ReadingDirection.LEFT_TO_RIGHT) ReaderAction.PREVIOUS else ReaderAction.NEXT
        xFraction in .7f..1f -> if (direction == ReadingDirection.LEFT_TO_RIGHT) ReaderAction.NEXT else ReaderAction.PREVIOUS
        xFraction in .3f..<.7f -> ReaderAction.TOGGLE_CONTROLS
        else -> ReaderAction.NONE
    }

    fun swipe(deltaX: Float, direction: ReadingDirection, zoom: Float): ReaderAction {
        if (zoom > 1.01f || kotlin.math.abs(deltaX) < 60f) return ReaderAction.NONE
        val towardNext = if (direction == ReadingDirection.LEFT_TO_RIGHT) deltaX < 0 else deltaX > 0
        return if (towardNext) ReaderAction.NEXT else ReaderAction.PREVIOUS
    }

    fun bitmapBudget(memoryClassMb: Int, lowRam: Boolean): Long {
        val cap = if (lowRam) 128L else 256L
        val percent = if (lowRam) .15 else .25
        return min(cap * MIB, (memoryClassMb * MIB * percent).toLong())
    }

    private const val MIB = 1024L * 1024L
}

object ProgressPolicy {
    const val STABLE_DISPLAY_MS = 500L
    const val RECENT_UPDATE_INTERVAL_MS = 60_000L

    fun shouldUpdateRecent(hasExisting: Boolean, lastSessionUpdate: Long, now: Long, exiting: Boolean): Boolean =
        !hasExisting || exiting || now - lastSessionUpdate >= RECENT_UPDATE_INTERVAL_MS
}

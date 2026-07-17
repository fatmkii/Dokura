package com.dokura.app.reader

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.BitmapRegionDecoder
import android.graphics.Rect
import java.io.File
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.sqrt

class ReaderImageDecoder(private val budgetBytes: Long) {
    fun decodeFit(file: File, targetWidth: Int, targetHeight: Int): Bitmap {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        require(bounds.outWidth > 0 && bounds.outHeight > 0) { "无法解码图片" }
        val fitSample = sampleForFit(bounds.outWidth, bounds.outHeight, targetWidth, targetHeight)
        val budgetSample = sampleForBudget(bounds.outWidth, bounds.outHeight, budgetBytes)
        val options = BitmapFactory.Options().apply {
            inPreferredConfig = Bitmap.Config.ARGB_8888
            inSampleSize = max(fitSample, budgetSample)
        }
        return requireNotNull(BitmapFactory.decodeFile(file.path, options)) { "无法解码图片" }
    }

    @Suppress("DEPRECATION")
    fun decodeRegion(file: File, region: Rect, sampleSize: Int = 1): Bitmap {
        val safeSample = max(sampleSize, sampleForBudget(region.width(), region.height(), budgetBytes))
        val decoder = BitmapRegionDecoder.newInstance(file.path, false)
        return decoder.useCompat {
            requireNotNull(it.decodeRegion(region, BitmapFactory.Options().apply {
                inPreferredConfig = Bitmap.Config.ARGB_8888
                inSampleSize = safeSample
            })) { "无法解码图片区域" }
        }
    }

    companion object {
        fun sampleForBudget(width: Int, height: Int, budgetBytes: Long): Int {
            if (width <= 0 || height <= 0 || budgetBytes <= 0) return 1
            val required = width.toLong() * height.toLong() * 4L
            if (required <= budgetBytes) return 1
            val ratio = sqrt(required.toDouble() / budgetBytes)
            var sample = 1
            while (sample < ceil(ratio).toInt()) sample *= 2
            return sample
        }

        private fun sampleForFit(width: Int, height: Int, targetWidth: Int, targetHeight: Int): Int {
            if (targetWidth <= 0 || targetHeight <= 0) return 1
            var sample = 1
            while (width / (sample * 2) >= targetWidth && height / (sample * 2) >= targetHeight) sample *= 2
            return sample
        }
    }
}

private inline fun <T> BitmapRegionDecoder.useCompat(block: (BitmapRegionDecoder) -> T): T = try {
    block(this)
} finally {
    recycle()
}

package com.remotedesk.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.util.AttributeSet
import android.view.View

/**
 * نمای نمایش صفحه مقصد؛ تصویر را با حفظ نسبت در مرکز می‌کشد
 * و مختصات لمس را به نرمال‌شده 0..1 صفحه مقصد تبدیل می‌کند.
 */
class ScreenView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    @Volatile private var bitmap: android.graphics.Bitmap? = null
    private val bgPaint = Paint().apply { color = Color.BLACK }
    private val bounds = Rect()

    fun setFrame(bmp: android.graphics.Bitmap) {
        bitmap = bmp
        postInvalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), bgPaint)
        val bmp = bitmap ?: return
        computeLetterbox(bmp.width, bmp.height, bounds)
        canvas.drawBitmap(bmp, null, bounds, null)
    }

    private fun computeLetterbox(bw: Int, bh: Int, out: Rect) {
        val vw = width
        val vh = height
        if (bw <= 0 || bh <= 0 || vw <= 0 || vh <= 0) {
            out.set(0, 0, 1, 1)
            return
        }
        val scale = minOf(vw.toFloat() / bw, vh.toFloat() / bh)
        val w = (bw * scale).toInt()
        val h = (bh * scale).toInt()
        out.set((vw - w) / 2, (vh - h) / 2, (vw - w) / 2 + w, (vh - h) / 2 + h)
    }

    /** خروجی: (x_norm, y_norm) یا null اگر لمس بیرون تصویر باشد. */
    fun normalized(x: Float, y: Float): Pair<Float, Float>? {
        val bmp = bitmap ?: return null
        computeLetterbox(bmp.width, bmp.height, bounds)
        if (bounds.width() <= 0 || bounds.height() <= 0) return null
        val bx = (x - bounds.left) / bounds.width()
        val by = (y - bounds.top) / bounds.height()
        if (bx < 0f || bx > 1f || by < 0f || by > 1f) return null
        return bx.coerceIn(0f, 1f) to by.coerceIn(0f, 1f)
    }
}

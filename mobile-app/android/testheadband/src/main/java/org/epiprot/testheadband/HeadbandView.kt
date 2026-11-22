package org.epiprot.testheadband

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PathMeasure
import android.graphics.RectF
import android.graphics.Typeface
import android.view.View
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Presentation view of the test headband: the X-ray render of the designed band, its electrodes glowing with
 * the EEG that is being "measured", data running along the flex cable to the pod and radio waves to the phone,
 * plus the live signals. Everything shown comes from the packets this app really streams (a real recorded
 * seizure replayed through the simulated headband).
 */
class HeadbandView(context: Context) : View(context) {
    private val tr = Locale.getDefault().language == "tr"
    private fun t(en: String, trk: String) = if (tr) trk else en

    private val img: Bitmap? = try { context.assets.open("headband_xray.jpg").use(BitmapFactory::decodeStream) } catch (e: Exception) { null }

    // ---------------------------------------------------------------- data (written by the stream thread)
    private val eegN = 256 * 5
    private val ch1 = FloatArray(eegN); private val ch2 = FloatArray(eegN); private var eegW = 0
    private val accN = 25 * 5
    private val acc = FloatArray(accN); private var accW = 0
    @Volatile var sending = false          // a phone is connected and subscribed: data goes out now
    @Volatile var battery = -1
    @Volatile var onsetIn = 0.0
    @Volatile var running = false
    @Volatile var off: String? = null      // "switched off from the app" / "unpaired"
    @Volatile var identifyUntil = 0L
    @Volatile var packetsPerS = 0
    private var lastEegLevel = 0f
    // 0.5 Hz high-pass for the display (electrode offset removed, like the phone's filter)
    private var hpX1 = 0f; private var hpY1 = 0f; private var hpX2 = 0f; private var hpY2 = 0f
    private fun hp1(x: Float): Float { hpY1 = 0.988f * (hpY1 + x - hpX1); hpX1 = x; return hpY1 }
    private fun hp2(x: Float): Float { hpY2 = 0.988f * (hpY2 + x - hpX2); hpX2 = x; return hpY2 }
    private val lsbNv = 44.7f            // Device info, PROTOCOL.md
    private val accLsb = 4096f

    /** Every packet the band produces (sent or stored). */
    fun packet(p: ByteArray) {
        if (p.size < 6) return
        val bb = ByteBuffer.wrap(p).order(ByteOrder.LITTLE_ENDIAN)
        when (p[0].toInt()) {
            0x01 -> if (p.size >= 208) synchronized(this) {
                val n = p[14].toInt()
                var lvl = 0f
                for (i in 0 until n) {
                    val o = 16 + i * 12
                    val a = hp1(s24(p, o) * lsbNv / 1000f); val b = hp2(s24(p, o + 3) * lsbNv / 1000f)
                    ch1[eegW] = a; ch2[eegW] = b; eegW = (eegW + 1) % eegN
                    lvl = max(lvl, abs(a))
                }
                lastEegLevel = lvl
            }
            0x02 -> if (p.size >= 71) synchronized(this) {
                val n = p[10].toInt()
                for (i in 0 until n) {
                    val o = 11 + i * 12
                    val x = bb.getShort(o) / accLsb; val y = bb.getShort(o + 2) / accLsb; val z = bb.getShort(o + 4) / accLsb
                    acc[accW] = sqrt(x * x + y * y + z * z); accW = (accW + 1) % accN
                }
            }
            0x03 -> if (p.size >= 13) battery = p[12].toInt() and 0xFF
        }
    }

    private fun s24(p: ByteArray, o: Int) =
        (p[o].toInt() and 0xFF) or ((p[o + 1].toInt() and 0xFF) shl 8) or (p[o + 2].toInt() shl 16)

    // ---------------------------------------------------------------- drawing
    private val bg = Color.rgb(16, 20, 28)
    private val cyan = Color.rgb(64, 220, 255)
    private val amber = Color.rgb(255, 176, 32)
    private val green = Color.rgb(80, 230, 140)
    private val red = Color.rgb(255, 70, 70)
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val text = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; typeface = Typeface.DEFAULT_BOLD }
    private val small = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(190, 200, 215) }
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = 3f; strokeJoin = Paint.Join.ROUND }

    // positions in the X-ray image (0..1)
    private val electrodes = listOf(0.544f to 0.179f, 0.538f to 0.342f, 0.516f to 0.462f)
    private val flex = listOf(0.566f to 0.085f, 0.553f to 0.19f, 0.537f to 0.35f, 0.512f to 0.47f, 0.475f to 0.53f, 0.455f to 0.56f)
    private val antenna = 0.455f to 0.587f
    private val pod = 0.465f to 0.72f

    private val start = System.nanoTime()

    override fun onDraw(c: Canvas) {
        val w = width.toFloat(); val h = height.toFloat()
        c.drawColor(bg)
        val s = min(w, h) / 1000f
        text.textSize = 34f * s; small.textSize = 24f * s
        val now = (System.nanoTime() - start) / 1e9f
        val wide = w > h * 1.15f

        val split = if (wide) 0.55f else min(0.55f, (w * 0.75f + 90f * s) / h)
        val imgBox = if (wide) RectF(0f, 0f, w * split, h) else RectF(0f, 0f, w, h * split)
        val sigBox = if (wide) RectF(w * split, 0f, w, h) else RectF(0f, h * split, w, h)
        drawBand(c, imgBox, s, now)
        drawSignals(c, sigBox, s)
        postInvalidateOnAnimation()
    }

    private fun drawBand(c: Canvas, box: RectF, s: Float, now: Float) {
        val im = img ?: return
        val scale = min(box.width() / im.width, (box.height() - 90 * s) / im.height)
        val iw = im.width * scale; val ih = im.height * scale
        val r = RectF(box.centerX() - iw / 2, box.top + 80 * s, box.centerX() + iw / 2, box.top + 80 * s + ih)
        c.drawBitmap(im, null, r, null)
        fun px(p: Pair<Float, Float>) = r.left + p.first * iw to r.top + p.second * ih

        // header
        val alive = running && off == null
        c.drawText("EpiProt " + t("headband", "kafa bandı"), box.left + 24 * s, box.top + 44 * s, text)
        val state = when {
            off != null -> off!!
            !running -> t("off", "kapalı")
            sending -> t("● LIVE → phone", "● CANLI → telefon") + "   $packetsPerS " + t("packets/s", "paket/sn")
            else -> t("○ no phone: measuring and storing", "○ telefon yok: ölçüyor ve saklıyor")
        }
        small.color = if (sending && alive) green else Color.rgb(190, 200, 215)
        c.drawText(state, box.left + 24 * s, box.top + 72 * s, small)
        small.color = Color.rgb(190, 200, 215)

        if (!alive) return
        // electrodes: glow follows the EEG amplitude
        val lvl = min(1f, lastEegLevel / 200f)
        for (e in electrodes) {
            val (x, y) = px(e)
            for (k in 2 downTo 1) {
                paint.color = Color.argb((50 + 70 * lvl).toInt() / k, 64, 220, 255)
                c.drawCircle(x, y, (14 + 18 * lvl) * s * k * 0.8f, paint)
            }
            paint.color = cyan; c.drawCircle(x, y, 8 * s, paint)
        }
        // data running along the flex cable to the pod
        val path = Path().apply {
            val (x0, y0) = px(flex[0]); moveTo(x0, y0)
            for (p in flex.drop(1)) { val (x, y) = px(p); lineTo(x, y) }
        }
        val pm = PathMeasure(path, false); val len = pm.length; val pos = FloatArray(2)
        paint.color = amber
        for (k in 0 until 6) {
            val f = ((now * 0.8f + k / 6f) % 1f)
            pm.getPosTan(f * len, pos, null)
            c.drawCircle(pos[0], pos[1], 7 * s, paint)
        }
        // pod label
        val (podX, podY) = px(pod)
        label(c, t("processor + Bluetooth", "işlemci + Bluetooth"), podX - 120 * s, podY + 10 * s, s)
        // radio waves from the antenna when the phone receives
        val (ax, ay) = px(antenna)
        line.color = if (sending) green else Color.argb(90, 200, 200, 200)
        if (sending) for (k in 0 until 4) {
            val f = (now * 1.2f + k / 4f) % 1f
            line.alpha = ((1 - f) * 255).toInt()
            val rr = (30 + 220 * f) * s
            c.drawArc(RectF(ax - rr, ay - rr, ax + rr, ay + rr), 150f, 60f, false, line)
        }
        // status light (blinks fast on IDENTIFY)
        val blink = System.currentTimeMillis() < identifyUntil
        paint.color = if (blink && (now * 6).toInt() % 2 == 0) Color.WHITE else if (sending) green else amber
        c.drawCircle(ax + 40 * s, ay - 10 * s, (if (blink) 14 else 8) * s, paint)
        // labels
        val (ex, ey) = px(electrodes[0])
        label(c, t("EEG electrodes", "EEG elektrotları"), ex + 70 * s, ey, s)
        val (fx, fy) = px(flex[3])
        label(c, t("signal cable", "sinyal kablosu"), fx + 80 * s, fy + 40 * s, s)
        if (sending) label(c, t("radio → phone", "radyo → telefon"), ax - 330 * s, ay - 40 * s, s)
        if (battery >= 0) c.drawText(t("battery", "pil") + " %$battery", box.right - 170 * s, box.top + 44 * s, small)
    }

    private val pill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(200, 16, 20, 28) }
    private fun label(c: Canvas, s: String, x: Float, y: Float, k: Float) {
        val w = small.measureText(s)
        c.drawRoundRect(RectF(x - 12 * k, y - 30 * k, x + w + 12 * k, y + 12 * k), 18 * k, 18 * k, pill)
        small.color = Color.WHITE; c.drawText(s, x, y, small); small.color = Color.rgb(190, 200, 215)
    }

    private fun drawSignals(c: Canvas, box: RectF, s: Float) {
        val pad = 24 * s
        val seizure = onsetIn <= 0 && running && off == null
        val head = when {
            !running || off != null -> ""
            seizure -> t("SEIZURE in the recording – the phone should alarm", "KAYITTA NÖBET – telefon alarm vermeli")
            else -> t("Seizure in the recording in ", "Kayıttaki nöbete ") + "%d:%02d".format((onsetIn / 60).toInt(), (onsetIn % 60).toInt()) +
                t("", " kaldı")
        }
        text.color = if (seizure) red else Color.WHITE
        c.drawText(head, box.left + pad, box.top + 44 * s, text)
        text.color = Color.WHITE
        c.drawText(t("Replay of a real recorded seizure (SeizeIT2)", "Gerçek bir nöbet kaydı oynatılıyor (SeizeIT2)"),
            box.left + pad, box.top + 72 * s, small)
        val top = box.top + 100 * s
        val each = (box.bottom - top - pad) / 3
        synchronized(this) {
            trace(c, RectF(box.left + pad, top, box.right - pad, top + each - 16 * s), ch1, eegW,
                t("EEG left, behind the ear (µV)", "EEG sol, kulak arkası (µV)"), cyan, s, true)
            trace(c, RectF(box.left + pad, top + each, box.right - pad, top + 2 * each - 16 * s), ch2, eegW,
                t("EEG across the head (µV)", "EEG baştan başa (µV)"), cyan, s, true)
            trace(c, RectF(box.left + pad, top + 2 * each, box.right - pad, top + 3 * each - 16 * s), acc, accW,
                t("Head movement (g)", "Baş hareketi (g)"), amber, s, false)
        }
    }

    private fun trace(c: Canvas, r: RectF, data: FloatArray, w: Int, label: String, color: Int, s: Float, centered: Boolean) {
        paint.color = Color.rgb(26, 32, 44); c.drawRoundRect(r, 12 * s, 12 * s, paint)
        c.drawText(label, r.left + 14 * s, r.top + 30 * s, small)
        val n = data.size
        var lo = Float.MAX_VALUE; var hi = -Float.MAX_VALUE
        for (v in data) { lo = min(lo, v); hi = max(hi, v) }
        if (centered) { val m = max(50f, max(abs(lo), abs(hi))); lo = -m; hi = m } else { lo = min(lo, 0.8f); hi = max(hi, 1.2f) }
        val inner = RectF(r.left + 8 * s, r.top + 40 * s, r.right - 8 * s, r.bottom - 8 * s)
        val p = Path()
        for (i in 0 until n) {
            val v = data[(w + i) % n]
            val x = inner.left + inner.width() * i / (n - 1)
            val y = inner.bottom - (v - lo) / (hi - lo) * inner.height()
            if (i == 0) p.moveTo(x, y) else p.lineTo(x, y)
        }
        line.color = color; line.alpha = 255; line.strokeWidth = 2.2f * s.coerceAtLeast(0.6f)
        c.drawPath(p, line)
        line.strokeWidth = 3f
        small.textSize = 20f * s
        c.drawText(if (centered) "±%.0f".format(hi) else "%.1f".format(hi), r.right - 90 * s, r.top + 30 * s, small)
        small.textSize = 24f * s
    }
}

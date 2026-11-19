package org.epiprot.phone.report

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import org.epiprot.phone.R
import java.io.File
import java.text.DateFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Draws the doctor report (A4, on the phone, nothing leaves the phone until the patient shares the file). */
object ReportPdf {
    private const val PW = 595
    private const val PH = 842
    private const val M = 40f

    private val TEAL = Color.parseColor("#0E7C86")
    private val TEAL_SOFT = Color.parseColor("#DDF1F1")
    private val CORAL = Color.parseColor("#D9483B")
    private val AMBER = Color.parseColor("#C77700")
    private val INK = Color.parseColor("#1B2B2E")
    private val INK_SOFT = Color.parseColor("#5B6B6E")
    private val LINE = Color.parseColor("#E3EAEA")
    private val BG = Color.parseColor("#F4F8F8")

    fun write(context: Context, d: ReportData, patient: String, out: File,
              signals: Map<Long, org.epiprot.phone.signals.SignalSnippet> = emptyMap()) {
        val s = { id: Int -> context.getString(id) }
        val date = DateFormat.getDateInstance(DateFormat.MEDIUM)
        val dateTime = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
        val doc = PdfDocument()
        var pageNo = 0
        lateinit var page: PdfDocument.Page
        lateinit var c: Canvas

        fun paint(size: Float, color: Int = INK, bold: Boolean = false) = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textSize = size; this.color = color; typeface = Typeface.create(Typeface.SANS_SERIF, if (bold) Typeface.BOLD else Typeface.NORMAL)
        }
        fun fill(color: Int) = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color; style = Paint.Style.FILL }
        fun wrap(text: String, p: Paint, width: Float): List<String> {
            val out = ArrayList<String>(); var cur = ""
            for (w in text.split(" ")) {
                val t = if (cur.isEmpty()) w else "$cur $w"
                if (p.measureText(t) <= width) cur = t else { out += cur; cur = w }
            }
            if (cur.isNotEmpty()) out += cur
            return out
        }
        fun footer() {
            val p = paint(7.5f, INK_SOFT)
            var y = PH - 34f
            for (l in wrap(s(R.string.rep_footer), p, PW - 2 * M - 40)) { c.drawText(l, M, y, p); y += 10 }
            c.drawText("$pageNo", PW - M - p.measureText("$pageNo"), PH - 34f, p)
        }
        fun newPage() {
            if (pageNo > 0) { footer(); doc.finishPage(page) }
            pageNo++
            page = doc.startPage(PdfDocument.PageInfo.Builder(PW, PH, pageNo).create())
            c = page.canvas
        }

        // ---------------------------------------------------------------- page 1: header, summary, charts
        newPage()
        c.drawRect(0f, 0f, PW.toFloat(), 104f, fill(TEAL))
        c.drawText(s(R.string.rep_title), M, 46f, paint(22f, Color.WHITE, true))
        c.drawText(patient.ifBlank { "–" }, M, 70f, paint(13f, Color.WHITE, true))
        c.drawText(s(R.string.rep_period) + ": " + date.format(Date(d.fromMs)) + " – " + date.format(Date(d.toMs)), M, 88f, paint(10f, Color.WHITE))
        val gen = s(R.string.rep_generated) + " " + dateTime.format(Date())
        c.drawText(gen, PW - M - paint(9f).measureText(gen), 88f, paint(9f, Color.WHITE))

        // summary tiles
        val tiles = listOf(
            Triple("${d.seizures}", s(R.string.rep_seizures), CORAL),
            Triple("${d.unconfirmed}", s(R.string.rep_unconfirmed), AMBER),
            Triple("${d.falseAlarms}", s(R.string.rep_false_alarms), TEAL),
            Triple(d.longestS?.let { mmss(it) } ?: "–", s(R.string.rep_longest), INK),
            Triple("${d.emergencies}", s(R.string.rep_emergencies), CORAL),
        )
        val tw = (PW - 2 * M - 4 * 8) / 5
        tiles.forEachIndexed { i, (v, label, col) ->
            val x = M + i * (tw + 8)
            c.drawRoundRect(RectF(x, 122f, x + tw, 196f), 10f, 10f, fill(BG))
            c.drawText(v, x + 10, 156f, paint(22f, col, true))
            var y = 172f
            for (l in wrap(label, paint(8.5f, INK_SOFT), tw - 16)) { c.drawText(l, x + 10, y, paint(8.5f, INK_SOFT)); y += 10 }
        }

        // weekly chart
        var top = 222f
        c.drawText(s(R.string.rep_per_week), M, top, paint(12f, INK, true))
        c.drawText(s(R.string.rep_per_week_note), M, top + 14, paint(8.5f, INK_SOFT))
        bars(c, d.weeks.map { it.second }, d.weeks.map { SimpleDateFormat("d MMM", Locale.getDefault()).format(Date(it.first)) },
            M, top + 26, PW - 2 * M, 130f, CORAL, ::paint, labelEvery = maxOf(1, d.weeks.size / 8))

        // hour-of-day chart
        top += 200f
        c.drawText(s(R.string.rep_by_hour), M, top, paint(12f, INK, true))
        c.drawText(s(R.string.rep_by_hour_note), M, top + 14, paint(8.5f, INK_SOFT))
        bars(c, d.byHour.toList(), (0..23).map { "%02d".format(it) }, M, top + 26, PW - 2 * M, 110f, TEAL, ::paint, labelEvery = 3)

        // sensors and notes
        top += 178f
        c.drawText(s(R.string.rep_sensors), M, top, paint(12f, INK, true))
        val sensorsText = if (d.sensorProblems.isEmpty()) s(R.string.rep_sensors_none)
            else d.sensorProblems.entries.joinToString(" · ") { "${it.key}: ${it.value}" }
        c.drawText(sensorsText, M, top + 16, paint(10f, INK))
        top += 40f
        c.drawText(s(R.string.rep_notes), M, top, paint(12f, INK, true))
        var ny = top + 16
        for (line in listOf(s(R.string.rep_note_kinds), s(R.string.rep_note_duration), s(R.string.rep_note_content))) {
            for (l in wrap("• $line", paint(9f, INK_SOFT), PW - 2 * M)) { c.drawText(l, M, ny, paint(9f, INK_SOFT)); ny += 12 }
        }

        // ---------------------------------------------------------------- event table
        newPage()
        val cols = listOf(s(R.string.rep_col_time) to 0.24f, s(R.string.rep_col_type) to 0.20f, s(R.string.rep_col_duration) to 0.11f,
            s(R.string.rep_col_pin) to 0.10f, s(R.string.rep_col_caregiver) to 0.12f, s(R.string.rep_col_emergency) to 0.10f,
            s(R.string.rep_col_answered) to 0.13f)
        val tableW = PW - 2 * M
        var y = 60f
        c.drawText(s(R.string.rep_events) + " (${d.events.size})", M, y, paint(14f, INK, true))
        y += 20
        fun header() {
            c.drawRect(M, y - 12, M + tableW, y + 6, fill(TEAL_SOFT))
            var x = M + 4
            for ((h, w) in cols) { c.drawText(h, x, y, paint(8.5f, INK, true)); x += w * tableW }
            y += 18
        }
        header()
        if (d.events.isEmpty()) c.drawText(s(R.string.rep_no_events), M, y + 6, paint(10f, INK_SOFT))
        val yes = s(R.string.rep_yes); val no = s(R.string.rep_no)
        for ((i, e) in d.events.withIndex()) {
            if (y > PH - 70) { newPage(); y = 60f; header() }
            if (i % 2 == 1) c.drawRect(M, y - 11, M + tableW, y + 5, fill(BG))
            val type = when (e.kind) {
                ReportKind.SEIZURE -> s(R.string.rep_kind_seizure)
                ReportKind.UNCONFIRMED -> s(R.string.rep_kind_unconfirmed)
                ReportKind.FALSE_ALARM -> s(R.string.rep_kind_false)
            }
            val cells = listOf(dateTime.format(Date(e.alarmMs)), type, e.durationS?.let { mmss(it) } ?: "–",
                if (e.cancelledWithPin) yes else no, if (e.caregiverNotified) yes else no, if (e.emergency) yes else no,
                e.recoveryResponseS?.let { mmss(it) } ?: "–")
            var x = M + 4
            cells.forEachIndexed { k, v ->
                val col = if (k == 1) when (e.kind) { ReportKind.SEIZURE -> CORAL; ReportKind.UNCONFIRMED -> AMBER; else -> TEAL } else INK
                c.drawText(v, x, y, paint(8.5f, col, k == 1)); x += cols[k].second * tableW
            }
            c.drawLine(M, y + 5, M + tableW, y + 5, Paint().apply { color = LINE; strokeWidth = 0.5f })
            y += 16
        }
        // ---------------------------------------------------------------- signals around each alarm (with consent)
        val withSignals = d.events.filter { it.eventId in signals }.sortedByDescending { it.alarmMs }
        for (e in withSignals) {
            val sn = signals.getValue(e.eventId)
            newPage()
            c.drawText(s(R.string.rep_sig_title), M, 56f, paint(14f, INK, true))
            c.drawText(dateTime.format(Date(e.alarmMs)) + " · " + when (e.kind) {
                ReportKind.SEIZURE -> s(R.string.rep_kind_seizure); ReportKind.UNCONFIRMED -> s(R.string.rep_kind_unconfirmed)
                ReportKind.FALSE_ALARM -> s(R.string.rep_kind_false) } + (e.durationS?.let { " · " + s(R.string.rep_col_duration) + " " + mmss(it) } ?: ""),
                M, 74f, paint(10f, INK_SOFT))
            val t0 = sn.startMs; val span = sn.durationMs.toFloat().coerceAtLeast(1f)
            val traces = listOf(
                Triple(s(R.string.rep_sig_eeg1), sn.eeg.getOrNull(0) ?: FloatArray(0), TEAL),
                Triple(s(R.string.rep_sig_eeg2), sn.eeg.getOrNull(1) ?: FloatArray(0), TEAL),
                Triple(s(R.string.rep_sig_mov), sn.movement, AMBER),
                Triple(s(R.string.rep_sig_hr), sn.heartRate, CORAL),
            )
            var top = 96f
            val h = 128f
            val markers = listOfNotNull(sn.onsetMs to Color.parseColor("#E8A33D"), sn.alarmMs to CORAL,
                d.events.firstOrNull { it.eventId == e.eventId }?.durationS?.let { (sn.onsetMs + it * 1000) to INK_SOFT })
            for ((label, data, col) in traces) {
                c.drawText(label, M, top + 10, paint(9.5f, INK, true))
                trace(c, data, M, top + 16, PW - 2 * M, h - 30, col, ::paint)
                for ((tm, mc) in markers) {
                    val x = M + (PW - 2 * M) * ((tm - t0) / span)
                    if (x in M..(PW - M)) c.drawLine(x, top + 14, x, top + h - 12, Paint().apply { color = mc; strokeWidth = 1.2f })
                }
                top += h
            }
            // time axis (minutes relative to the alarm)
            val axisY = top - 4
            val lp = paint(8f, INK_SOFT)
            var mnt = -((sn.alarmMs - t0) / 60_000L)
            while (t0 + 0L < sn.startMs + sn.durationMs) {
                val tm = sn.alarmMs + mnt * 60_000L
                if (tm > sn.startMs + sn.durationMs) break
                val x = M + (PW - 2 * M) * ((tm - t0) / span)
                if (x >= M) c.drawText((if (mnt > 0) "+" else "") + "$mnt", x - 4, axisY, lp)
                mnt++
            }
            c.drawText(s(R.string.rep_sig_axis), M, axisY + 14, lp)
            // legend
            var lx = M; val ly = axisY + 32
            for ((txt, col) in listOf(s(R.string.rep_sig_onset) to Color.parseColor("#E8A33D"), s(R.string.rep_sig_alarm) to CORAL,
                    s(R.string.rep_sig_end) to INK_SOFT)) {
                c.drawRect(lx, ly - 7, lx + 12, ly - 5, fill(col)); c.drawText(txt, lx + 16, ly - 3, paint(8.5f, INK_SOFT)); lx += 150
            }
            var ny = ly + 16
            for (l in wrap(s(R.string.rep_sig_note), paint(8.5f, INK_SOFT), PW - 2 * M)) { c.drawText(l, M, ny, paint(8.5f, INK_SOFT)); ny += 11 }
        }
        if (withSignals.isEmpty() && d.events.isNotEmpty()) {
            if (y > PH - 110) { newPage(); y = 60f }
            y += 20
            for (l in wrap(s(R.string.rep_sig_none), paint(9f, INK_SOFT), PW - 2 * M)) { c.drawText(l, M, y, paint(9f, INK_SOFT)); y += 12 }
        }
        footer()
        doc.finishPage(page)
        out.parentFile?.mkdirs()
        out.outputStream().use { doc.writeTo(it) }
        doc.close()
    }

    private fun mmss(s: Long) = if (s >= 3600) "%d:%02d:%02d".format(s / 3600, s / 60 % 60, s % 60) else "%d:%02d".format(s / 60, s % 60)

    /** Min/max per pixel column (fast for long signals); gaps (NaN) are left empty. */
    private fun trace(c: Canvas, v: FloatArray, x0: Float, y0: Float, w: Float, h: Float, color: Int,
                      paint: (Float, Int, Boolean) -> Paint) {
        c.drawRect(x0, y0, x0 + w, y0 + h, Paint().apply { this.color = BG })
        val finite = v.filter { it.isFinite() }
        if (finite.isEmpty()) { c.drawText("–", x0 + w / 2, y0 + h / 2, paint(9f, INK_SOFT, false)); return }
        // robust range: 1st-99th percentile so one artefact does not flatten everything
        val sorted = finite.sorted()
        var lo = sorted[(sorted.size * 0.01).toInt()]; var hi = sorted[((sorted.size - 1) * 0.99).toInt()]
        if (hi - lo < 1e-6f) { lo -= 1f; hi += 1f }
        val cols = w.toInt().coerceAtLeast(1)
        val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color; strokeWidth = 0.8f }
        fun yOf(a: Float) = y0 + h - h * ((a.coerceIn(lo, hi) - lo) / (hi - lo))
        val lp = paint(7f, INK_SOFT, false)
        val fmt = if (hi - lo < 10f) "%.2f" else "%.0f"
        c.drawText(fmt.format(hi), x0 + w + 3, y0 + 7, lp)
        c.drawText(fmt.format(lo), x0 + w + 3, y0 + h, lp)
        if (v.size < cols) {          // short series (heart rate): a line through the points, broken at gaps
            val step = w / v.size
            p.strokeWidth = 1.4f
            for (k in 1 until v.size) if (v[k - 1].isFinite() && v[k].isFinite())
                c.drawLine(x0 + step * (k - 0.5f), yOf(v[k - 1]), x0 + step * (k + 0.5f), yOf(v[k]), p)
            return
        }
        for (cx in 0 until cols) {
            val a = (cx.toLong() * v.size / cols).toInt(); val b = (((cx + 1).toLong() * v.size / cols).toInt()).coerceAtLeast(a + 1).coerceAtMost(v.size)
            var mn = Float.POSITIVE_INFINITY; var mx = Float.NEGATIVE_INFINITY
            for (k in a until b) { val q = v[k]; if (q.isFinite()) { if (q < mn) mn = q; if (q > mx) mx = q } }
            if (mn.isFinite()) c.drawLine(x0 + cx, yOf(mx), x0 + cx, yOf(mn) + 0.5f, p)
        }
    }

    private fun bars(c: Canvas, values: List<Int>, labels: List<String>, x0: Float, y0: Float, w: Float, h: Float, color: Int,
                     paint: (Float, Int, Boolean) -> Paint, labelEvery: Int) {
        val n = values.size.coerceAtLeast(1)
        val maxV = (values.maxOrNull() ?: 0).coerceAtLeast(1)
        val base = y0 + h
        val axis = Paint().apply { this.color = LINE; strokeWidth = 1f }
        c.drawLine(x0, base, x0 + w, base, axis)
        // y gridlines: 0, max/2, max
        for (v in listOf(maxV, (maxV + 1) / 2)) {
            val yy = base - h * v / maxV
            c.drawLine(x0 + 18, yy, x0 + w, yy, Paint().apply { this.color = LINE; strokeWidth = 0.5f })
            c.drawText("$v", x0, yy + 3, paint(7.5f, INK_SOFT, false))
        }
        val slot = (w - 20) / n
        val bw = (slot * 0.65f).coerceAtMost(28f)
        val fillP = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color }
        values.forEachIndexed { i, v ->
            val cx = x0 + 20 + slot * i + slot / 2
            if (v > 0) c.drawRoundRect(RectF(cx - bw / 2, base - h * v / maxV, cx + bw / 2, base), 3f, 3f, fillP)
            if (i % labelEvery == 0) {
                val lp = paint(7f, INK_SOFT, false)
                c.drawText(labels[i], cx - lp.measureText(labels[i]) / 2, base + 11, lp)
            }
        }
    }
}

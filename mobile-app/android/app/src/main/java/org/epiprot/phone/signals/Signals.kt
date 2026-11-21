package org.epiprot.phone.signals

import org.epiprot.phone.model.WindowFeatures
import org.epiprot.phone.model.WindowInput
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.util.zip.DeflaterOutputStream
import java.util.zip.InflaterInputStream
import kotlin.math.sqrt

/**
 * The signals around one alarm, kept (only with the "signals" consent) for the doctor report:
 * from [PRE_WINDOWS] windows before the alarm to [POST_WINDOWS] windows after it (2 min + 5 min).
 *  eeg      : 2 channels at 256 Hz, microvolts (NaN where the headband sent nothing)
 *  movement : headband acceleration magnitude at 25 Hz (wrist if the headband has none), NaN for gaps
 *  heartRate: one value per 5 s window (watch), NaN when missing
 */
class SignalSnippet(
    val eventId: Long,
    val startMs: Long,                 // start of the first window
    val alarmMs: Long,
    val onsetMs: Long,
    val eeg: Array<FloatArray>,
    val movement: FloatArray,
    val heartRate: FloatArray,
) {
    val durationMs: Long get() = heartRate.size * WINDOW_MS

    companion object {
        const val WINDOW_MS = 5_000L
        const val PRE_WINDOWS = 24      // 2 min
        const val POST_WINDOWS = 60     // 5 min
        const val EEG_FS = 256
        const val MOV_FS = 25
        private const val VERSION = 1

        /** Compressed binary form (the database stores it encrypted). */
        fun encode(s: SignalSnippet): ByteArray {
            val bos = ByteArrayOutputStream()
            DataOutputStream(DeflaterOutputStream(bos)).use { o ->
                o.writeInt(VERSION); o.writeLong(s.eventId); o.writeLong(s.startMs); o.writeLong(s.alarmMs); o.writeLong(s.onsetMs)
                o.writeInt(s.eeg.size); for (ch in s.eeg) { o.writeInt(ch.size); ch.forEach(o::writeFloat) }
                o.writeInt(s.movement.size); s.movement.forEach(o::writeFloat)
                o.writeInt(s.heartRate.size); s.heartRate.forEach(o::writeFloat)
            }
            return bos.toByteArray()
        }

        fun decode(b: ByteArray): SignalSnippet = DataInputStream(InflaterInputStream(b.inputStream())).use { i ->
            require(i.readInt() == VERSION) { "unknown signal format" }
            val id = i.readLong(); val start = i.readLong(); val alarm = i.readLong(); val onset = i.readLong()
            val eeg = Array(i.readInt()) { FloatArray(i.readInt()) { i.readFloat() } }
            val mov = FloatArray(i.readInt()) { i.readFloat() }
            val hr = FloatArray(i.readInt()) { i.readFloat() }
            SignalSnippet(id, start, alarm, onset, eeg, mov, hr)
        }
    }
}

/**
 * Keeps the last 2 minutes of windows in memory; when an alarm comes it records the next 5 minutes and hands the
 * finished snippet to [save]. Nothing is kept unless [enabled] says the consent allows it.
 */
class SignalRecorder(private val enabled: () -> Boolean, private val save: (SignalSnippet) -> Unit) {
    private class W(val input: WindowInput, val endMs: Long)
    private val recent = ArrayDeque<W>()
    private var capture: Capture? = null

    private class Capture(val eventId: Long, val alarmMs: Long, val onsetMs: Long, val windows: MutableList<W>, val pre: Int, var after: Int = 0)

    fun add(w: WindowInput, endMs: Long) {
        if (!enabled()) { recent.clear(); capture = null; return }
        val x = W(w, endMs)
        recent.addLast(x); if (recent.size > SignalSnippet.PRE_WINDOWS) recent.removeFirst()
        capture?.let { c ->
            c.windows += x; c.after++
            if (c.after >= SignalSnippet.POST_WINDOWS) finish()
        }
    }

    /**
     * Late headband data (after a Bluetooth gap) for the window ending at [endMs]: the kept window and, if an
     * alarm recording is running, its copy get the real signals, so the doctor report shows no hole there.
     */
    fun replace(w: WindowInput, endMs: Long) {
        if (!enabled()) return
        val i = recent.indexOfLast { it.endMs == endMs }
        if (i >= 0) recent[i] = W(w, endMs)
        capture?.windows?.let { ws ->
            val j = ws.indexOfLast { it.endMs == endMs }
            if (j >= 0) ws[j] = W(w, endMs)
        }
    }

    /** Called right after the window that raised the alarm was added. */
    fun onAlarm(eventId: Long, alarmMs: Long, onsetMs: Long) {
        if (!enabled()) return
        if (capture != null) finish()                 // a new alarm closes the previous recording early
        capture = Capture(eventId, alarmMs, onsetMs, recent.toMutableList(), recent.size)
    }

    /** Monitoring / demo stops: keep what was recorded so far. */
    fun flush() { if (capture != null) finish() }

    private fun finish() {
        val c = capture ?: return
        capture = null
        if (c.windows.isEmpty()) return
        // the time line follows the window count (the alarm window ends at alarmMs), not the arrival times
        save(build(c.eventId, c.alarmMs, c.onsetMs, c.windows.map { it.input }, c.alarmMs - c.pre * SignalSnippet.WINDOW_MS))
    }

    companion object {
        /** Joins windows into one snippet (also used by the tests). */
        fun build(eventId: Long, alarmMs: Long, onsetMs: Long, windows: List<WindowInput>, startMs: Long): SignalSnippet {
            val nE = WindowFeatures.EEG_N; val nM = WindowFeatures.MOV_N
            val eeg = Array(2) { ch -> FloatArray(windows.size * nE) { k -> windows[k / nE].eegUv?.get(ch)?.getOrNull(k % nE) ?: Float.NaN } }
            val mov = FloatArray(windows.size * nM) { k ->
                val w = windows[k / nM]
                val axes = w.mov["head_acc"] ?: w.mov["body_acc"]
                if (axes == null) Float.NaN else {
                    val j = k % nM
                    val x = axes[0].getOrNull(j) ?: Float.NaN; val y = axes[1].getOrNull(j) ?: Float.NaN; val z = axes[2].getOrNull(j) ?: Float.NaN
                    sqrt(x * x + y * y + z * z)
                }
            }
            val hr = FloatArray(windows.size) { WindowFeatures.heartRate(windows[it].heartRate).toFloat() }
            return SignalSnippet(eventId, startMs, alarmMs, onsetMs, eeg, mov, hr)
        }
    }
}

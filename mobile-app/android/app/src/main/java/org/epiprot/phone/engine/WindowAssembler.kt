package org.epiprot.phone.engine

import org.epiprot.phone.model.WindowFeatures
import org.epiprot.phone.model.WindowInput
import org.epiprot.phone.protocol.SensorBatch

/**
 * Unit conversion from the devices to the units the model was trained with.
 *
 * ASSUMPTION, to be calibrated with the real hardware: SeizeIT2 movement is stored scaled to the
 * sensor's full range (1 g = ~0.5 in most recordings). A watch reports m/s^2 and rad/s.
 */
data class Calibration(
    val watchAccPerMs2: Float = 0.5f / 9.81f,
    val watchGyrPerRadS: Float = 57.2958f / 250f,
    val headAccScale: Float = 1f,
    val headGyrScale: Float = 1f,
)

/**
 * Collects the samples arriving from the headband (BLE) and the watch (Data Layer) into
 * 5 s windows on one timeline, and hands each window to the detector once it is complete
 * (window end + [latencyMs] for transmission delays). Samples for windows already handed
 * over are dropped. A sensor with no samples in a window is "missing" (null).
 */
class WindowAssembler(val startMs: Long, private val cal: Calibration = Calibration(), private val latencyMs: Long = 2_000) {
    private class Buf {
        val eeg = Array(2) { FloatArray(WindowFeatures.EEG_N) { Float.NaN } }
        var hasEeg = false
        val mov = HashMap<String, Array<FloatArray>>()
        val hr = ArrayList<Float>()
    }

    private val open = HashMap<Long, Buf>()
    private var nextIndex = 0L

    private fun index(tMs: Long) = Math.floorDiv(tMs - startMs, WINDOW_MS)
    private fun windowStart(i: Long) = startMs + i * WINDOW_MS
    private fun buf(i: Long): Buf? = if (i < nextIndex) null else open.getOrPut(i) { Buf() }

    private fun putMov(key: String, tMs: Long, x: Float, y: Float, z: Float) {
        val i = index(tMs)
        val b = buf(i) ?: return
        val slot = ((tMs - windowStart(i)) * WindowFeatures.MOV_FS / 1000).toInt()
        if (slot !in 0 until WindowFeatures.MOV_N) return
        val a = b.mov.getOrPut(key) { Array(3) { FloatArray(WindowFeatures.MOV_N) { Float.NaN } } }
        a[0][slot] = x; a[1][slot] = y; a[2][slot] = z
    }

    /** One watch packet (about 1 s): wrist movement and heart rate. */
    fun addWatch(b: SensorBatch) {
        for (s in b.acc) putMov("body_acc", b.startMs + s.offsetMs,
            s.x * cal.watchAccPerMs2, s.y * cal.watchAccPerMs2, s.z * cal.watchAccPerMs2)
        for (s in b.gyr) putMov("body_gyr", b.startMs + s.offsetMs,
            s.x * cal.watchGyrPerRadS, s.y * cal.watchGyrPerRadS, s.z * cal.watchGyrPerRadS)
        if (b.heartRate.isFinite()) buf(index(b.startMs))?.hr?.add(b.heartRate)
    }

    /** Headband EEG: consecutive samples at 256 Hz starting at [firstMs], microvolts. */
    fun addEeg(firstMs: Long, left: FloatArray, cross: FloatArray) {
        for (k in left.indices) {
            val rel = (firstMs - startMs) + k * 1000.0 / WindowFeatures.EEG_FS     // ms since start
            val i = Math.floorDiv(rel.toLong(), WINDOW_MS)
            val b = buf(i) ?: continue
            val slot = ((rel - i * WINDOW_MS) * WindowFeatures.EEG_FS / 1000 + 1e-6).toInt()
            if (slot !in 0 until WindowFeatures.EEG_N) continue
            b.eeg[0][slot] = left[k]; b.eeg[1][slot] = cross.getOrElse(k) { Float.NaN }; b.hasEeg = true
        }
    }

    /** Headband movement sample (25 Hz). */
    fun addHeadMovement(tMs: Long, acc: FloatArray, gyr: FloatArray) {
        putMov("head_acc", tMs, acc[0] * cal.headAccScale, acc[1] * cal.headAccScale, acc[2] * cal.headAccScale)
        putMov("head_gyr", tMs, gyr[0] * cal.headGyrScale, gyr[1] * cal.headGyrScale, gyr[2] * cal.headGyrScale)
    }

    /** All windows that are complete at [nowMs], oldest first, with their end times. */
    fun closeReady(nowMs: Long): List<Pair<WindowInput, Long>> {
        val out = ArrayList<Pair<WindowInput, Long>>()
        while (windowStart(nextIndex + 1) + latencyMs <= nowMs) {
            val b = open.remove(nextIndex)
            out += WindowInput(
                eegUv = b?.takeIf { it.hasEeg }?.eeg,
                mov = b?.mov ?: emptyMap(),
                heartRate = b?.hr?.toFloatArray() ?: FloatArray(0),
            ) to windowStart(nextIndex + 1)
            nextIndex++
        }
        return out
    }

    companion object { const val WINDOW_MS = 5_000L }
}

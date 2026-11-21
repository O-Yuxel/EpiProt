package org.epiprot.phone.engine

import org.epiprot.phone.headband.Channels
import org.epiprot.phone.model.WindowFeatures
import org.epiprot.phone.model.WindowInput
import org.epiprot.phone.protocol.SensorBatch
import kotlin.math.floor
import kotlin.math.roundToInt

/**
 * Unit conversion from the devices to the units the model was trained with.
 *
 * Head movement (the model uses it): SeizeIT2 stored movement in two scales a factor 3 apart; 43 of
 * the 55 tonic-clonic seizures the model learned from are in "group B": 1 g = 1/6 unit,
 * 1 unit = ~1016 °/s, measured from the data (python -m epiprot.headband.calibration; HARDWARE.md D14).
 * The headband reports g and °/s.
 * Watch movement (not a model input, only checked for presence): m/s^2 and rad/s, group-A scale.
 */
data class Calibration(
    val watchAccPerMs2: Float = 0.5f / 9.81f,
    val watchGyrPerRadS: Float = 57.2958f / 250f,
    val headAccPerG: Float = 1f / 6f,
    val headGyrPerDps: Float = 1f / 1016f,
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
        var eeg4: Array<FloatArray>? = null          // headband: 4 channels
        var leadOff = 0
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

    /**
     * Headband EEG, all 4 channels (µV, NaN = bad), consecutive samples at 256 Hz from [firstMs].
     * Samples go to their nearest slot: the headband clock and the EEG clock are both crystals, so
     * consecutive packets meet without gaps or overlaps. [leadOff] = electrodes without contact.
     */
    fun addHeadbandEeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) {
        val n = uv[0].size
        for (k in 0 until n) {
            val rel = firstMs - startMs + k * 1000.0 / WindowFeatures.EEG_FS
            var i = Math.floorDiv(rel.toLong(), WINDOW_MS)
            var slot = ((rel - i * WINDOW_MS) * WindowFeatures.EEG_FS / 1000).roundToInt()
            if (slot == WindowFeatures.EEG_N) { i += 1; slot = 0 }
            val b = buf(i) ?: continue
            val e = b.eeg4 ?: Array(4) { FloatArray(WindowFeatures.EEG_N) { Float.NaN } }.also { b.eeg4 = it }
            for (c in 0 until 4) e[c][slot] = uv[c][k]
            b.leadOff = b.leadOff or leadOff
        }
    }

    /**
     * Headband movement sample (25 Hz) in g and °/s. The sensor clock is locked to the headband
     * crystal (HARDWARE.md D13), so each sample goes to its nearest slot, values untouched.
     */
    fun addHeadMovement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) {
        val t = floor(tMs + 500.0 / WindowFeatures.MOV_FS).toLong()        // nearest slot
        putMov("head_acc", t, accG[0] * cal.headAccPerG, accG[1] * cal.headAccPerG, accG[2] * cal.headAccPerG)
        putMov("head_gyr", t, gyrDps[0] * cal.headGyrPerDps, gyrDps[1] * cal.headGyrPerDps, gyrDps[2] * cal.headGyrPerDps)
    }

    /** All windows that are complete at [nowMs], oldest first, with their end times. */
    fun closeReady(nowMs: Long): List<Pair<WindowInput, Long>> {
        val out = ArrayList<Pair<WindowInput, Long>>()
        while (windowStart(nextIndex + 1) + latencyMs <= nowMs) {
            val b = open.remove(nextIndex)
            val e4 = b?.eeg4
            val choice = e4?.let { Channels.choose(b.leadOff) }
            out += WindowInput(
                eegUv = if (e4 != null) arrayOf(e4[choice!!.first], e4[choice.second]) else b?.takeIf { it.hasEeg }?.eeg,
                mov = b?.mov ?: emptyMap(),
                heartRate = b?.hr?.toFloatArray() ?: FloatArray(0),
                contactBad = choice?.contactOk == false,
                channels = choice,
                leadOff = b?.leadOff ?: 0,
            ) to windowStart(nextIndex + 1)
            nextIndex++
        }
        return out
    }

    companion object { const val WINDOW_MS = 5_000L }
}

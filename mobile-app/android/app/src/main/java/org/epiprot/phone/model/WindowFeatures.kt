package org.epiprot.phone.model

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Raw data of one 5 s window, as the phone assembled it from the headband and the watch.
 * Missing samples are NaN; a sensor that sent nothing at all is null.
 *
 * @param eegUv   2 channels (left behind-the-ear, cross) x 1280 samples at 256 Hz, microvolts
 * @param mov     "head_acc", "head_gyr" (headband), "body_acc", "body_gyr" (watch):
 *                3 axes x 125 samples at 25 Hz, already in the model's units (see [Calibration])
 * @param heartRate heart-rate readings from the watch in this window (beats per minute)
 */
class WindowInput(
    val eegUv: Array<FloatArray>?,
    val mov: Map<String, Array<FloatArray>>,
    val heartRate: FloatArray,
)

/**
 * The 35 per-window features of the 5 s model, with exactly the formulas of
 * mobile-app/src/epiprot/gbm/tc_features.py (parity checked in the unit tests).
 * The heart rate comes from the watch instead of chest-ECG R-peaks.
 */
object WindowFeatures {
    const val WINDOW_S = 5.0
    const val EEG_FS = 256.0
    const val MOV_FS = 25.0
    val EEG_N = (WINDOW_S * EEG_FS).toInt()     // 1280
    val MOV_N = (WINDOW_S * MOV_FS).toInt()     // 125

    private val EEG_BANDS = listOf("delta" to (1.0 to 4.0), "theta" to (4.0 to 8.0), "alpha" to (8.0 to 13.0),
        "beta" to (13.0 to 30.0), "gamma" to (30.0 to 60.0))
    val MOV_KEYS = listOf("head_acc", "head_gyr", "body_acc", "body_gyr")

    val NAMES: List<String> = buildList {
        for (ch in listOf("L", "X")) {
            add("eeg${ch}_ll"); add("eeg${ch}_rms")
            EEG_BANDS.forEach { add("eeg${ch}_${it.first}") }
        }
        add("ecg_hr")
        for (k in MOV_KEYS) listOf("std", "p0_3", "p3_8", "p8_12", "rhythm").forEach { add("${k}_$it") }
    }

    fun compute(w: WindowInput): Map<String, Double> {
        val out = LinkedHashMap<String, Double>()
        for ((ci, ch) in listOf("L", "X").withIndex()) {
            val seg = w.eegUv?.getOrNull(ci)?.let { fit(it, EEG_N) } ?: DoubleArray(EEG_N) { Double.NaN }
            out["eeg${ch}_ll"] = log10(nanMeanAbsDiff(seg) + 1e-6)
            out["eeg${ch}_rms"] = log10(nanStd(seg) + 1e-6)
            for ((name, band) in EEG_BANDS) out["eeg${ch}_$name"] = bandPower(seg, EEG_FS, band.first, band.second)
        }
        out["ecg_hr"] = heartRate(w.heartRate)
        for (k in MOV_KEYS) {
            val axes = w.mov[k]
            if (axes == null || axes.size != 3) {
                listOf("std", "p0_3", "p3_8", "p8_12", "rhythm").forEach { out["${k}_$it"] = Double.NaN }
                continue
            }
            val a = axes.map { fit(it, MOV_N) }
            val mag = DoubleArray(MOV_N) { i -> sqrt(a[0][i] * a[0][i] + a[1][i] * a[1][i] + a[2][i] * a[2][i]) }
            out["${k}_std"] = log10(nanStd(mag) + 1e-6)
            out["${k}_p0_3"] = bandPower(mag, MOV_FS, 0.3, 3.0)
            out["${k}_p3_8"] = bandPower(mag, MOV_FS, 3.0, 8.0)
            out["${k}_p8_12"] = bandPower(mag, MOV_FS, 8.0, 12.4)
            out["${k}_rhythm"] = rhythm(mag, MOV_FS)
        }
        return out
    }

    /** Median of the valid readings; NaN with fewer than 2 (as the ECG version needs >= 2 beat intervals). */
    fun heartRate(hr: FloatArray): Double {
        val v = hr.filter { it.isFinite() && it in 25f..250f }.map { it.toDouble() }.sorted()
        if (v.size < 2) return Double.NaN
        return if (v.size % 2 == 1) v[v.size / 2] else (v[v.size / 2 - 1] + v[v.size / 2]) / 2
    }

    private fun fit(x: FloatArray, n: Int) = DoubleArray(n) { i -> if (i < x.size) x[i].toDouble() else Double.NaN }

    private fun nanMean(x: DoubleArray): Double {
        var s = 0.0; var c = 0
        for (v in x) if (!v.isNaN()) { s += v; c++ }
        return if (c == 0) Double.NaN else s / c
    }

    private fun nanStd(x: DoubleArray): Double {
        val m = nanMean(x)
        if (m.isNaN()) return Double.NaN
        var s = 0.0; var c = 0
        for (v in x) if (!v.isNaN()) { s += (v - m) * (v - m); c++ }
        return sqrt(s / c)
    }

    private fun nanMeanAbsDiff(x: DoubleArray): Double {
        var s = 0.0; var c = 0
        for (i in 1 until x.size) {
            val d = x[i] - x[i - 1]
            if (!d.isNaN()) { s += abs(d); c++ }
        }
        return if (c == 0) Double.NaN else s / c
    }

    /** Mean-removed, NaN -> 0 (numpy: nan_to_num(seg - nanmean(seg))). */
    private fun centered(x: DoubleArray): DoubleArray {
        val m = nanMean(x)
        return DoubleArray(x.size) { i -> val v = x[i] - m; if (v.isNaN()) 0.0 else v }
    }

    private val twiddles = HashMap<Int, Pair<DoubleArray, DoubleArray>>()

    private fun twiddle(n: Int) = synchronized(twiddles) {
        twiddles.getOrPut(n) { DoubleArray(n) { cos(2 * PI * it / n) } to DoubleArray(n) { sin(2 * PI * it / n) } }
    }

    /** log10(sum |rfft|^2 over lo <= f < hi / n + 1e-12), via a direct DFT of the needed bins only. */
    fun bandPower(x: DoubleArray, fs: Double, lo: Double, hi: Double): Double {
        val n = x.size
        val d = centered(x)
        val (c, s) = twiddle(n)
        var total = 0.0
        for (k in 0..n / 2) {
            val f = k * fs / n
            if (f < lo || f >= hi) continue
            var re = 0.0; var im = 0.0; var idx = 0
            for (t in 0 until n) {
                re += d[t] * c[idx]; im -= d[t] * s[idx]
                idx += k; if (idx >= n) idx -= n
            }
            total += re * re + im * im
        }
        return log10(total / n + 1e-12)
    }

    /** Strongest autocorrelation at 2-8 Hz lags relative to lag 0 (convulsion rhythmicity). */
    fun rhythm(x: DoubleArray, fs: Double): Double {
        val d = centered(x)
        fun ac(lag: Int): Double { var s = 0.0; for (t in 0 until d.size - lag) s += d[t] * d[t + lag]; return s }
        val lo = (fs / 8).toInt(); val hi = (fs / 2).toInt()
        var best = Double.NEGATIVE_INFINITY
        for (lag in lo..hi) best = maxOf(best, ac(lag))
        return best / (ac(0) + 1e-12)
    }
}

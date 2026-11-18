package org.epiprot.phone.model

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.ln
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * 30 s window features of model B, exactly as mobile-app/src/epiprot/gbm/tc30s_features.py:
 * per EEG channel a spectrogram (1 s Hann segments, 0.5 s hop, 1..40 Hz) and 23 spectral features
 * (formulas of epiprot.gbm.features.window_features), plus the watch heart rate (1 value per second):
 * mean, std, min, max, and hr_missing.
 */
object Features30s {
    const val FS = 256
    const val SEG = 256
    const val HOP = 128
    const val N = 30 * FS                    // 7680 samples
    val NSEG = (N - SEG) / HOP + 1           // 59
    const val NF = 40                        // 1..40 Hz
    const val MIN_HR_SECONDS = 15

    private val BANDS = listOf("delta" to (1 until 4), "theta" to (4 until 8), "alpha" to (8 until 13),
        "beta" to (13 until 30), "gamma" to (30 until 41))
    private val PER_CH = BANDS.map { "logpow_${it.first}" } + BANDS.map { "relpow_${it.first}" } +
        BANDS.map { "tvar_${it.first}" } +
        listOf("logpow_total", "tvar_total", "theta_alpha", "slow_fast", "spec_entropy", "sef90", "peak_freq", "peak_freq_lo")
    val NAMES: List<String> = listOf("eegL", "eegC").flatMap { c -> PER_CH.map { "${c}_$it" } } +
        listOf("hr_mean", "hr_std", "hr_min", "hr_max", "hr_missing")

    private val hann = DoubleArray(SEG) { 0.5 - 0.5 * cos(2 * PI * it / SEG) }     // periodic Hann
    private val hannPow = hann.sumOf { it * it }
    private val cosT = DoubleArray(SEG) { cos(2 * PI * it / SEG) }
    private val sinT = DoubleArray(SEG) { sin(2 * PI * it / SEG) }

    /** (40 x 59) dB spectrogram of one channel, rounded to float32 like the Python cache. */
    fun spectrogramDb(x: FloatArray): Array<FloatArray>? {
        if (x.size < N || (0 until N).any { x[it].isNaN() }) return null
        val out = Array(NF) { FloatArray(NSEG) }
        val seg = DoubleArray(SEG)
        for (s in 0 until NSEG) {
            var mean = 0.0
            for (i in 0 until SEG) { seg[i] = x[s * HOP + i].toDouble(); mean += seg[i] }
            mean /= SEG
            for (i in 0 until SEG) seg[i] = (seg[i] - mean) * hann[i]
            for (k in 1..NF) {
                var re = 0.0; var im = 0.0; var idx = 0
                for (t in 0 until SEG) {
                    re += seg[t] * cosT[idx]; im -= seg[t] * sinT[idx]
                    idx += k; if (idx >= SEG) idx -= SEG
                }
                val p = (re * re + im * im) * 2 / (FS * hannPow)
                out[k - 1][s] = (10 * log10(p + 1e-10)).toFloat()
            }
        }
        return out
    }

    /** The 23 spectral features of one channel from its dB spectrogram (NaN when the channel is missing). */
    fun spectral(db: Array<FloatArray>?): DoubleArray {
        if (db == null) return DoubleArray(PER_CH.size) { Double.NaN }
        val eps = 1e-12
        val p = Array(NF) { f -> DoubleArray(NSEG) { t -> 10.0.pow(db[f][t] / 10.0).toFloat().toDouble() } }
        val pm = DoubleArray(NF) { f -> p[f].sum() / NSEG }
        val total = pm.sum() + eps
        val bp = BANDS.associate { (b, r) -> b to (r.sumOf { pm[it - 1] } + eps) }
        fun std(v: DoubleArray): Double { val m = v.average(); return sqrt(v.sumOf { (it - m) * (it - m) } / v.size) }
        val out = ArrayList<Double>(PER_CH.size)
        BANDS.forEach { out += log10(bp.getValue(it.first)) }
        BANDS.forEach { out += bp.getValue(it.first) / total }
        BANDS.forEach { (_, r) -> out += std(DoubleArray(NSEG) { t -> log10(r.sumOf { p[it - 1][t] } + eps) }) }
        out += log10(total)
        out += std(DoubleArray(NSEG) { t -> log10((0 until NF).sumOf { p[it][t] } + eps) })
        out += log10(bp.getValue("theta") / bp.getValue("alpha"))
        out += log10((bp.getValue("delta") + bp.getValue("theta")) / (bp.getValue("alpha") + bp.getValue("beta")))
        val pn = DoubleArray(NF) { pm[it] / total }
        out += -pn.sumOf { it * ln(it + eps) } / ln(NF.toDouble())
        var cum = 0.0; var below = 0
        for (v in pn) { cum += v; if (cum < 0.9) below++ }
        out += (below.coerceIn(0, NF - 1) + 1).toDouble()
        out += (pm.indices.maxBy { pm[it] } + 1).toDouble()
        out += ((0 until 3).maxBy { pm[it] } + 1).toDouble()
        return out.toDoubleArray()
    }

    /**
     * @param eegLeft / eegCross 7680 samples (uV) or null
     * @param heartRate the watch's 1 Hz heart-rate values in the 30 s (NaN = no valid reading)
     * @param watchSent false when the watch sent nothing at all (-> hr_missing = 1)
     */
    fun compute(eegLeft: FloatArray?, eegCross: FloatArray?, heartRate: FloatArray, watchSent: Boolean): DoubleArray {
        val l = spectral(eegLeft?.let { spectrogramDb(it) })
        val c = spectral(eegCross?.let { spectrogramDb(it) })
        val v = heartRate.filter { it.isFinite() }.map { it.toDouble() }
        val hr = if (v.size >= MIN_HR_SECONDS) {
            val m = v.average()
            doubleArrayOf(m, sqrt(v.sumOf { (it - m) * (it - m) } / v.size), v.min(), v.max())
        } else DoubleArray(4) { Double.NaN }
        return l + c + hr + doubleArrayOf(if (watchSent) 0.0 else 1.0)
    }
}

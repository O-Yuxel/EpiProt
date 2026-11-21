package org.epiprot.phone.model

import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.max


/**
 * Turns the stream of 5 s base features into the model inputs, one window at a time
 * (streaming version of `expand()` in mobile-app/src/epiprot/gbm/tc_detect.py):
 *   x, x - mean(prev 1 min), x - mean(prev 10 min), mean/max of the last 15 s and 30 s,
 *   mean(last 60 s) - mean(prev 10 min).
 * Missing values are filled with the patient's running median for the context columns,
 * the first block keeps them missing (LightGBM handles NaN).
 */
class ContextExpander(private val nBase: Int, private val median: RunningMedian = RunningMedian(nBase)) {
    private val history = ArrayDeque<DoubleArray>()   // filled rows, newest last, at most LONG
    private var fixedMedian: DoubleArray? = null

    /** For tests: use a fixed median instead of the running one. */
    fun useFixedMedian(m: DoubleArray) { fixedMedian = m }

    fun next(base: DoubleArray): DoubleArray {
        require(base.size == nBase)
        median.add(base)
        val med = fixedMedian ?: median.current()
        val cur = DoubleArray(nBase) { i -> if (base[i].isNaN()) med[i] else base[i] }

        val prev12 = prevMean(12, cur)
        val prev120 = prevMean(120, cur)
        val out = DoubleArray(nBase * 8)
        for (i in 0 until nBase) {
            out[i] = base[i]
            out[nBase + i] = cur[i] - prev12[i]
            out[2 * nBase + i] = cur[i] - prev120[i]
        }
        val m3 = causal(3, cur, max = false); val x3 = causal(3, cur, max = true)
        val m6 = causal(6, cur, max = false); val x6 = causal(6, cur, max = true)
        val m12 = causal(12, cur, max = false)
        for (i in 0 until nBase) {
            out[3 * nBase + i] = m3[i]; out[4 * nBase + i] = x3[i]
            out[5 * nBase + i] = m6[i]; out[6 * nBase + i] = x6[i]
            out[7 * nBase + i] = m12[i] - prev120[i]
        }
        history.addLast(cur)
        if (history.size > LONG) history.removeFirst()
        return out
    }

    /**
     * Late data for a window already processed ([age] = how many windows ago, 0 = the latest): its
     * history row, which was filled with the running median while the data were missing, gets the
     * real values, so later windows compare against the true recent past.
     */
    fun replace(age: Int, base: DoubleArray) {
        require(base.size == nBase)
        if (age < 0 || age >= history.size) return
        median.add(base)
        val med = fixedMedian ?: median.current()
        history[history.size - 1 - age] = DoubleArray(nBase) { i -> if (base[i].isNaN()) med[i] else base[i] }
    }

    /** Mean of the previous w filled rows; the first window uses itself. */
    private fun prevMean(w: Int, cur: DoubleArray): DoubleArray {
        if (history.isEmpty()) return cur.copyOf()
        val n = minOf(w, history.size)
        val s = DoubleArray(nBase)
        for (r in history.size - n until history.size) { val row = history[r]; for (i in 0 until nBase) s[i] += row[i] }
        for (i in 0 until nBase) s[i] /= n
        return s
    }

    /** Mean or max over the last w rows including the current one. */
    private fun causal(w: Int, cur: DoubleArray, max: Boolean): DoubleArray {
        val out = cur.copyOf()
        val n = minOf(w - 1, history.size)
        for (r in history.size - n until history.size) {
            val row = history[r]
            for (i in 0 until nBase) out[i] = if (max) max(out[i], row[i]) else out[i] + row[i]
        }
        if (!max) for (i in 0 until nBase) out[i] /= (n + 1)
        return out
    }

    companion object { const val LONG = 120 }
}

/**
 * Approximate median of each feature over everything seen so far (bounded memory: a uniform
 * reservoir of [capacity] values per feature, re-evaluated every [every] windows).
 * The training data used the whole recording's median; a phone only knows the past.
 * A feature never seen yet counts as 0, as in training.
 */
class RunningMedian(private val n: Int, private val capacity: Int = 2048, private val every: Int = 12,
                    seed: Long = 1, private val withIqr: Boolean = false) {
    private var cachedIqr = DoubleArray(n) { 1.0 }
    private val rnd = java.util.Random(seed)
    private val store = Array(n) { DoubleArray(capacity) }
    private val count = IntArray(n)
    private val seen = LongArray(n)
    private var cached = DoubleArray(n)
    private var sinceUpdate = Int.MAX_VALUE / 2

    fun add(x: DoubleArray) {
        for (i in 0 until n) {
            val v = x[i]
            if (v.isNaN()) continue
            seen[i]++
            if (count[i] < capacity) store[i][count[i]++] = v
            else { val j = (rnd.nextDouble() * seen[i]).toLong(); if (j < capacity) store[i][j.toInt()] = v }
        }
        sinceUpdate++
    }

    fun current(): DoubleArray {
        if (sinceUpdate >= every || count.any { it in 1..every }) {
            val sorted = Array(n) { i -> store[i].copyOf(count[i]).also { it.sort() } }
            cached = DoubleArray(n) { i -> if (count[i] == 0) 0.0 else quantile(sorted[i], 0.5) }
            if (withIqr) cachedIqr = DoubleArray(n) { i ->
                val r = if (count[i] == 0) 0.0 else quantile(sorted[i], 0.75) - quantile(sorted[i], 0.25)
                if (r > 1e-6) r else 1.0
            }
            sinceUpdate = 0
        }
        return cached
    }

    /** Inter-quartile range (1 where it is ~0), valid after [current]. */
    fun iqr(): DoubleArray = cachedIqr

    /** numpy's default (linear) percentile of a sorted array. */
    private fun quantile(s: DoubleArray, q: Double): Double {
        val pos = q * (s.size - 1)
        val lo = pos.toInt(); val hi = minOf(lo + 1, s.size - 1)
        return s[lo] + (s[hi] - s[lo]) * (pos - lo)
    }
}

/** Score scaling: model probability -> its quantile among non-seizure windows (np.interp of a table). */
class ScaleTable(private val v: DoubleArray, private val q: DoubleArray) {
    fun scale(p: Double): Double {
        var lo = 0; var hi = v.size - 1
        if (p < v[0]) return q[0]
        if (p >= v[hi]) return q[hi]
        while (lo < hi) {                     // last index with v[j] <= p
            val mid = (lo + hi + 1) ushr 1
            if (v[mid] <= p) lo = mid else hi = mid - 1
        }
        val j = lo
        return if (v[j + 1] == v[j]) q[j] else q[j] + (q[j + 1] - q[j]) * (p - v[j]) / (v[j + 1] - v[j])
    }
}

/**
 * Alarm rule (tc_detect.alarms): mean of the last k scaled scores >= threshold, then no new alarm
 * for [refractory] windows.
 */
class AlarmRule(private val threshold: Double, private val k: Int, private val refractory: Int) {
    private val buf = ArrayDeque<Double>()
    private var index = -1L
    private var nextAllowed = 0L
    var lastSmoothed = 0.0
        private set

    fun next(score: Double): Boolean {
        index++
        buf.addLast(score); if (buf.size > k) buf.removeFirst()
        lastSmoothed = buf.sum() / buf.size
        if (lastSmoothed >= threshold && index >= nextAllowed) { nextAllowed = index + refractory; return true }
        return false
    }
}

/** Parsed assets/model/detector.json. */
class DetectorConfig(
    val baseFeatures: List<String>,
    val featuresA: List<String>, val scaleA: ScaleTable, val fileA: String,
    val featuresFb: List<String>, val scaleFb: ScaleTable, val fileFb: String,
    val fallbackWhenMissing: List<String>,
    val threshold: Double, val smoothK: Int, val refractory: Int,
    val lowLevel: Double, val endAfterLow: Int,
    val modelB: ModelBConfig? = null,
    val hrBackup: HrBackupConfig? = null,
) {
    companion object {
        fun parse(json: String): DetectorConfig {
            val j = JSONObject(json)
            fun strs(a: org.json.JSONArray) = List(a.length()) { a.getString(it) }
            fun dbls(a: org.json.JSONArray) = DoubleArray(a.length()) { a.getDouble(it) }
            val m = j.getJSONObject("models")
            val a = m.getJSONObject("a"); val fb = m.getJSONObject("a_fb")
            fun table(o: JSONObject) = o.getJSONObject("scale").let { ScaleTable(dbls(it.getJSONArray("v")), dbls(it.getJSONArray("q"))) }
            return DetectorConfig(
                strs(j.getJSONArray("base_features")),
                strs(a.getJSONArray("features")), table(a), a.getString("file"),
                strs(fb.getJSONArray("features")), table(fb), fb.getString("file"),
                strs(j.getJSONArray("fallback_when_missing")),
                j.getDouble("threshold"), j.getInt("smooth_k"), j.getInt("refractory_windows"),
                j.getDouble("low_level"), j.getInt("end_after_low_windows"),
                j.optJSONObject("model_b")?.let { b ->
                    ModelBConfig(b.getString("file"), strs(b.getJSONArray("base_features")), strs(b.getJSONArray("features")), table(b))
                },
                j.optJSONObject("heart_rate_backup")?.let { h ->
                    val ha = h.getJSONObject("a"); val hb = h.getJSONObject("b")
                    HrBackupConfig(h.getString("when_missing"), h.optDouble("stuck_bpm", 0.0), h.optInt("stuck_windows", 12),
                        ha.getString("file"), strs(ha.getJSONArray("features")), table(ha),
                        hb.getString("file"), strs(hb.getJSONArray("features")), table(hb))
                },
            )
        }
    }
}

class ModelBConfig(val file: String, val baseFeatures: List<String>, val features: List<String>, val scale: ScaleTable)

/**
 * Heart-rate backup: while the watch sends no heart rate ([whenMissing] is missing), the 5 s model A_nohr
 * (EEG + headband movement) and the 30 s model B_nohr (EEG spectrum) are used instead. They never saw a heart
 * rate, so a heart rate that drops out (watch off, optical sensor lost during a convulsion) cannot fool them.
 */
class HrBackupConfig(
    val whenMissing: String,
    /** Heart rate that varied less than [stuckBpm] over the last [stuckWindows] windows counts as missing (stuck optical sensor). 0 = off. */
    val stuckBpm: Double = 0.0, val stuckWindows: Int = 12,
    val fileA: String, val featuresA: List<String>, val scaleA: ScaleTable,
    val fileB: String, val featuresB: List<String>, val scaleB: ScaleTable,
)

/** All model files of the detector. */
class DetectorModels(val a: Gbdt, val fb: Gbdt, val b: Gbdt? = null, val aNohr: Gbdt? = null, val bNohr: Gbdt? = null) {
    companion object {
        /** [read] returns the text of a file in assets/model/. */
        fun load(cfg: DetectorConfig, read: (String) -> String): DetectorModels {
            fun m(f: String) = Gbdt.parse(read(f))
            return DetectorModels(m(cfg.fileA), m(cfg.fileFb), cfg.modelB?.let { m(it.file) },
                cfg.hrBackup?.let { m(it.fileA) }, cfg.hrBackup?.let { m(it.fileB) })
        }
    }
}

/**
 * Change features of the 30 s model (detect.make_features "both"): the window's values (missing ->
 * median), and (x - mean of the previous 5 min), (x - mean of the previous 60 min), (x - previous window),
 * each divided by the patient's inter-quartile range. Training used the whole recording's median / IQR;
 * the phone uses running estimates over the past.
 */
class ChangeExpander30(private val n: Int) {
    private val stats = RunningMedian(n, withIqr = true)
    private val history = ArrayDeque<DoubleArray>()
    private var fixed: Pair<DoubleArray, DoubleArray>? = null

    fun useFixed(median: DoubleArray, iqr: DoubleArray) { fixed = median to iqr }

    /** Late data for a 30 s block already processed ([age] blocks ago): see ContextExpander.replace. */
    fun replace(age: Int, base: DoubleArray) {
        if (age < 0 || age >= history.size) return
        stats.add(base)
        val med = fixed?.first ?: stats.current()
        history[history.size - 1 - age] = DoubleArray(n) { if (base[it].isNaN()) med[it] else base[it] }
    }

    fun next(base: DoubleArray): DoubleArray {
        stats.add(base)
        val (med, iqr) = fixed ?: (stats.current() to stats.iqr())
        val cur = DoubleArray(n) { if (base[it].isNaN()) med[it] else base[it] }
        fun prevMean(w: Int): DoubleArray {
            if (history.isEmpty()) return cur.copyOf()
            val k = minOf(w, history.size)
            val s = DoubleArray(n)
            for (r in history.size - k until history.size) for (i in 0 until n) s[i] += history[r][i]
            return DoubleArray(n) { s[it] / k }
        }
        val p10 = prevMean(10); val p120 = prevMean(120)
        val prev = history.lastOrNull() ?: cur
        val out = DoubleArray(4 * n)
        for (i in 0 until n) {
            out[i] = cur[i]
            out[n + i] = (cur[i] - p10[i]) / iqr[i]
            out[2 * n + i] = (cur[i] - p120[i]) / iqr[i]
            out[3 * n + i] = (cur[i] - prev[i]) / iqr[i]
        }
        history.addLast(cur); if (history.size > 120) history.removeFirst()
        return out
    }
}

/**
 * Model B: every 30 s (6 windows) it computes the 30 s features from the raw headband EEG and the
 * watch heart rate; its scaled score is held until the next 30 s window (as tc_ensemble.map30to5).
 */
class ModelB(private val cfg: ModelBConfig, private val model: Gbdt,
             private val backup: HrBackupConfig? = null, private val modelNohr: Gbdt? = null) {
    private val expander = ChangeExpander30(cfg.baseFeatures.size)
    private val buf = ArrayList<WindowInput>(6)
    private val raws = ArrayDeque<WindowInput>()        // last windows, for late data (newest last)
    private var seen = 0L
    var heldScore = 0.0
        private set
    /** Held scaled score of the backup model without heart rate. */
    var heldScoreNohr = 0.0
        private set
    private val idxNohr: IntArray? = backup?.featuresB?.map {
        cfg.features.indexOf(it).also { i -> require(i >= 0) { "unknown 30 s feature $it" } }
    }?.toIntArray()

    init {
        require(cfg.baseFeatures == Features30s.NAMES) { "30 s feature names differ from Features30s" }
        require(model.numFeatures == cfg.features.size) { "model B / config mismatch" }
        if (backup != null) require(modelNohr != null && modelNohr.numFeatures == idxNohr!!.size) { "model B_nohr / config mismatch" }
    }

    /** Feed one 5 s window; returns the (possibly new) held scaled score. */
    fun next(w: WindowInput?): Double {
        val win = w ?: WindowInput(null, emptyMap(), FloatArray(0))
        buf += win
        raws.addLast(win); if (raws.size > KEEP) raws.removeFirst()
        seen++
        if (buf.size < 6) return heldScore
        val base = base30(buf)
        buf.clear()
        val x = expander.next(base)
        heldScore = cfg.scale.scale(model.predict(x))
        if (idxNohr != null) heldScoreNohr = backup!!.scaleB.scale(modelNohr!!.predict(DoubleArray(idxNohr.size) { x[idxNohr[it]] }))
        return heldScore
    }

    private fun base30(ws: List<WindowInput>): DoubleArray {
        val n5 = WindowFeatures.EEG_N
        fun eeg(ch: Int): FloatArray? =
            if (ws.any { it.eegUv == null }) null
            else FloatArray(6 * n5) { ws[it / n5].eegUv!![ch][it % n5] }
        val hr = ws.flatMap { it.heartRate.toList() }.toFloatArray()
        val watchSent = ws.any { it.heartRate.isNotEmpty() || it.mov.containsKey("body_acc") }
        return Features30s.compute(eeg(0), eeg(1), hr, watchSent)
    }

    /** Late data for the window [age] windows ago: recompute its 30 s block's history row (no new score). */
    fun backfill(age: Int, w: WindowInput) {
        if (age < 0 || age >= raws.size) return
        raws[raws.size - 1 - age] = w
        val idx = seen - 1 - age                       // window number since the start
        val block = idx / 6
        val done = seen / 6                            // blocks already scored
        if (block >= done) { buf[(idx % 6).toInt()] = w; return }   // block still being collected
        val first = (block * 6 - (seen - raws.size)).toInt()        // position of the block in raws
        if (first < 0) return
        expander.replace((done - 1 - block).toInt(), base30(List(6) { raws[first + it] }))
    }

    companion object { const val KEEP = 132 }
}

/** Result of one 5 s window. Times are window indices since monitoring started. */
data class WindowResult(
    val index: Long,
    val probability: Double,
    val score: Double,           // scaled 0..1
    val smoothed: Double,
    val fallback: Boolean,       // no movement data -> backup model
    val alarm: Boolean,
    val onsetIndex: Long?,       // estimated seizure start (on an alarm)
    val seizureEndedIndex: Long?,// last seizure-like window, when the seizure is over
    val noHeartRate: Boolean = false, // no heart rate from the watch -> models without heart rate
)

/**
 * The EpiProt detector: model A (EEG + heart + movement) or, when the movement sensor sends nothing,
 * the backup model A' (EEG + heart), or, when the watch sends no heart rate, A_nohr (EEG + movement);
 * max with the held 30 s score (B, or B_nohr without heart rate); scaled score, smoothing over k
 * windows, threshold, 5 min refractory period after each alarm.
 */
class Detector(private val cfg: DetectorConfig, private val modelA: Gbdt, private val modelFb: Gbdt,
               modelB: Gbdt? = null, private val modelANohr: Gbdt? = null, modelBNohr: Gbdt? = null,
               private val roundToHalf: Boolean = true) {
    constructor(cfg: DetectorConfig, m: DetectorModels) : this(cfg, m.a, m.fb, m.b, m.aNohr, m.bNohr)

    private val hb = cfg.hrBackup
    private val b: ModelB? = cfg.modelB?.let { c ->
        ModelB(c, requireNotNull(modelB) { "model B file missing" }, hb, modelBNohr)
    }
    private val expander = ContextExpander(cfg.baseFeatures.size)
    private val xNames: List<String> = buildList {
        val b = cfg.baseFeatures
        addAll(b)
        listOf("@d1m", "@d10m", "@mean15s", "@max15s", "@mean30s", "@max30s", "@mean60s-d10m")
            .forEach { s -> b.forEach { add(it + s) } }
    }
    private val idxA = cfg.featuresA.map { xNames.indexOf(it).also { i -> require(i >= 0) { "unknown feature $it" } } }.toIntArray()
    private val idxFb = cfg.featuresFb.map { xNames.indexOf(it).also { i -> require(i >= 0) { "unknown feature $it" } } }.toIntArray()
    private val fbIdx = cfg.fallbackWhenMissing.map { cfg.baseFeatures.indexOf(it) }
    private val idxNohr = hb?.featuresA?.map { xNames.indexOf(it).also { i -> require(i >= 0) { "unknown feature $it" } } }?.toIntArray()
    private val recentHr = ArrayDeque<Double>()        // last heart-rate values, for the stuck-sensor check
    private val hrIdx = hb?.let { cfg.baseFeatures.indexOf(it.whenMissing).also { i -> require(i >= 0) { "unknown feature ${it.whenMissing}" } } }
    private val recent = ArrayDeque<Double>()          // scaled scores, for the onset estimate
    private val rule = AlarmRule(cfg.threshold, cfg.smoothK, cfg.refractory)
    private var index = -1L
    private var active = false
    private var below = 0

    init {
        require(modelA.numFeatures == idxA.size && modelFb.numFeatures == idxFb.size) { "model / config mismatch" }
        if (hb != null) require(modelANohr != null && modelANohr.numFeatures == idxNohr!!.size) { "model A_nohr / config mismatch" }
    }

    val seizureActive: Boolean get() = active

    /** One 5 s window: its base features and (for model B) its raw data. */
    fun next(features: Map<String, Double>, raw: WindowInput? = null): WindowResult =
        next(DoubleArray(cfg.baseFeatures.size) { features[cfg.baseFeatures[it]] ?: Double.NaN }, raw)

    fun next(base: DoubleArray, raw: WindowInput? = null): WindowResult {
        index++
        val x = expander.next(base)
        if (roundToHalf) for (i in x.indices) x[i] = toHalf(x[i])
        val fallback = fbIdx.all { base[it].isNaN() }
        val stuck = hrIdx != null && hrStuck(base[hrIdx])          // records every value, also missing ones
        val noHr = hrIdx != null && (base[hrIdx].isNaN() || stuck)
        val p: Double
        val s5: Double
        when {
            noHr -> { p = modelANohr!!.predict(DoubleArray(idxNohr!!.size) { x[idxNohr[it]] }); s5 = hb!!.scaleA.scale(p) }
            fallback -> { p = modelFb.predict(DoubleArray(idxFb.size) { x[idxFb[it]] }); s5 = cfg.scaleFb.scale(p) }
            else -> { p = modelA.predict(DoubleArray(idxA.size) { x[idxA[it]] }); s5 = cfg.scaleA.scale(p) }
        }
        val s = if (b != null) {                                      // rule "max"
            b.next(raw)
            maxOf(s5, if (noHr) b.heldScoreNohr else b.heldScore)
        } else s5

        val alarm = rule.next(s)
        val sm = rule.lastSmoothed
        recent.addLast(s); if (recent.size > MAX_ONSET_LOOKBACK) recent.removeFirst()

        var onset: Long? = null
        if (alarm) {
            var back = 0                     // walk back while the score stayed high
            while (back + 1 < recent.size && recent[recent.size - 2 - back] >= cfg.lowLevel) back++
            onset = index - back
            active = true
            below = 0
        }
        var ended: Long? = null
        if (active && !alarm) {
            below = if (s < cfg.lowLevel) below + 1 else 0
            if (below >= cfg.endAfterLow) { active = false; ended = index - below }
        }
        return WindowResult(index, p, s, sm, fallback, alarm, onset, ended, noHr)
    }

    /**
     * Late data (headband catch-up after a Bluetooth gap) for the window [age] windows ago, 0 = the
     * latest: the models' memory of the recent past gets the real values instead of the stand-ins used
     * while the data were missing. No score or alarm for the past window; later windows benefit.
     */
    fun backfill(age: Int, features: Map<String, Double>, raw: WindowInput) {
        if (age < 0 || age >= ContextExpander.LONG) return
        expander.replace(age, DoubleArray(cfg.baseFeatures.size) { features[cfg.baseFeatures[it]] ?: Double.NaN })
        b?.backfill(age, raw)
    }

    /**
     * A real heart rate always moves; one that hardly changed over the last minute comes from a stuck sensor and must
     * not hide a seizure the headband sees (same rule as stuck_mask in mobile-app/src/epiprot/gbm/hr_robustness.py).
     */
    private fun hrStuck(hr: Double): Boolean {
        val b = hb ?: return false
        recentHr.addLast(hr); if (recentHr.size > b.stuckWindows) recentHr.removeFirst()
        if (b.stuckBpm <= 0 || recentHr.size < b.stuckWindows || recentHr.any { it.isNaN() }) return false
        return recentHr.max() - recentHr.min() < b.stuckBpm
    }

    companion object {
        const val MAX_ONSET_LOOKBACK = 720   // 1 h

        /** Round to the nearest IEEE half-precision value (the models were trained on float16 features). */
        fun toHalf(v: Double): Double {
            if (v.isNaN() || v.isInfinite() || v == 0.0) return v
            val a = abs(v)
            if (a >= 65520.0) return if (v > 0) Double.POSITIVE_INFINITY else Double.NEGATIVE_INFINITY
            val f = a.toFloat().toDouble()               // float32 first, as numpy does
            val step = if (f < 6.103515625e-05) 5.9604644775390625e-08 else Math.scalb(1.0, Math.getExponent(f) - 10)
            val r = Math.rint(f / step) * step
            return if (v < 0) -r else r
        }
    }
}

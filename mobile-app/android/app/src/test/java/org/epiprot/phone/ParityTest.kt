package org.epiprot.phone

import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.model.AlarmRule
import org.epiprot.phone.model.ContextExpander
import org.epiprot.phone.model.DetectorConfig
import org.epiprot.phone.model.Gbdt
import org.epiprot.phone.model.WindowFeatures
import org.epiprot.phone.model.WindowInput
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max

/** The phone code must give the same numbers as the Python code the model was trained and evaluated with. */
object Fixtures {
    fun json(name: String) = JSONObject(File("src/test/resources/fixtures/$name").readText())
    fun asset(name: String) = File("src/main/assets/model/$name").readText()
    val config by lazy { DetectorConfig.parse(asset("detector.json")) }
    val modelA by lazy { Gbdt.parse(asset("model_a.txt")) }
    val modelFb by lazy { Gbdt.parse(asset("model_a_fb.txt")) }
    val modelB by lazy { config.modelB?.let { Gbdt.parse(asset(it.file)) } }
    val models by lazy { org.epiprot.phone.model.DetectorModels.load(config) { asset(it) } }

    fun JSONArray.doubles() = DoubleArray(length()) { if (isNull(it)) Double.NaN else getDouble(it) }
    fun JSONArray.floats() = FloatArray(length()) { getDouble(it).toFloat() }
    fun JSONArray.strings() = List(length()) { getString(it) }
}

class ParityTest {
    private fun close(msg: String, want: Double, got: Double, tol: Double) {
        if (want.isNaN()) { assertTrue("$msg: want NaN, got $got", got.isNaN()); return }
        assertTrue("$msg: want $want, got $got", abs(want - got) <= tol * max(1.0, abs(want)))
    }

    @Test
    fun windowFeaturesMatchPython() = with(Fixtures) {
        val j = json("windows.json")
        val ws = j.getJSONArray("windows")
        for (wi in 0 until ws.length()) {
            val w = ws.getJSONObject(wi)
            val eeg = w.getJSONArray("eeg_uv").let { a -> Array(2) { a.getJSONArray(it).floats() } }
            val mj = w.getJSONObject("mov")
            val mov = WindowFeatures.MOV_KEYS.associateWith { k -> mj.getJSONArray(k).let { a -> Array(3) { a.getJSONArray(it).floats() } } }
            val got = WindowFeatures.compute(WindowInput(eeg, mov, FloatArray(0)))
            val want = w.getJSONObject("features")
            for (name in want.keys()) {
                val v = if (want.isNull(name)) Double.NaN else want.getDouble(name)
                close("window ${w.getInt("index")} $name", v, got.getValue(name), 2e-4)
            }
        }
    }

    @Test
    fun features30sMatchPython() = with(Fixtures) {
        val j = json("windows30.json")
        assertEquals(org.epiprot.phone.model.Features30s.NAMES, j.getJSONArray("names").strings())
        val ws = j.getJSONArray("windows")
        for (wi in 0 until ws.length()) {
            val w = ws.getJSONObject(wi)
            val e = w.getJSONArray("eeg")
            val hr = w.getJSONArray("hr").let { a -> FloatArray(a.length()) { if (a.isNull(it)) Float.NaN else a.getDouble(it).toFloat() } }
            val got = org.epiprot.phone.model.Features30s.compute(e.getJSONArray(0).floats(), e.getJSONArray(1).floats(), hr, true)
            val want = w.getJSONArray("features").doubles()
            val names = org.epiprot.phone.model.Features30s.NAMES
            for (k in want.indices) close("30s window $wi ${names[k]}", want[k], got[k], 2e-4)
        }
    }

    @Test
    fun modelBExpansionAndPredictionMatchPython() = with(Fixtures) {
        val cb = config.modelB ?: return@with
        val j = json("expand30.json")
        assertEquals(cb.baseFeatures, j.getJSONArray("base").strings())
        val e = org.epiprot.phone.model.ChangeExpander30(cb.baseFeatures.size)
        e.useFixed(j.getJSONArray("median").doubles(), j.getJSONArray("iqr").doubles())
        val hist = j.getJSONArray("history")
        for (r in 0 until hist.length()) e.next(hist.getJSONArray(r).doubles())
        val F = j.getJSONArray("F"); val X = j.getJSONArray("X"); val pred = j.getJSONArray("pred_b").doubles()
        for (r in 0 until F.length()) {
            val got = e.next(F.getJSONArray(r).doubles())
            val want = X.getJSONArray(r).doubles()
            for (c in want.indices) close("30s row $r ${cb.features[c]}", want[c], got[c], 1e-4)
            close("pred_b row $r", pred[r], modelB!!.predict(want), 1e-9)
        }
        val hb = config.hrBackup ?: return@with
        val predH = j.getJSONArray("pred_b_nohr").doubles()
        val idx = hb.featuresB.map { cb.features.indexOf(it) }
        for (r in 0 until X.length()) {
            val row = X.getJSONArray(r).doubles()
            close("pred_b_nohr row $r", predH[r], models.bNohr!!.predict(DoubleArray(idx.size) { row[idx[it]] }), 1e-9)
        }
    }

    @Test
    fun contextExpansionMatchesPython() = with(Fixtures) {
        val j = json("expand.json")
        val base = j.getJSONArray("base").strings()
        assertEquals(config.baseFeatures, base)
        val e = ContextExpander(base.size).apply { useFixedMedian(j.getJSONArray("median").doubles()) }
        val F = j.getJSONArray("F"); val X = j.getJSONArray("X"); val cols = j.getJSONArray("X_cols").strings()
        for (r in 0 until F.length()) {
            val got = e.next(F.getJSONArray(r).doubles())
            val want = X.getJSONArray(r).doubles()
            for (c in want.indices) close("row $r ${cols[c]}", want[c], got[c], 1e-4)
        }
    }

    @Test
    fun modelsMatchLightGbm() = with(Fixtures) {
        val j = json("expand.json")
        val cols = j.getJSONArray("X_cols").strings()
        val X = j.getJSONArray("X")
        val cases = mutableListOf(Triple(modelA, config.featuresA, "pred_a"), Triple(modelFb, config.featuresFb, "pred_a_fb"))
        config.hrBackup?.let { cases += Triple(models.aNohr!!, it.featuresA, "pred_a_nohr") }
        for ((model, feats, key) in cases) {
            val idx = feats.map { cols.indexOf(it) }
            val want = j.getJSONArray(key).doubles()
            assertEquals(400, model.numTrees)
            for (r in 0 until X.length()) {
                val row = X.getJSONArray(r).doubles()
                close("$key row $r", want[r], model.predict(DoubleArray(idx.size) { row[idx[it]] }), 1e-9)
            }
        }
    }

    @Test
    fun scoreScalingAndAlarmRuleMatchPython() = with(Fixtures) {
        val j = json("alarms.json")
        val sc = j.getJSONObject("scale_check")
        val raw = sc.getJSONArray("raw").doubles(); val scaled = sc.getJSONArray("scaled").doubles()
        for (i in raw.indices) close("scale $i", scaled[i], config.scaleA.scale(raw[i]), 1e-9)

        assertEquals(config.threshold, j.getDouble("threshold"), 0.0)
        val rule = AlarmRule(j.getDouble("threshold"), j.getInt("k"), j.getInt("refractory"))
        val score = j.getJSONArray("score").doubles()
        val got = score.indices.filter { rule.next(score[it]) }
        val want = j.getJSONArray("alarms").let { a -> List(a.length()) { a.getInt(it) } }
        assertEquals(want, got)
    }

    @Test
    fun healthMonitorMatchesPython() = with(Fixtures) {
        val cases = JSONArray(File("src/test/resources/fixtures/health.json").readText())
        val qv = HealthMonitor.Quality.entries
        for (ci in 0 until cases.length()) {
            val c = cases.getJSONObject(ci)
            val q = c.getJSONObject("q")
            val keys = listOf("brain", "head_mov", "heart", "body_mov")
            val s = keys.associateWith { q.getString(it) }
            val n = s.getValue("brain").length
            val busy = BooleanArray(n)
            c.getJSONArray("busy_s").let { b ->
                for (k in 0 until b.length()) {
                    val iv = b.getJSONArray(k)
                    for (i in (iv.getDouble(0) / 5).toInt() until minOf(n, ceil(iv.getDouble(1) / 5).toInt())) busy[i] = true
                }
            }
            val m = HealthMonitor()
            val warned = ArrayList<HealthMonitor.Episode>()
            for (i in 0 until n) {
                val w = keys.associateWith { qv[s.getValue(it)[i] - '0'] }
                for (e in m.next(w, (i + 1) * 5_000L, busy[i])) if (e is HealthMonitor.Event.Warning) warned += e.episode
            }
            val want = c.getJSONArray("episodes")
            assertEquals("${c.getString("sub")}: number of warnings", want.length(), warned.size)
            val got = warned.sortedBy { it.warnedMs }
            for (k in 0 until want.length()) {
                val we = want.getJSONObject(k); val ge = got[k]
                val tag = "${c.getString("sub")} warning $k"
                assertEquals(tag, we.getString("device"), ge.device)
                assertEquals(tag, we.getString("code"), ge.code)
                assertEquals(tag, we.getString("impact"), ge.impact)
                assertEquals(tag, we.getString("problem"), ge.problem)
                assertEquals(tag, (we.getDouble("warned_s") * 1000).toLong(), ge.warnedMs)
                if (we.isNull("fixed_s")) assertEquals(tag, null, ge.fixedMs)
                else assertEquals(tag, (we.getDouble("fixed_s") * 1000).toLong(), ge.fixedMs)
                assertEquals(tag, we.getJSONArray("reminders").doubles().map { (it * 1000).toLong() }, ge.reminders)
            }
        }
    }
}

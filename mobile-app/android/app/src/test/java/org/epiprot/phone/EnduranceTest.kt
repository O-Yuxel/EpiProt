package org.epiprot.phone

import org.epiprot.phone.alarm.FlowEffect
import org.epiprot.phone.engine.DemoRecording
import org.epiprot.phone.engine.EngineActions
import org.epiprot.phone.engine.MonitoringEngine
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.protocol.PhoneMessage
import org.epiprot.phone.signals.SignalRecorder
import org.epiprot.phone.signals.SignalSnippet
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Long run of the whole phone chain (features, both models, backups, alarm flow, health monitor, signal recorder):
 * the demo recording (15 min with one tonic-clonic seizure) is replayed again and again with continuous time stamps.
 * Default 2 h (fast); the full day: gradlew test -PenduranceHours=24
 */
class EnduranceTest {
    private class Actions : EngineActions {
        var events = 0L; var sms = 0; var watch = 0
        override fun newDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean) = ++events
        override fun flow(effect: FlowEffect, demo: Boolean) { if (effect is FlowEffect.Sms) sms++ }
        override fun sensor(event: HealthMonitor.Event, demo: Boolean) {}
        override fun watch(message: PhoneMessage) { watch++ }
    }

    private fun usedMb(): Double { repeat(3) { System.gc(); Thread.sleep(50) }; val r = Runtime.getRuntime(); return (r.totalMemory() - r.freeMemory()) / 1e6 }

    @Test
    fun runsForHoursWithoutSlowingDownOrGrowing() = with(Fixtures) {
        val hours = (System.getProperty("endurance.hours") ?: "2").toDouble()
        val n = (hours * 720).toInt()
        val demo = DemoRecording.parse(File("src/main/assets/demo/demo_seizure.bin").readBytes())
        val act = Actions()
        val engine = MonitoringEngine(config, models, act)
        var saved = 0
        val recorder = SignalRecorder({ true }) { saved++; SignalSnippet.encode(it) }
        val t0 = 1_800_000_000_000L
        val times = LongArray(n)
        var mem25 = 0.0
        val mem0 = usedMb()
        var alarms = 0
        for (i in 0 until n) {
            val w = demo.windows[i % demo.windows.size]
            val end = t0 + (i + 1) * 5_000L
            val s = System.nanoTime()
            recorder.add(w, end)
            val r = engine.onWindow(w, end)
            if (r.alarm) { alarms++; recorder.onAlarm(act.events, end, end) }
            times[i] = System.nanoTime() - s
            if (i == n / 4) mem25 = usedMb()
        }
        val memEnd = usedMb()
        val sorted = times.sorted()
        val meanMs = times.average() / 1e6
        val p99 = sorted[(n * 0.99).toInt()] / 1e6
        val cycles = n / demo.windows.size
        println("endurance: %.1f h = %d windows, %.2f ms/window (99%%: %.2f ms), alarms %d in %d replays, SMS %d, snippets %d, memory %.1f -> %.1f -> %.1f MB"
            .format(hours, n, meanMs, p99, alarms, cycles, act.sms, saved, mem0, mem25, memEnd))
        // one alarm per replayed seizure (5 min refractory, recovery flow in between), nothing missed after hours
        assertTrue("alarms $alarms for $cycles seizures", alarms >= cycles - 1 && alarms <= cycles + 1)
        assertTrue("signal snippets $saved", saved >= alarms - 1)
        // fast enough: a 5 s window must take a tiny fraction of 5 s (this PC; a phone is ~5-10x slower)
        assertTrue("mean %.2f ms".format(meanMs), meanMs < 100)
        // no memory growth between the first quarter and the end (bounded buffers)
        assertTrue("memory grew %.1f -> %.1f MB".format(mem25, memEnd), memEnd - mem25 < 30)
    }
}

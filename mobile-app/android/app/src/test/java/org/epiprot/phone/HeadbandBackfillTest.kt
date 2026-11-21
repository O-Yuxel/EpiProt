package org.epiprot.phone

import org.epiprot.phone.alarm.FlowEffect
import org.epiprot.phone.engine.EngineActions
import org.epiprot.phone.engine.MonitoringEngine
import org.epiprot.phone.headband.HeadbandPipeline
import org.epiprot.phone.headband.HeadbandReceiver
import org.epiprot.phone.headband.HeadbandStream
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.protocol.PhoneMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The real Bluetooth test (device-firmware/README.md): the phone's Bluetooth was off for ~97 s, about
 * 5 min before the seizure; the headband stored the data and sent them after reconnecting. Without
 * using those data for the model's memory the alarm came 85-88 s after onset instead of 15 s.
 */
class HeadbandBackfillTest {
    private class Rec : EngineActions {
        val alarms = ArrayList<Long>()
        override fun newDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean) = 1L.also { alarms += alarmMs }
        override fun flow(effect: FlowEffect, demo: Boolean) {}
        override fun sensor(event: HealthMonitor.Event, demo: Boolean) {}
        override fun watch(message: PhoneMessage) {}
    }

    private val stream = HeadbandStream.parse(File("src/main/assets/demo/headband_demo.ehb").readBytes())
    private val base = 1_000_000_000L

    /** Alarm time in seconds after the seizure onset, and how many past windows got late data. */
    private fun run(gap: LongRange?, backfill: Boolean): Pair<Double, Int> = with(Fixtures) {
        val rec = Rec()
        val engine = MonitoringEngine(config, models, rec)
        engine.reset(false)
        var pipe: HeadbandPipeline? = null
        val sink = object : org.epiprot.phone.headband.HeadbandSink {
            fun p(ms: Double) = pipe ?: HeadbandPipeline(ms.toLong(), { w, end -> engine.onWindow(w, end) },
                { w, end -> if (backfill) engine.onLateWindow(w, end) }).also { pipe = it }
            override fun eeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) = p(firstMs).eeg(firstMs, uv, leadOff)
            override fun movement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) { pipe?.movement(tMs, accG, gyrDps) }
            override fun lateEeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) { pipe?.lateEeg(firstMs, uv, leadOff) }
            override fun lateMovement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) { pipe?.lateMovement(tMs, accG, gyrDps) }
        }
        val rx = HeadbandReceiver(stream.info, sink)
        // what the phone received: live packets outside the gap; the gap's packets later, flagged, 8 per live packet
        val stored = ArrayDeque<ByteArray>()
        var lastTick = 0L
        for ((ms, b) in stream.records) {
            if (gap != null && ms in gap) { stored.addLast(b.copyOf().also { it[1] = (it[1].toInt() or 1).toByte() }); continue }
            val t = base + ms
            if (gap != null && ms > gap.last + 1_500) repeat(minOf(8, stored.size)) { rx.onPacket(t, stored.removeFirst()) }
            rx.onPacket(t, b)
            if (t - lastTick >= 1_000) { pipe?.tick(t); lastTick = t }
        }
        pipe?.tick(base + stream.records.last().first + 10_000)
        val onsetMs = base + (stream.meta.getDouble("onset_s") * 1000).toLong()
        assertTrue("no alarm", rec.alarms.isNotEmpty())
        (rec.alarms.first() - onsetMs) / 1000.0 to (pipe?.lateWindows ?: 0)
    }

    @Test
    fun lateDataFromABluetoothGapRestoreTheAlarmTime() {
        val gap = 203_000L until 300_000L
        val (clean, _) = run(null, backfill = true)
        val (without, _) = run(gap, backfill = false)
        val (with, late) = run(gap, backfill = true)
        println("BACKFILL: no gap ${clean}s | gap without late data ${without}s | gap with late data ${with}s ($late past windows rebuilt)")
        assertTrue(late in 15..21)                       // ~97 s of past windows
        assertTrue("late data should bring the alarm back near the no-gap time: $with vs $clean", with <= clean + 10)
        assertTrue(without > with)
    }

    /** The test headband sends its stored packets before the first live one: they must wait for the clock. */
    @Test
    fun catchUpBeforeAnyLivePacketIsPlacedCorrectly() {
        var lateEeg = 0
        var badTime = 0
        val sink = object : org.epiprot.phone.headband.HeadbandSink {
            override fun eeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) {}
            override fun movement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) {}
            override fun lateEeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) {
                lateEeg++; if (firstMs < base - 60_000 || firstMs > base + 200_000) badTime++
            }
        }
        val rx = HeadbandReceiver(stream.info, sink)
        val recs = stream.records.take(800)
        val t = base + recs.last().first
        for ((_, b) in recs.take(400)) rx.onPacket(t, b.copyOf().also { it[1] = (it[1].toInt() or 1).toByte() })
        assertEquals(0, lateEeg)                                    // waiting: no clock yet
        for ((ms, b) in recs.drop(400)) rx.onPacket(base + ms, b)
        assertTrue(lateEeg > 200)
        assertEquals("stored packets placed on the right timeline", 0, badTime)
    }

    @Test
    fun noGapNothingChanges() {
        val (t, late) = run(null, backfill = true)
        assertEquals(0, late)
        assertTrue(t < 30)
    }
}

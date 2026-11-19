package org.epiprot.phone

import org.epiprot.phone.alarm.AlarmFlow
import org.epiprot.phone.alarm.CaregiverMessage
import org.epiprot.phone.alarm.FlowEffect
import org.epiprot.phone.engine.DemoRecording
import org.epiprot.phone.engine.EngineActions
import org.epiprot.phone.engine.MonitoringEngine
import org.epiprot.phone.engine.WindowAssembler
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.model.Detector
import org.epiprot.phone.model.WindowFeatures
import org.epiprot.phone.model.WindowInput
import org.epiprot.phone.protocol.PhoneMessage
import org.epiprot.phone.protocol.PinContext
import org.epiprot.phone.protocol.PinResult
import org.epiprot.phone.protocol.Sample
import org.epiprot.phone.protocol.SensorBatch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

private fun List<FlowEffect>.sms() = filterIsInstance<FlowEffect.Sms>().map { it.message }
private fun List<FlowEffect>.watch() = filterIsInstance<FlowEffect.Watch>().map { it.message }
private fun List<FlowEffect>.steps() = filterIsInstance<FlowEffect.Step>().map { it.step }

class AlarmFlowTest {
    private val t0 = 1_000_000L

    @Test
    fun caregiverAlertedAtTheAlarmAndFalseAlarmFollowUpOnPin() {
        val f = AlarmFlow()
        val start = f.onAlarm(1, t0, t0 - 20_000)
        assertEquals(listOf(CaregiverMessage.SEIZURE_ALERT), start.sms())
        assertEquals(listOf(PhoneMessage.AlarmStart(1, 30)), start.watch())
        val pin = f.onPin(PinResult(PinContext.ALARM, 1, ok = true, attempt = 1, timeMs = 0), t0 + 8_000)
        assertEquals(listOf(CaregiverMessage.FALSE_ALARM), pin.sms())
        assertTrue(PhoneMessage.AlarmEnd(1, "pin") in pin.watch())
        assertEquals(AlarmFlow.State.Idle, f.state)
    }

    @Test
    fun wrongPinKeepsAlarmAndLatePinIsIgnored() {
        val f = AlarmFlow()
        f.onAlarm(1, t0, t0)
        assertEquals(listOf("wrong PIN"), f.onPin(PinResult(PinContext.ALARM, 1, false, 1, 0), t0 + 3_000).steps())
        assertTrue(f.tick(t0 + 30_000).steps().contains("no PIN in 30 s"))
        assertTrue(f.onPin(PinResult(PinContext.ALARM, 1, true, 2, 0), t0 + 31_000).isEmpty())
        assertTrue(f.state is AlarmFlow.State.Active)
    }

    @Test
    fun emergencyAfterFiveMinutesThenRecoveryCheckInsAndEscalation() {
        val f = AlarmFlow()
        val onset = t0 - 40_000
        f.onAlarm(1, t0, onset)
        f.tick(t0 + 30_000)
        val em = f.tick(onset + 300_000)
        assertEquals(listOf(CaregiverMessage.EMERGENCY), em.sms())
        assertTrue(f.tick(onset + 310_000).isEmpty())            // only once
        val end = onset + 360_000
        assertTrue(f.onSeizureEnded(end, end + 30_000).steps().contains("recovery monitoring started"))
        val c1 = f.tick(end + 300_000)
        assertEquals(listOf(PhoneMessage.CheckIn(1, 1)), c1.watch())
        f.tick(end + 600_000)
        val c3 = f.tick(end + 900_000)
        assertEquals(listOf(CaregiverMessage.NO_ANSWER), c3.sms())
        val ok = f.onPin(PinResult(PinContext.CHECKIN, 1, true, 1, 0), end + 1_000_000)
        assertTrue(ok.steps().contains("patient answered"))
        assertEquals(AlarmFlow.State.Idle, f.state)
    }

    @Test
    fun seizureEndingDuringPinWindowStartsRecoveryWhenWindowCloses() {
        val f = AlarmFlow()
        f.onAlarm(1, t0, t0 - 10_000)
        assertTrue(f.onSeizureEnded(t0 + 10_000, t0 + 15_000).isEmpty())
        val fx = f.tick(t0 + 30_000)
        assertTrue(fx.steps().containsAll(listOf("no PIN in 30 s", "recovery monitoring started")))
        assertTrue(f.state is AlarmFlow.State.Recovery)
    }

    @Test
    fun handedToCaregiverAfterOneHourWithoutAnswer() {
        val f = AlarmFlow()
        f.onAlarm(1, t0, t0)
        f.tick(t0 + 30_000)
        f.onSeizureEnded(t0 + 60_000, t0 + 90_000)
        var last = emptyList<FlowEffect>()
        var t = t0 + 90_000
        while (f.state != AlarmFlow.State.Idle) { t += 10_000; last = f.tick(t) }
        assertEquals(listOf(CaregiverMessage.HANDOVER), last.sms())
        assertTrue(t >= t0 + 60_000 + 3_600_000)
    }

    @Test
    fun caregiverCanCloseTheAlarm() {
        val f = AlarmFlow()
        f.onAlarm(1, t0, t0)
        val fx = f.resolveByCaregiver(t0 + 60_000, wasSeizure = false)
        assertTrue(PhoneMessage.AlarmEnd(1, "caregiver") in fx.watch())
        assertFalse(f.busy)
    }
}

class AssemblerTest {
    @Test
    fun watchBatchesFillWindowsAndGapsAreMissing() {
        val a = WindowAssembler(startMs = 0)
        for (sec in 0 until 5) {
            val acc = List(25) { Sample(it * 40, 0f, 0f, 9.81f) }
            a.addWatch(SensorBatch(sec, sec * 1000L, 70f + sec, true, acc, emptyList()))
        }
        assertTrue(a.closeReady(6_000).isEmpty())          // waits for transmission delay
        val (w, end) = a.closeReady(7_000).single()
        assertEquals(5_000L, end)
        val body = w.mov.getValue("body_acc")
        assertEquals(0.5f, body[2][0], 1e-4f)               // 1 g -> 0.5 model units
        assertTrue(body[2].all { it.isFinite() })
        assertEquals(72.0, WindowFeatures.heartRate(w.heartRate), 1e-9)
        assertNull(w.eegUv)
        assertNull(w.mov["body_gyr"])
        val (empty, _) = a.closeReady(12_000).single()      // nothing arrived
        assertTrue(empty.mov.isEmpty() && empty.heartRate.isEmpty())
    }

    @Test
    fun eegSamplesLandInTheirSlots() {
        val a = WindowAssembler(startMs = 1_000)
        a.addEeg(1_000, FloatArray(2560) { it.toFloat() }, FloatArray(2560) { -it.toFloat() })
        val ws = a.closeReady(20_000)
        assertEquals(3, ws.size)
        assertEquals(1279f, ws[0].first.eegUv!![0][1279])
        assertEquals(1280f, ws[1].first.eegUv!![0][0])
        assertNull(ws[2].first.eegUv)
    }

    @Test
    fun missingHeartRateSwitchesToTheBackupModels() = with(Fixtures) {
        val hb = config.hrBackup ?: return@with
        val demo = DemoRecording.parse(File("src/main/assets/demo/demo_seizure.bin").readBytes())
        val withHr = Detector(config, models)
        val noHr = Detector(config, models)
        var alarmNoHr = -1
        var gaps = 0
        demo.windows.forEachIndexed { i, w ->
            val f = WindowFeatures.compute(w)
            val r1 = withHr.next(f, w)
            val r2 = noHr.next(f + (hb.whenMissing to Double.NaN), WindowInput(w.eegUv, w.mov, FloatArray(0)))
            if (r1.noHeartRate) gaps++                 // real recording: a few windows without heart rate
            assertTrue(r2.noHeartRate)
            if (r2.alarm && alarmNoHr < 0) alarmNoHr = i
        }
        assertTrue("heart rate missing in $gaps of ${demo.windows.size} windows", gaps < demo.windows.size / 4)
        assertTrue("backup models (no heart rate) missed the demo seizure", alarmNoHr >= 0)
        println("demo without heart rate: alarm ${(alarmNoHr + 1) * 5.0 - demo.onsetS}s after onset")
    }

    @Test
    fun halfPrecisionRounding() {
        assertEquals(0.333251953125, Detector.toHalf(1.0 / 3), 0.0)
        assertEquals(-12.0, Detector.toHalf(-12.0), 0.0)
        assertTrue(Detector.toHalf(Double.NaN).isNaN())
        assertEquals(65504.0, Detector.toHalf(65504.0), 0.0)
    }
}

class EngineTest {
    private class Recorder : EngineActions {
        val events = ArrayList<Long>()
        val effects = ArrayList<FlowEffect>()
        val watch = ArrayList<PhoneMessage>()
        val sensor = ArrayList<HealthMonitor.Event>()
        override fun newDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean) = (events.size + 1L).also { events += alarmMs }
        override fun flow(effect: FlowEffect, demo: Boolean) { effects += effect }
        override fun sensor(event: HealthMonitor.Event, demo: Boolean) { sensor += event }
        override fun watch(message: PhoneMessage) { watch += message }
    }

    @Test
    fun replayedRealSeizureRaisesAnAlarmAndAlertsTheCaregiver() = with(Fixtures) {
        val demo = DemoRecording.parse(File("src/main/assets/demo/demo_seizure.bin").readBytes())
        assertEquals(180, demo.windows.size)
        val rec = Recorder()
        val engine = MonitoringEngine(config, models, rec)
        engine.reset(demo = true)
        val t0 = 1_000_000_000L
        var alarmWindow = -1
        demo.windows.forEachIndexed { i, w ->
            val r = engine.onWindow(w, t0 + (i + 1) * 5_000L)
            if (r.alarm && alarmWindow < 0) alarmWindow = i
        }
        assertTrue("no alarm during the replayed seizure", alarmWindow >= 0)
        val latency = (alarmWindow + 1) * 5.0 - demo.onsetS
        println("demo: alarm ${latency}s after onset (seizure ${demo.durationS}s, ${demo.label})")
        // the final model was trained on all SeizeIT2 patients, this recording included: the demo shows the
        // chain working, it is not a performance test (an alarm shortly before the annotated onset is possible)
        assertTrue("alarm long before onset: $latency", latency > -30)
        assertTrue("alarm too late: $latency", latency < demo.durationS + 30)
        assertEquals(1, rec.events.size)
        assertTrue(rec.effects.sms().contains(CaregiverMessage.SEIZURE_ALERT))
        assertTrue(rec.watch.any { it is PhoneMessage.AlarmStart })
        assertTrue("no sensor warnings expected on clean data", rec.sensor.isEmpty())
    }
}

package org.epiprot.phone

import org.epiprot.phone.alarm.FlowEffect
import org.epiprot.phone.engine.EngineActions
import org.epiprot.phone.engine.MonitoringEngine
import org.epiprot.phone.headband.Channels
import org.epiprot.phone.headband.HeadbandReplay
import org.epiprot.phone.headband.HeadbandStream
import org.epiprot.phone.headband.PadStatus
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.protocol.PhoneMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * End to end without hardware: a real tonic-clonic seizure (SeizeIT2 sub-058) played through the
 * software copy of the headband (Bluetooth packets, contact checks, a drying backup pad) into the
 * phone's receiver, window assembler, model and alarm flow.
 */
class VirtualHeadbandTest {
    private class Recorder : EngineActions {
        val alarms = ArrayList<Long>()
        val watch = ArrayList<PhoneMessage>()
        val sensor = ArrayList<HealthMonitor.Event>()
        override fun newDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean) = (alarms.size + 1L).also { alarms += alarmMs }
        override fun flow(effect: FlowEffect, demo: Boolean) {}
        override fun sensor(event: HealthMonitor.Event, demo: Boolean) { sensor += event }
        override fun watch(message: PhoneMessage) { watch += message }
    }

    @Test
    fun realSeizureThroughTheVirtualHeadbandRaisesTheAlarm() = with(Fixtures) {
        val stream = HeadbandStream.parse(File("src/main/assets/demo/headband_demo.ehb").readBytes())
        val onsetS = stream.meta.getDouble("onset_s")
        val rec = Recorder()
        val engine = MonitoringEngine(config, models, rec)
        engine.reset(demo = true)
        val t0 = 1_000_000_000L
        var n = 0
        var alarmWindow = -1
        var backupWindows = 0
        var lastState: org.epiprot.phone.headband.HeadbandState? = null
        for (step in HeadbandReplay(stream).steps()) when (step) {
            is HeadbandReplay.Step.State -> { lastState = step.state; engine.onHeadbandState(step.state, t0 + n * 5_000L) }
            is HeadbandReplay.Step.Window -> {
                n++
                if (step.input.channels != Channels.Choice(0, 1, true)) backupWindows++
                val r = engine.onWindow(step.input, t0 + n * 5_000L)
                if (r.alarm && alarmWindow < 0) alarmWindow = n
            }
        }
        assertEquals(180, n)                                                   // 15 min
        assertTrue("no alarm during the seizure", alarmWindow > 0)
        val latency = alarmWindow * 5.0 - onsetS
        println("virtual headband: alarm ${latency}s after onset")
        assertTrue("alarm long before onset: $latency", latency > -30)
        assertTrue("alarm too late: $latency", latency < stream.meta.getDouble("duration_s") + 30)
        assertEquals(1, rec.alarms.size)
        assertEquals("standard channels throughout (the drying pad is a backup one)", 0, backupWindows)
        // the drying pad behind the right ear (lower) is reported, quietly (not urgent)
        val pad = rec.watch.filterIsInstance<PhoneMessage.SensorWarning>().single { it.code == "pad_replace" }
        assertEquals("R-bottom", pad.detail)
        assertTrue(!pad.urgent)
        assertTrue(rec.watch.filterIsInstance<PhoneMessage.SensorWarning>().none { it.code == "headband_missing" || it.code == "brain_weak" })
        val pads = PadStatus.of(lastState)
        assertEquals(PadStatus.Contact.OK, pads[0].contact)
        assertTrue(pads[3].contact != PadStatus.Contact.OK)                    // R-bottom
    }
}

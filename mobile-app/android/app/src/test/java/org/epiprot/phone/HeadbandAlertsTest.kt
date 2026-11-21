package org.epiprot.phone

import org.epiprot.phone.alarm.FlowEffect
import org.epiprot.phone.engine.EngineActions
import org.epiprot.phone.engine.MonitoringEngine
import org.epiprot.phone.headband.HeadbandAlerts
import org.epiprot.phone.headband.HeadbandProtocol as P
import org.epiprot.phone.headband.HeadbandState
import org.epiprot.phone.headband.WarningPolicy
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.model.WindowFeatures
import org.epiprot.phone.model.WindowInput
import org.epiprot.phone.protocol.PhoneMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HeadbandAlertsTest {
    private val ltop = 1 shl P.ELECTRODES.indexOf("L-top")

    private fun HeadbandAlerts.windows(n: Int, leadOff: Int, contactOk: Boolean, t0: Long) =
        (1..n).flatMap { onWindow(leadOff, contactOk, t0 + it * 5_000L) }

    @Test
    fun padWithoutContactForTwoMinutesIsReportedWithItsNameAndClearsWhenBack() {
        val a = HeadbandAlerts()
        assertTrue(a.windows(17, ltop, true, 0).isEmpty())                // 75 % of 2 min not reached yet
        val w = a.windows(7, ltop, true, 85_000).single() as HealthMonitor.Event.Warning
        assertEquals("pad_contact_lost", w.episode.code)
        assertEquals("L-top", w.episode.detail)
        assertEquals("none", w.episode.impact)                           // backup channels keep detection going
        assertFalse(WarningPolicy.urgent(w.episode.code, w.episode.impact))
        val fixed = a.windows(6, 0, true, 120_000)
        assertTrue(fixed.single() is HealthMonitor.Event.Fixed)
    }

    @Test
    fun noBackupLeftMakesItLimitedAndUrgent() {
        val a = HeadbandAlerts()
        val bias = 1 shl P.ELECTRODES.indexOf("bias")
        val w = a.windows(24, bias, false, 0).single().episode
        assertEquals("bias", w.detail)
        assertEquals("limited", w.impact)
        assertTrue(WarningPolicy.urgent(w.code, w.impact))
    }

    @Test
    fun contactCheckAsksToReplaceADryingPad() {
        val a = HeadbandAlerts()
        val z = intArrayOf(20, 160, 25, P.Z_UNKNOWN, 18)                  // L-bottom drying, R-bottom no contact
        val ev = a.onState(HeadbandState(impedanceKohm = z, lastContactCheckMs = 1_000), 1_000)
        val w = ev.single().episode
        assertEquals("pad_replace", w.code)
        assertEquals("L-bottom", w.detail)                               // no contact = pad_contact_lost, not here
        assertTrue(a.onState(HeadbandState(impedanceKohm = z, lastContactCheckMs = 1_000), 2_000).isEmpty())   // same check
        val ok = a.onState(HeadbandState(impedanceKohm = intArrayOf(20, 22, 25, 30, 18), lastContactCheckMs = 600_000), 600_000)
        assertTrue(ok.single() is HealthMonitor.Event.Fixed)
    }

    @Test
    fun batteryLowCriticalAndCharging() {
        val a = HeadbandAlerts()
        val low = a.onState(HeadbandState(batteryPct = 14, lowBattery = true), 0).single().episode
        assertEquals("headband_battery_low" to "14", low.code to low.detail)
        assertFalse(WarningPolicy.urgent(low.code, low.impact))
        val crit = a.onState(HeadbandState(batteryPct = 2, lowBattery = true), 1_000).single().episode
        assertEquals("headband_battery_critical", crit.code)
        assertTrue(WarningPolicy.urgent(crit.code, crit.impact))
        val ch = a.onState(HeadbandState(batteryPct = 2, lowBattery = true, chargerAttached = true, charging = true), 2_000)
        val codes = ch.map { (if (it is HealthMonitor.Event.Fixed) "fixed:" else "") + it.episode.code }.toSet()
        assertEquals(setOf("headband_charging", "fixed:headband_battery_low", "fixed:headband_battery_critical"), codes)
        assertTrue(a.charging)
        assertFalse(WarningPolicy.urgent("headband_charging", "limited"))
    }
}

class HeadbandEngineTest {
    private class Recorder : EngineActions {
        val watch = ArrayList<PhoneMessage>()
        override fun newDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean) = 1L
        override fun flow(effect: FlowEffect, demo: Boolean) {}
        override fun sensor(event: HealthMonitor.Event, demo: Boolean) {}
        override fun watch(message: PhoneMessage) { watch += message }
    }

    /** Watch data only (headband off the head). */
    private fun watchOnly() = WindowInput(null,
        mapOf("body_acc" to Array(3) { FloatArray(WindowFeatures.MOV_N) { 0.1f } }), floatArrayOf(70f, 71f))

    @Test
    fun whileChargingTheWatchSaysChargingNotHeadbandMissing() = with(Fixtures) {
        val rec = Recorder()
        val e = MonitoringEngine(config, models, rec)
        e.reset(demo = false)
        val t0 = 1_000_000_000L
        e.onHeadbandState(HeadbandState(batteryPct = 50, chargerAttached = true, charging = true), t0)
        for (i in 1..40) e.onWindow(watchOnly(), t0 + i * 5_000L)              // 200 s without headband data
        val warned = rec.watch.filterIsInstance<PhoneMessage.SensorWarning>().map { it.code }
        assertEquals(listOf("headband_charging"), warned)
        val charging = rec.watch.filterIsInstance<PhoneMessage.SensorWarning>().single()
        assertFalse(charging.urgent)
        // charger off but the band is not worn: now the headband warning comes, and it is urgent
        e.onHeadbandState(HeadbandState(batteryPct = 60), t0 + 205_000)
        val after = rec.watch.filterIsInstance<PhoneMessage.SensorWarning>().last()
        assertEquals("headband_missing", after.code)
        assertTrue(after.urgent)
        assertTrue(rec.watch.any { it is PhoneMessage.SensorFixed && it.code == "headband_charging" })
    }
}

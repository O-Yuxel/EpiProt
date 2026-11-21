package org.epiprot.watch

import org.epiprot.watch.core.Effect
import org.epiprot.watch.core.Impact
import org.epiprot.watch.core.NightMode
import org.epiprot.watch.core.Screen
import org.epiprot.watch.core.WarningCode
import org.epiprot.watch.core.WatchStateMachine
import org.epiprot.watch.protocol.PhoneMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NightModeTest {
    private val t0 = 1_000_000L

    @Test
    fun scheduleOverMidnightAndManualSwitchUntilTheScheduleChanges() {
        val n = NightMode(true, 23 * 60, 7 * 60)
        assertTrue(n.isNight(23 * 60 + 30))
        assertTrue(n.isNight(3 * 60))
        assertFalse(n.isNight(7 * 60))
        assertFalse(n.isNight(12 * 60))
        n.toggle(23 * 60 + 30)                     // switched off at 23:30
        assertFalse(n.isNight(2 * 60))
        assertFalse(n.isNight(8 * 60))             // schedule says day: override ends
        assertTrue(n.isNight(23 * 60 + 5))         // next evening night mode is back
        assertFalse(NightMode(false).isNight(2 * 60))
    }

    @Test
    fun nonUrgentWarningIsQuietAtNightAndSummarisedInTheMorning() {
        val m = WatchStateMachine()
        m.setNight(true, t0)
        assertTrue(m.sensorWarning(WarningCode.PAD_REPLACE, Impact.NONE, t0, "L-bottom", urgent = false).isEmpty())
        assertEquals(Screen.Home, m.screen)
        assertTrue(WarningCode.PAD_REPLACE in m.activeWarnings)          // listed on the home screen
        val fx = m.setNight(false, t0 + 8 * 3_600_000L)
        assertTrue(Effect.VibrateShort in fx && Effect.VibrateWarning !in fx)
        assertEquals(Screen.NightSummary(listOf(WarningCode.PAD_REPLACE to "L-bottom")), m.screen)
        assertTrue(m.dismiss(t0 + 8 * 3_600_000L + 1_000).isEmpty())       // not shown a second time
        assertEquals(Screen.Home, m.screen)
    }

    @Test
    fun urgentWarningsAndAlarmsStillVibrateAtNight() {
        val m = WatchStateMachine()
        m.setNight(true, t0)
        val w = m.sensorWarning(WarningCode.HEADBAND_MISSING, Impact.LIMITED, t0, urgent = true)
        assertTrue(Effect.VibrateWarning in w)
        assertEquals(Screen.Warning(WarningCode.HEADBAND_MISSING, Impact.LIMITED), m.screen)
        m.dismiss(t0 + 1_000)
        assertTrue(Effect.VibrateAlarm in m.alarmStart(5, t0 + 2_000))
    }

    @Test
    fun quietWarningFixedAtNightDoesNotVibrate() {
        val m = WatchStateMachine()
        m.setNight(true, t0)
        m.sensorWarning(WarningCode.HEADBAND_BATTERY_LOW, Impact.NONE, t0, "14", urgent = false)
        m.openWarning(WarningCode.HEADBAND_BATTERY_LOW)
        assertEquals("14", (m.screen as Screen.Warning).detail)
        assertTrue(m.sensorFixed(WarningCode.HEADBAND_BATTERY_LOW, t0 + 1_000).none { it == Effect.VibrateShort })
        assertEquals(Screen.Home, m.screen)
    }

    @Test
    fun detailUrgencyAndNightSettingsTravelInTheMessages() {
        for (msg in listOf(PhoneMessage.SensorWarning("pad_replace", "none", "L-bottom,R-top", false),
                           PhoneMessage.Settings("s", "h", 30, false, 22 * 60, 6 * 60 + 30))) {
            val (path, bytes) = PhoneMessage.encode(msg)
            assertEquals(msg, PhoneMessage.decode(path, bytes))
        }
        val old = PhoneMessage.decode(org.epiprot.watch.protocol.Paths.SENSOR_WARNING,
            """{"code":"brain_weak","impact":"limited"}""".toByteArray()) as PhoneMessage.SensorWarning
        assertTrue(old.urgent)                                            // older phone: everything vibrates
    }
}

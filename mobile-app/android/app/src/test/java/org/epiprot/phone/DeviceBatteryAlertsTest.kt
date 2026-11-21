package org.epiprot.phone

import org.epiprot.phone.headband.WarningPolicy
import org.epiprot.phone.health.DeviceBatteryAlerts
import org.epiprot.phone.health.HealthMonitor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceBatteryAlertsTest {
    private fun codes(ev: List<HealthMonitor.Event>) =
        ev.map { (if (it is HealthMonitor.Event.Fixed) "fixed:" else "") + it.episode.code }

    @Test
    fun phoneLowThenCriticalThenChargingFixesBoth() {
        val a = DeviceBatteryAlerts()
        assertTrue(a.onPhone(25, false, 0).isEmpty())
        val low = a.onPhone(19, false, 60_000)
        assertEquals(listOf("phone_battery_low"), codes(low))
        assertEquals("19", low.single().episode.detail)
        assertFalse(WarningPolicy.urgent("phone_battery_low", "none"))           // quiet at night
        assertTrue(a.onPhone(15, false, 120_000).isEmpty())                       // no repeat
        val crit = a.onPhone(10, false, 180_000)
        assertEquals(listOf("phone_battery_critical"), codes(crit))
        assertTrue(WarningPolicy.urgent("phone_battery_critical", "none"))        // vibrates also at night
        assertEquals(setOf("fixed:phone_battery_low", "fixed:phone_battery_critical"), codes(a.onPhone(10, true, 240_000)).toSet())
    }

    @Test
    fun watchLowClearsOnlyWithMarginOrCharging() {
        val a = DeviceBatteryAlerts()
        assertEquals(listOf("watch_battery_low"), codes(a.onWatch(14, false, 0)))
        assertTrue(a.onWatch(16, false, 1).isEmpty())                             // 15 + 5 margin not reached
        assertEquals(listOf("fixed:watch_battery_low"), codes(a.onWatch(20, false, 2)))
        assertTrue(a.onWatch(-1, false, 3).isEmpty())                             // unknown battery: nothing
    }
}

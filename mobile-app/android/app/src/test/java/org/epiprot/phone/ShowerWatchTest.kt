package org.epiprot.phone

import org.epiprot.phone.alarm.ShowerWatch
import org.epiprot.phone.alarm.ShowerWatch.Effect
import org.epiprot.phone.caregiver.CaregiverSms
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ShowerWatchTest {
    private val t0 = 1_000_000_000L
    private val min = 60_000L

    @Test
    fun outInTimeAlertsNobody() {
        val w = ShowerWatch()
        w.onStart(t0, 15)
        assertTrue(w.tick(t0 + 14 * min).isEmpty())
        assertTrue(w.onEnd(t0).isEmpty())
        assertFalse(w.running)
        assertTrue(w.tick(t0 + 60 * min).isEmpty())
    }

    @Test
    fun watchReportsNoAnswerOnceThenAllClear() {
        val w = ShowerWatch()
        w.onStart(t0, 10)
        assertEquals(listOf(Effect.Alert(t0, 10)), w.onOverdue(t0, 10, t0 + 12 * min))
        assertTrue(w.tick(t0 + 20 * min).isEmpty())                       // never a second alert for the same shower
        assertTrue(w.onOverdue(t0, 10, t0 + 21 * min).isEmpty())
        assertEquals(listOf(Effect.AllClear(t0)), w.onEnd(t0))            // "I am fine" afterwards: all clear
    }

    @Test
    fun phoneAlertsByItselfWhenTheWatchIsSilent() {
        val w = ShowerWatch()
        w.onStart(t0, 15)
        assertTrue(w.tick(t0 + 15 * min + 2 * min + 59_000).isEmpty())    // time + 2 min + 1 min slack not over yet
        assertEquals(listOf(Effect.Alert(t0, 15)), w.tick(t0 + 18 * min))
    }

    @Test
    fun aMissedStartStillAlerts() {
        val w = ShowerWatch()                                              // start message never arrived
        assertEquals(listOf(Effect.Alert(t0, 20)), w.onOverdue(t0, 20, t0 + 22 * min))
    }

    @Test
    fun caregiverSmsTags() {
        assertEquals(CaregiverSms.Kind.SHOWER, CaregiverSms.kind("EpiProt: ... [EP:W]"))
        assertTrue(CaregiverSms.Kind.SHOWER.rings)
        assertEquals(CaregiverSms.Kind.SHOWER_OK, CaregiverSms.kind("EpiProt: ... [EP:O]"))
        assertFalse(CaregiverSms.Kind.SHOWER_OK.rings)
    }
}

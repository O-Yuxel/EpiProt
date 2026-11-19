package org.epiprot.phone

import org.epiprot.phone.data.EventRow
import org.epiprot.phone.data.SensorAlertRow
import org.epiprot.phone.report.ReportData
import org.epiprot.phone.report.ReportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Calendar
import java.util.TimeZone

class ReportTest {
    private val utc = TimeZone.getTimeZone("UTC")
    private fun t(day: Int, hour: Int) = Calendar.getInstance(utc).apply { clear(); set(2026, Calendar.NOVEMBER, day, hour, 0, 0) }.timeInMillis
    private fun ev(id: Long, at: Long, kind: String = "unconfirmed", confirmed: String? = null, durS: Long? = null,
                   pin: Boolean = false, demo: Boolean = false, emergency: Boolean = false) =
        EventRow(id, kind, "device", demo, at, at - 20_000, durS?.let { at - 20_000 + it * 1000 }, at, null,
            if (emergency) at + 300_000 else null, pin, confirmed, emptyList(), null, if (durS != null) 240_000 else null)

    @Test
    fun eventsAreClassifiedAndCounted() {
        val events = listOf(
            ev(1, t(2, 3), confirmed = "yes", durS = 95),                 // caregiver confirmed
            ev(2, t(3, 14), durS = 400, emergency = true),                // nobody confirmed
            ev(3, t(9, 22), kind = "false_alarm", pin = true),            // PIN
            ev(4, t(10, 1), confirmed = "no"),                            // caregiver: no seizure
            ev(5, t(11, 2), demo = true),                                 // demo, excluded
            ev(6, t(30, 2)),                                              // outside the period
        )
        val alerts = listOf(SensorAlertRow(t(4, 9), "watch", "heart_missing", "weaker", null, 0, false))
        val d = ReportData.build(events, alerts, t(1, 0), t(20, 0), includeDemo = false, zone = utc)
        assertEquals(4, d.events.size)
        assertEquals(listOf(ReportKind.SEIZURE, ReportKind.UNCONFIRMED, ReportKind.FALSE_ALARM, ReportKind.FALSE_ALARM), d.events.map { it.kind })
        assertEquals(1, d.seizures); assertEquals(1, d.unconfirmed); assertEquals(2, d.falseAlarms); assertEquals(1, d.emergencies)
        assertEquals(400L, d.longestS)
        assertEquals(240L, d.events[0].recoveryResponseS)
        assertEquals(mapOf("watch" to 1), d.sensorProblems)
        // per week: false alarms are not counted; 2 Nov 2026 is a Monday
        assertEquals(listOf(0, 2, 0, 0), d.weeks.map { it.second })   // weeks from Monday 26 Oct; false alarms not counted
        assertEquals(1, d.byHour[3]); assertEquals(1, d.byHour[14]); assertEquals(0, d.byHour[22])
        assertEquals(5, ReportData.build(events, alerts, t(1, 0), t(20, 0), includeDemo = true, zone = utc).events.size)
    }

    @Test
    fun emptyPeriodStillGivesAReport() {
        val d = ReportData.build(emptyList(), emptyList(), t(1, 0), t(7, 0), includeDemo = false, zone = utc)
        assertEquals(0, d.events.size); assertNull(d.longestS); assertEquals(24, d.byHour.size)
    }
}

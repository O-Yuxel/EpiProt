package org.epiprot.phone.report

import org.epiprot.phone.data.EventRow
import org.epiprot.phone.data.SensorAlertRow
import java.util.Calendar
import java.util.TimeZone

/** How an alarm ended up in the report. */
enum class ReportKind { SEIZURE, UNCONFIRMED, FALSE_ALARM }

data class ReportEvent(
    val eventId: Long,
    val alarmMs: Long,
    val kind: ReportKind,
    val durationS: Long?,             // estimated seizure duration (onset -> last seizure-like window)
    val cancelledWithPin: Boolean,
    val caregiverNotified: Boolean,
    val emergency: Boolean,
    val recoveryResponseS: Long?,     // time until the patient answered "Are you OK?" after the seizure
    val confirmedBy: String?,         // patient / caregiver
)

/**
 * Everything the doctor report shows, computed from the event log (pure logic, unit-tested).
 * Only what a doctor needs: no location, no caregiver numbers, no consent details.
 */
data class ReportData(
    val fromMs: Long,
    val toMs: Long,
    val events: List<ReportEvent>,
    val sensorProblems: Map<String, Int>,           // device -> number of warnings in the period
    val weeks: List<Pair<Long, Int>>,               // week start -> seizures + unconfirmed alarms
    val byHour: IntArray,                           // 24 bins, seizures + unconfirmed alarms
) {
    val seizures get() = events.count { it.kind == ReportKind.SEIZURE }
    val unconfirmed get() = events.count { it.kind == ReportKind.UNCONFIRMED }
    val falseAlarms get() = events.count { it.kind == ReportKind.FALSE_ALARM }
    val emergencies get() = events.count { it.emergency }
    val longestS: Long? get() = events.filter { it.kind != ReportKind.FALSE_ALARM }.mapNotNull { it.durationS }.maxOrNull()

    companion object {
        fun kindOf(e: EventRow): ReportKind = when {
            e.kind == "false_alarm" || e.confirmed == "no" -> ReportKind.FALSE_ALARM
            e.kind == "seizure" || e.confirmed == "yes" -> ReportKind.SEIZURE
            else -> ReportKind.UNCONFIRMED
        }

        fun build(events: List<EventRow>, alerts: List<SensorAlertRow>, fromMs: Long, toMs: Long,
                  includeDemo: Boolean, zone: TimeZone = TimeZone.getDefault()): ReportData {
            val inRange = events.filter { e ->
                val t = e.alarmMs ?: return@filter false
                t in fromMs..toMs && (includeDemo || !e.demo)
            }.sortedBy { it.alarmMs }
            val rows = inRange.map { e ->
                ReportEvent(
                    eventId = e.id,
                    alarmMs = e.alarmMs!!,
                    kind = kindOf(e),
                    durationS = if (e.onsetMs != null && e.endMs != null && e.endMs >= e.onsetMs) (e.endMs - e.onsetMs) / 1000 else null,
                    cancelledWithPin = e.cancelledWithPin,
                    caregiverNotified = e.caregiverNotifiedMs != null,
                    emergency = e.emergencyMs != null,
                    recoveryResponseS = e.recoveryResponseMs?.let { it / 1000 },
                    confirmedBy = e.confirmedBy,
                )
            }
            val counted = rows.filter { it.kind != ReportKind.FALSE_ALARM }
            val cal = Calendar.getInstance(zone)
            fun weekStart(t: Long): Long {
                cal.timeInMillis = t
                cal.set(Calendar.HOUR_OF_DAY, 0); cal.set(Calendar.MINUTE, 0); cal.set(Calendar.SECOND, 0); cal.set(Calendar.MILLISECOND, 0)
                val dow = (cal.get(Calendar.DAY_OF_WEEK) + 5) % 7          // Monday = 0
                cal.add(Calendar.DAY_OF_YEAR, -dow)
                return cal.timeInMillis
            }
            val weeks = ArrayList<Pair<Long, Int>>()
            var w = weekStart(fromMs)
            val last = weekStart(toMs)
            while (w <= last && weeks.size < 60) {
                val next = Calendar.getInstance(zone).apply { timeInMillis = w; add(Calendar.DAY_OF_YEAR, 7) }.timeInMillis
                weeks += w to counted.count { it.alarmMs in w until next }
                w = next
            }
            val byHour = IntArray(24)
            for (e in counted) { cal.timeInMillis = e.alarmMs; byHour[cal.get(Calendar.HOUR_OF_DAY)]++ }
            val problems = alerts.filter { it.warnedMs in fromMs..toMs && (includeDemo || !it.demo) }
                .groupingBy { it.device }.eachCount()
            return ReportData(fromMs, toMs, rows, problems, weeks, byHour)
        }
    }
}

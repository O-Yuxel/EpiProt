package org.epiprot.phone.health

import org.epiprot.phone.health.HealthMonitor.Episode
import org.epiprot.phone.health.HealthMonitor.Event

/**
 * Battery warnings for the phone and the watch (the headband has its own, HeadbandAlerts):
 *
 *  phone_battery_low       phone below 20 % and not charging: if the phone switches off, nothing works
 *  phone_battery_critical  phone at 10 % or less and not charging (urgent: vibrates also at night)
 *  watch_battery_low       watch below 15 % and not charging (while the watch charges there is no heart rate,
 *                          detection goes on with the headband and the no-heart-rate models)
 *
 * [detail] = the battery percentage. A warning is fixed when the device charges or is 5 points above its threshold.
 */
class DeviceBatteryAlerts {
    private val open = LinkedHashMap<String, Episode>()
    val openEpisodes: List<Episode> get() = open.values.toList()

    fun onPhone(pct: Int, charging: Boolean, nowMs: Long): List<Event> = buildList {
        addAll(rule(PHONE_LOW, "phone", pct, charging, PHONE_LOW_PCT, nowMs))
        addAll(rule(PHONE_CRITICAL, "phone", pct, charging, PHONE_CRITICAL_PCT, nowMs))
    }

    fun onWatch(pct: Int, charging: Boolean, nowMs: Long): List<Event> =
        rule(WATCH_LOW, "watch", pct, charging, WATCH_LOW_PCT, nowMs)

    private fun rule(code: String, device: String, pct: Int, charging: Boolean, below: Int, nowMs: Long): List<Event> {
        if (pct < 0) return emptyList()
        val low = !charging && (if (code == PHONE_CRITICAL) pct <= below else pct < below)
        val cur = open[code]
        if (low && cur == null) {
            val e = Episode(device, code, "none", "battery", emptySet(), nowMs, nowMs, detail = "$pct")
            open[code] = e
            return listOf(Event.Warning(e))
        }
        if (!low && cur != null && (charging || pct >= below + CLEAR_MARGIN)) {
            open.remove(code)
            cur.fixedMs = nowMs
            return listOf(Event.Fixed(cur))
        }
        return emptyList()
    }

    companion object {
        const val PHONE_LOW = "phone_battery_low"
        const val PHONE_CRITICAL = "phone_battery_critical"
        const val WATCH_LOW = "watch_battery_low"
        const val PHONE_LOW_PCT = 20
        const val PHONE_CRITICAL_PCT = 10
        const val WATCH_LOW_PCT = 15
        const val CLEAR_MARGIN = 5
    }
}

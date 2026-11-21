package org.epiprot.phone.headband

import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.health.HealthMonitor.Episode
import org.epiprot.phone.health.HealthMonitor.Event
import org.epiprot.phone.headband.HeadbandProtocol as P

/**
 * Warnings from the headband's own reports (device-firmware/README.md, decided with the user):
 *
 *  pad_contact_lost   a pad (or the bias electrode) has had no contact in >= 75 % of the last 2 min
 *                     (lead-off bits, same rule as the sensor-health monitor). Impact "none" while a
 *                     backup channel pair keeps detection running, "limited" when none is left.
 *  pad_replace        a contact check found a pad still touching but above 150 kOhm: drying out.
 *  headband_battery_low       below 15 % (the headband's low-battery bit)
 *  headband_battery_critical  2 % or less and not charging: detection stops soon
 *  headband_charging          charger attached: band off the head, seizure detection is off (impact no_alarms)
 *  headband_off               the patient turned the band off, disconnected or unpaired it in the app: detection is
 *                             off (impact no_alarms); detail = off | disconnected | unpaired. Cleared by the next data.
 *
 * [detail] of a warning = the pads concerned, e.g. "L-bottom,R-top".
 */
class HeadbandAlerts {
    private val window = ArrayDeque<Pair<Int, Boolean>>()     // per 5 s window: lead-off bits, contact ok
    private val open = LinkedHashMap<String, Episode>()
    private var lastCheckMs = 0L

    val openEpisodes: List<Episode> get() = open.values.toList()
    val charging: Boolean get() = CHARGING in open
    /** Band charging or switched off on purpose: missing-headband warnings are held back (these say why). */
    val away: Boolean get() = CHARGING in open || OFF in open

    /** The patient switched the band off / disconnected / unpaired it in the app ([how] = detail). */
    fun turnedOff(how: String, nowMs: Long): List<Event> {
        offAtMs = nowMs
        return if (open[OFF]?.detail == how) emptyList() else replace(OFF, "no_alarms", how, nowMs, nowMs)
    }
    private var offAtMs = Long.MIN_VALUE / 2

    /** One headband 5 s window ending at [endMs]. */
    fun onWindow(leadOff: Int, contactOk: Boolean, endMs: Long): List<Event> {
        window.addLast(leadOff to contactOk)
        if (window.size > HealthMonitor.BAD_WIN) window.removeFirst()
        if (window.size < HealthMonitor.BAD_WIN) return emptyList()
        val cur = open[CONTACT_LOST]
        if (cur != null) {          // same as the health monitor: fixed after 30 s with contact again
            val padsOpen = cur.detail.split(",").map { P.ELECTRODES.indexOf(it) }
            val clean = window.takeLast(HealthMonitor.GOOD_WIN).none { w -> padsOpen.any { w.first and (1 shl it) != 0 } }
            if (clean) return fix(CONTACT_LOST, endMs)
        }
        val pads = P.ELECTRODES.indices.filter { e ->
            window.count { it.first and (1 shl e) != 0 } >= HealthMonitor.BAD_FRAC * HealthMonitor.BAD_WIN
        }
        if (pads.isNotEmpty()) {
            val impact = if (window.count { !it.second } * 2 >= window.size) "limited" else "none"
            val detail = pads.joinToString(",") { P.ELECTRODES[it] }
            if (cur == null || cur.detail != detail || cur.impact != impact)
                return replace(CONTACT_LOST, impact, detail, endMs - HealthMonitor.BAD_WIN * HealthMonitor.WINDOW_MS, endMs)
        }
        return emptyList()
    }

    /** New headband state (status packet or contact check) at [nowMs]. */
    fun onState(s: HeadbandState, nowMs: Long): List<Event> {
        val out = mutableListOf<Event>()
        // data again: the band is on and connected (packets still in flight right after "off" do not count)
        if (OFF in open && nowMs - offAtMs > OFF_GRACE_MS) out += fix(OFF, nowMs)
        // charging
        if (s.chargerAttached && CHARGING !in open) out += replace(CHARGING, "no_alarms", "", nowMs, nowMs)
        if (!s.chargerAttached && CHARGING in open) out += fix(CHARGING, nowMs)
        // battery
        if (s.batteryPct >= 0) {
            val low = s.lowBattery && !s.charging
            val critical = s.batteryPct <= CRITICAL_PCT && !s.charging && !s.chargerAttached
            if (low && BATTERY_LOW !in open) out += replace(BATTERY_LOW, "none", "${s.batteryPct}", nowMs, nowMs)
            if (!low && BATTERY_LOW in open && (s.charging || s.batteryPct >= LOW_CLEAR_PCT)) out += fix(BATTERY_LOW, nowMs)
            if (critical && BATTERY_CRITICAL !in open) out += replace(BATTERY_CRITICAL, "limited", "${s.batteryPct}", nowMs, nowMs)
            if (!critical && BATTERY_CRITICAL in open) out += fix(BATTERY_CRITICAL, nowMs)
        }
        // contact check
        val z = s.impedanceKohm
        if (z != null && s.lastContactCheckMs != lastCheckMs) {
            lastCheckMs = s.lastContactCheckMs
            val drying = z.indices.filter { z[it] != P.Z_UNKNOWN && z[it] > REPLACE_PAD_KOHM }
            val detail = drying.joinToString(",") { P.ELECTRODES[it] }
            val cur = open[PAD_REPLACE]
            if (drying.isNotEmpty() && (cur == null || cur.detail != detail)) out += replace(PAD_REPLACE, "none", detail, nowMs, nowMs)
            if (drying.isEmpty() && cur != null) out += fix(PAD_REPLACE, nowMs)
        }
        return out
    }

    private fun replace(code: String, impact: String, detail: String, badFromMs: Long, nowMs: Long): List<Event> {
        val e = Episode("headband", code, impact, "headband", emptySet(), badFromMs, nowMs, detail = detail)
        open[code] = e
        return listOf(Event.Warning(e))
    }

    private fun fix(code: String, nowMs: Long): List<Event> {
        val e = open.remove(code) ?: return emptyList()
        e.fixedMs = nowMs
        return listOf(Event.Fixed(e))
    }

    companion object {
        const val CONTACT_LOST = "pad_contact_lost"
        const val PAD_REPLACE = "pad_replace"
        const val BATTERY_LOW = "headband_battery_low"
        const val BATTERY_CRITICAL = "headband_battery_critical"
        const val CHARGING = "headband_charging"
        const val OFF = "headband_off"
        const val OFF_GRACE_MS = 5_000L
        const val REPLACE_PAD_KOHM = 150         // [EST], HARDWARE.md D15
        const val CRITICAL_PCT = 2               // ~30 min left at ~2 days per charge
        const val LOW_CLEAR_PCT = 20
    }
}

/** Which warnings vibrate on the watch in night mode (decided with the user). */
object WarningPolicy {
    /** Urgent = detection is limited or about to stop. Charging or switching off stops it too, but the patient chose it: quiet at night. */
    fun urgent(code: String, impact: String): Boolean =
        code != HeadbandAlerts.CHARGING && code != HeadbandAlerts.OFF &&
            (code == HeadbandAlerts.BATTERY_CRITICAL || impact == "limited" || impact == "no_alarms")
}

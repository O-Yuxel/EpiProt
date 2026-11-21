package org.epiprot.watch.core

import org.epiprot.watch.protocol.PinContext

/** What the watch shows. */
sealed interface Screen {
    data object Home : Screen

    /** Alarm with the PIN window open. */
    data class Alarm(val alarmId: Long, val deadlineMs: Long, val wrongAttempts: Int = 0) : Screen

    /** PIN window over: caregiver is coming, no cancel possible any more. */
    data class AlarmActive(val alarmId: Long) : Screen

    /** "Are you OK?" during recovery monitoring. */
    data class CheckIn(val alarmId: Long, val number: Int, val wrongAttempts: Int = 0) : Screen

    /** [detail]: which part, e.g. the pads ("L-bottom,R-top") or the battery percentage. */
    data class Warning(val code: WarningCode, val impact: Impact, val detail: String = "") : Screen

    /** Morning summary of the warnings that came in quietly during night mode. */
    data class NightSummary(val items: List<Pair<WarningCode, String>>) : Screen

    data class Info(val kind: InfoKind, val untilMs: Long) : Screen
}

enum class InfoKind { FALSE_ALARM_SENT, RECOVERY_OK, SENSOR_FIXED, ALARM_ENDED }

/** Side effects the controller carries out. */
sealed interface Effect {
    data class SendPin(val context: PinContext, val alarmId: Long, val ok: Boolean, val attempt: Int) : Effect
    data object VibrateAlarm : Effect      // strong, repeating, until stopped
    data object VibrateCheckIn : Effect
    data object VibrateWarning : Effect
    data object VibrateShort : Effect
    data object StopVibration : Effect
    data object WakeScreen : Effect
}

/**
 * The watch's alarm logic, without any Android code so it can be unit-tested.
 *
 * Rules (same as mobile-app/src/epiprot/app/flow.py):
 *  - Alarm: caregiver is already alerted by the phone; the watch vibrates and asks for the PIN for 30 s.
 *    Correct PIN -> phone sends the "false alarm" message. Wrong PIN -> alarm continues.
 *  - After the PIN window the alarm can no longer be cancelled on the watch.
 *  - Check-in: "Are you OK?" answered with the PIN.
 *  - Sensor warnings never interrupt an alarm or a check-in; they are shown right after.
 *  - Night mode: non-urgent warnings are only listed, without vibration or waking the screen; when
 *    night mode ends, one soft vibration and a summary. Alarms and urgent warnings are unchanged.
 */
class WatchStateMachine(
    private var pinWindowMs: Long = 30_000,
    private val infoMs: Long = 4_000,
) {
    var screen: Screen = Screen.Home
        private set

    /** Alarm whose PIN window is over and that the phone has not ended yet (also while the home screen is shown). */
    var activeAlarm: Long? = null
        private set

    /** Open sensor problems (shown on the home screen even after the warning was dismissed). */
    val activeWarnings: Map<WarningCode, Impact> get() = warnings
    private val warnings = LinkedHashMap<WarningCode, Impact>()
    private val acknowledged = HashSet<WarningCode>()
    private val details = HashMap<WarningCode, String>()
    private val urgency = HashMap<WarningCode, Boolean>()
    /** Warnings that came in quietly during night mode (for the morning summary). */
    private val quiet = LinkedHashMap<WarningCode, String>()

    val activeDetails: Map<WarningCode, String> get() = details
    var night = false
        private set

    fun setPinWindow(seconds: Int) {
        pinWindowMs = seconds.coerceIn(10, 120) * 1000L
    }

    fun alarmStart(alarmId: Long, now: Long): List<Effect> {
        activeAlarm = null
        screen = Screen.Alarm(alarmId, now + pinWindowMs)
        return listOf(Effect.WakeScreen, Effect.VibrateAlarm)
    }

    fun alarmEnd(alarmId: Long, now: Long): List<Effect> {
        val s = screen
        val busyWithThisAlarm = (s is Screen.Alarm && s.alarmId == alarmId) ||
            (s is Screen.AlarmActive && s.alarmId == alarmId) ||
            (s is Screen.CheckIn && s.alarmId == alarmId)
        val inBackground = activeAlarm == alarmId
        if (activeAlarm == alarmId) activeAlarm = null
        if (!busyWithThisAlarm) {
            return if (inBackground && s is Screen.Home) {
                screen = Screen.Info(InfoKind.ALARM_ENDED, now + infoMs); emptyList()
            } else emptyList()
        }
        screen = Screen.Info(InfoKind.ALARM_ENDED, now + infoMs)
        return listOf(Effect.StopVibration)
    }

    fun checkIn(alarmId: Long, number: Int, now: Long): List<Effect> {
        if (screen is Screen.Alarm) return emptyList()   // PIN window still open: that PIN answers it
        screen = Screen.CheckIn(alarmId, number)
        return listOf(Effect.WakeScreen, Effect.VibrateCheckIn)
    }

    fun pinEntered(ok: Boolean, now: Long): List<Effect> = when (val s = screen) {
        is Screen.Alarm -> {
            val attempt = s.wrongAttempts + 1
            if (ok) {
                screen = Screen.Info(InfoKind.FALSE_ALARM_SENT, now + infoMs)
                listOf(Effect.SendPin(PinContext.ALARM, s.alarmId, true, attempt), Effect.StopVibration)
            } else {
                screen = s.copy(wrongAttempts = attempt)
                listOf(Effect.SendPin(PinContext.ALARM, s.alarmId, false, attempt))
            }
        }
        is Screen.CheckIn -> {
            val attempt = s.wrongAttempts + 1
            if (ok) {
                activeAlarm = null
                screen = Screen.Info(InfoKind.RECOVERY_OK, now + infoMs)
                listOf(Effect.SendPin(PinContext.CHECKIN, s.alarmId, true, attempt), Effect.StopVibration)
            } else {
                screen = s.copy(wrongAttempts = attempt)
                listOf(Effect.SendPin(PinContext.CHECKIN, s.alarmId, false, attempt), Effect.VibrateShort)
            }
        }
        else -> emptyList()
    }

    fun sensorWarning(code: WarningCode, impact: Impact, now: Long, detail: String = "", urgent: Boolean = true): List<Effect> {
        warnings[code] = impact
        details[code] = detail
        urgency[code] = urgent
        acknowledged.remove(code)          // a new warning or reminder is shown again
        if (night && !urgent) {
            quiet[code] = detail
            return emptyList()
        }
        return if (busy()) emptyList() else show(code)
    }

    fun sensorFixed(code: WarningCode, now: Long): List<Effect> {
        if (warnings.remove(code) == null) return emptyList()
        details.remove(code)
        val urgent = urgency.remove(code) ?: true
        acknowledged.remove(code)
        val s = screen
        if (s is Screen.Warning && s.code == code) {
            if (night && !urgent) return next()
            screen = Screen.Info(InfoKind.SENSOR_FIXED, now + infoMs)
            return listOf(Effect.VibrateShort)
        }
        return emptyList()
    }

    /** Night mode on / off (called by the controller from the schedule). */
    fun setNight(isNight: Boolean, now: Long): List<Effect> {
        if (isNight == night) return emptyList()
        night = isNight
        if (!night && quiet.isNotEmpty() && (screen is Screen.Home)) {
            showSummary()
            return listOf(Effect.WakeScreen, Effect.VibrateShort)
        }
        return emptyList()
    }

    /** User pressed OK on a warning or info screen. */
    fun dismiss(now: Long): List<Effect> = when (val s = screen) {
        is Screen.Warning -> {
            acknowledged.add(s.code)
            next()
        }
        is Screen.Info -> next()
        is Screen.NightSummary -> {
            acknowledged.addAll(s.items.map { it.first }.filter { it in warnings })
            next()
        }
        else -> emptyList()
    }

    /** "Home" on the help-is-coming screen: only hides it, the alarm itself goes on (it ends from the phone). */
    fun goHome(): List<Effect> {
        val s = screen
        if (s !is Screen.AlarmActive) return emptyList()
        activeAlarm = s.alarmId
        screen = Screen.Home
        return listOf(Effect.StopVibration)
    }

    /** Back to the help-is-coming screen from the home screen. */
    fun reopenAlarm(): List<Effect> {
        val id = activeAlarm ?: return emptyList()
        if (screen != Screen.Home) return emptyList()
        screen = Screen.AlarmActive(id)
        return emptyList()
    }

    /** The phone says this alarm no longer exists (phone restarted, alarm closed while disconnected). */
    fun alarmUnknownToPhone(alarmId: Long, now: Long): List<Effect> = alarmEnd(alarmId, now)

    /** Alarm the watch currently considers running (sent in the status so the phone can correct it). */
    fun runningAlarm(): Long? = when (val s = screen) {
        is Screen.Alarm -> s.alarmId
        is Screen.AlarmActive -> s.alarmId
        is Screen.CheckIn -> s.alarmId
        else -> activeAlarm
    }

    /** User opened an open problem from the home screen. */
    fun openWarning(code: WarningCode): List<Effect> {
        val impact = warnings[code] ?: return emptyList()
        if (busy()) return emptyList()
        screen = Screen.Warning(code, impact, details[code] ?: "")
        return emptyList()
    }

    fun tick(now: Long): List<Effect> = when (val s = screen) {
        is Screen.Alarm -> if (now >= s.deadlineMs) {
            activeAlarm = s.alarmId
            screen = Screen.AlarmActive(s.alarmId)
            listOf(Effect.StopVibration)
        } else emptyList()
        is Screen.Info -> if (now >= s.untilMs) next() else emptyList()
        else -> emptyList()
    }

    private fun busy() = screen is Screen.Alarm || screen is Screen.AlarmActive || screen is Screen.CheckIn

    private fun show(code: WarningCode): List<Effect> {
        screen = Screen.Warning(code, warnings.getValue(code), details[code] ?: "")
        return listOf(Effect.WakeScreen, Effect.VibrateWarning)
    }

    private fun showSummary() {
        screen = Screen.NightSummary(quiet.toList())
        quiet.clear()
    }

    private fun next(): List<Effect> {
        val pending = warnings.keys.firstOrNull { it !in acknowledged && (!night || urgency[it] != false) }
        if (pending != null) return show(pending)
        if (!night && quiet.isNotEmpty()) {
            showSummary()
            return listOf(Effect.VibrateShort)
        }
        screen = Screen.Home
        return emptyList()
    }
}

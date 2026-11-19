package org.epiprot.phone.alarm

import org.epiprot.phone.protocol.PhoneMessage
import org.epiprot.phone.protocol.PinContext
import org.epiprot.phone.protocol.PinResult

/** What the caregiver is told by SMS. */
enum class CaregiverMessage { SEIZURE_ALERT, FALSE_ALARM, EMERGENCY, NO_ANSWER, HANDOVER }

/** Commands produced by the alarm flow; the monitoring service carries them out. */
sealed interface FlowEffect {
    data class Sms(val eventId: Long, val message: CaregiverMessage) : FlowEffect
    data class Watch(val message: PhoneMessage) : FlowEffect
    data class Step(val eventId: Long, val timeMs: Long, val step: String, val detail: String) : FlowEffect
    data class Update(val eventId: Long, val fields: Map<String, Any?>) : FlowEffect
}

/**
 * Alarm and recovery-monitoring flow, real-time version of mobile-app/src/epiprot/app/flow.py:
 *  1. Alarm: the caregiver gets the seizure alert + location IMMEDIATELY, the watch asks for the PIN.
 *  2. Correct PIN within 30 s -> false alarm; the caregiver gets a follow-up "false alarm" message.
 *  3. No PIN in 30 s -> the alert stays active.
 *  4. Seizure still going 5 min after its estimated start -> emergency message (emergency services, rescue medication).
 *  5. After the seizure: "Are you OK?" on the watch every 5 min (answered with the PIN);
 *     no answer 15 min after the seizure -> caregiver alerted again; after 60 min handed to the caregiver.
 * Pure logic (no Android): times in wall-clock milliseconds, decisions returned as [FlowEffect]s.
 */
class AlarmFlow(
    private val pinWindowMs: Long = 30_000,
    private val emergencyAfterMs: Long = 300_000,
    private val checkInEveryMs: Long = 300_000,
    private val escalateAfterMs: Long = 900_000,
    private val recoveryMaxMs: Long = 3_600_000,
    private val maxSeizureMs: Long = 1_800_000,     // no end detected -> start recovery monitoring anyway
) {
    sealed interface State {
        data object Idle : State
        data class Alarm(val id: Long, val alarmMs: Long, val onsetMs: Long, val endMs: Long?, val wrong: Int) : State
        data class Active(val id: Long, val onsetMs: Long, val emergencySent: Boolean) : State
        data class Recovery(val id: Long, val endMs: Long, val checkIns: Int, val escalated: Boolean) : State
    }

    var state: State = State.Idle
        private set

    val busy: Boolean get() = state != State.Idle

    /** Device alarm. [eventId] was created by the caller in the event log. */
    fun onAlarm(eventId: Long, nowMs: Long, onsetMs: Long): List<FlowEffect> {
        val out = mutableListOf<FlowEffect>()
        currentId()?.let { old ->       // a new alarm replaces an unfinished flow
            out += FlowEffect.Step(old, nowMs, "superseded", "new alarm $eventId")
            out += FlowEffect.Watch(PhoneMessage.AlarmEnd(old, "new alarm"))
        }
        state = State.Alarm(eventId, nowMs, onsetMs, null, 0)
        out += FlowEffect.Watch(PhoneMessage.AlarmStart(eventId, (pinWindowMs / 1000).toInt()))
        out += FlowEffect.Step(eventId, nowMs, "alarm", "watch vibrates, PIN requested (${pinWindowMs / 1000} s)")
        out += FlowEffect.Sms(eventId, CaregiverMessage.SEIZURE_ALERT)
        out += FlowEffect.Step(eventId, nowMs, "caregiver notified", "seizure alert + location sent immediately")
        out += FlowEffect.Update(eventId, mapOf("caregiver_notified_ms" to nowMs))
        return out
    }

    fun onPin(r: PinResult, nowMs: Long): List<FlowEffect> {
        val s = state
        return when {
            s is State.Alarm && r.alarmId == s.id && r.context == PinContext.ALARM && nowMs <= s.alarmMs + pinWindowMs ->
                if (r.ok) {
                    state = State.Idle
                    listOf(
                        FlowEffect.Step(s.id, nowMs, "cancelled with PIN", "patient is fine"),
                        FlowEffect.Sms(s.id, CaregiverMessage.FALSE_ALARM),
                        FlowEffect.Step(s.id, nowMs, "caregiver informed: false alarm",
                            "follow-up message: patient entered the PIN, they are fine"),
                        FlowEffect.Update(s.id, mapOf("kind" to "false_alarm", "cancelled_with_pin" to true,
                            "false_alarm_sent_ms" to nowMs, "confirmed" to "no", "confirmed_by" to "patient")),
                        FlowEffect.Watch(PhoneMessage.AlarmEnd(s.id, "pin")),
                    )
                } else {
                    state = s.copy(wrong = s.wrong + 1)
                    listOf(FlowEffect.Step(s.id, nowMs, "wrong PIN", "alarm continues"))
                }
            s is State.Recovery && r.alarmId == s.id && r.context == PinContext.CHECKIN ->
                if (r.ok) {
                    state = State.Idle
                    listOf(
                        FlowEffect.Step(s.id, nowMs, "patient answered", "correct PIN, recovery monitoring ends"),
                        FlowEffect.Update(s.id, mapOf("recovery_response_ms" to nowMs - s.endMs,
                            "recovery_escalated" to s.escalated)),
                        FlowEffect.Watch(PhoneMessage.AlarmEnd(s.id, "recovered")),
                    )
                } else listOf(FlowEffect.Step(s.id, nowMs, "wrong PIN", "check-in continues"))
            else -> emptyList()       // late or unrelated answer
        }
    }

    /** The detector says the seizure is over (last seizure-like window ended at [endMs]). */
    fun onSeizureEnded(endMs: Long, nowMs: Long): List<FlowEffect> = when (val s = state) {
        is State.Alarm -> { state = s.copy(endMs = endMs); emptyList() }
        is State.Active -> startRecovery(s.id, endMs, nowMs)
        else -> emptyList()
    }

    fun tick(nowMs: Long): List<FlowEffect> {
        val out = mutableListOf<FlowEffect>()
        when (val s = state) {
            is State.Alarm -> if (nowMs >= s.alarmMs + pinWindowMs) {
                out += FlowEffect.Step(s.id, s.alarmMs + pinWindowMs, "no PIN in ${pinWindowMs / 1000} s",
                    "alert stays active for the caregiver")
                state = State.Active(s.id, s.onsetMs, false)
                if (s.endMs != null) out += startRecovery(s.id, s.endMs, nowMs) else out += tick(nowMs)
            }
            is State.Active -> {
                if (!s.emergencySent && nowMs >= s.onsetMs + emergencyAfterMs) {
                    state = s.copy(emergencySent = true)
                    out += FlowEffect.Sms(s.id, CaregiverMessage.EMERGENCY)
                    out += FlowEffect.Step(s.id, nowMs, "EMERGENCY", "seizure > 5 min: call emergency services, give rescue medication")
                    out += FlowEffect.Update(s.id, mapOf("emergency_ms" to nowMs))
                }
                if (nowMs >= s.onsetMs + maxSeizureMs) out += startRecovery(s.id, nowMs, nowMs)
            }
            is State.Recovery -> {
                val next = s.endMs + (s.checkIns + 1) * checkInEveryMs
                if (nowMs >= s.endMs + recoveryMaxMs) {
                    state = State.Idle
                    out += FlowEffect.Step(s.id, nowMs, "handed to caregiver", "no answer for ${recoveryMaxMs / 60_000} min")
                    out += FlowEffect.Sms(s.id, CaregiverMessage.HANDOVER)
                    out += FlowEffect.Update(s.id, mapOf("recovery_escalated" to true))
                    out += FlowEffect.Watch(PhoneMessage.AlarmEnd(s.id, "handed to caregiver"))
                } else if (nowMs >= next) {
                    val n = s.checkIns + 1
                    var esc = s.escalated
                    out += FlowEffect.Watch(PhoneMessage.CheckIn(s.id, n))
                    out += FlowEffect.Step(s.id, nowMs, "check-in", "\"Are you OK?\" #$n")
                    if (!esc && nowMs >= s.endMs + escalateAfterMs) {
                        esc = true
                        out += FlowEffect.Sms(s.id, CaregiverMessage.NO_ANSWER)
                        out += FlowEffect.Step(s.id, nowMs, "caregiver alerted again",
                            "no answer ${escalateAfterMs / 60_000} min after the seizure")
                    }
                    state = s.copy(checkIns = n, escalated = esc)
                }
            }
            State.Idle -> Unit
        }
        return out
    }

    /** The caregiver closes the alarm in the phone app (they are with the patient). */
    fun resolveByCaregiver(nowMs: Long, wasSeizure: Boolean?): List<FlowEffect> {
        val id = currentId() ?: return emptyList()
        state = State.Idle
        return listOf(
            FlowEffect.Step(id, nowMs, "closed by caregiver", when (wasSeizure) {
                true -> "seizure"; false -> "no seizure"; null -> "not sure" }),
            FlowEffect.Update(id, buildMap {
                if (wasSeizure != null) { put("confirmed", if (wasSeizure) "yes" else "no"); put("confirmed_by", "caregiver") }
                if (wasSeizure == false) put("kind", "false_alarm")
            }),
            FlowEffect.Watch(PhoneMessage.AlarmEnd(id, "caregiver")),
        )
    }

    private fun startRecovery(id: Long, endMs: Long, nowMs: Long): List<FlowEffect> {
        state = State.Recovery(id, endMs, 0, false)
        return listOf(
            FlowEffect.Step(id, nowMs, "recovery monitoring started", "check-in every ${checkInEveryMs / 60_000} min"),
            FlowEffect.Update(id, mapOf("end_ms" to endMs)),
        ) + tick(nowMs)
    }

    fun currentId(): Long? = when (val s = state) {
        is State.Alarm -> s.id
        is State.Active -> s.id
        is State.Recovery -> s.id
        State.Idle -> null
    }
}

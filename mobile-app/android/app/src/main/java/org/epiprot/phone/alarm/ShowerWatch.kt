package org.epiprot.phone.alarm

/**
 * Shower mode (the headband is off in the shower, so there is no seizure detection; the bathroom is one of the
 * riskiest places for a person with epilepsy). The patient starts a timer on the watch; if they do not say "I am
 * out" after the time plus 2 minutes, the caregiver is alerted.
 *
 * The watch decides first (it asks "Are you out?" and reports "overdue" after 2 minutes without an answer). The phone
 * runs the same timer as a backup: if the watch is empty or out of reach, it alerts the caregiver itself, one minute
 * after the watch would have. Each shower alerts the caregiver at most once; "I am out" after an alert sends the
 * caregiver an all-clear. Pure logic, times in wall-clock milliseconds.
 */
class ShowerWatch(private val answerMs: Long = 120_000, private val phoneSlackMs: Long = 60_000) {
    sealed interface Effect {
        /** Alert the caregiver: the patient has not come out of the shower. */
        data class Alert(val sessionMs: Long, val minutes: Int) : Effect
        /** The patient answered after an alert: tell the caregiver all is well. */
        data class AllClear(val sessionMs: Long) : Effect
    }

    private data class Session(val startMs: Long, val minutes: Int, var alerted: Boolean = false)

    private var current: Session? = null

    val running: Boolean get() = current != null

    fun onStart(sessionMs: Long, minutes: Int) {
        current = Session(sessionMs, minutes.coerceIn(1, 60))
    }

    fun onEnd(sessionMs: Long): List<Effect> {
        val s = current?.takeIf { it.startMs == sessionMs } ?: return emptyList()
        current = null
        return if (s.alerted) listOf(Effect.AllClear(s.startMs)) else emptyList()
    }

    /** The watch asked "Are you out?" and got no answer. */
    fun onOverdue(sessionMs: Long, minutes: Int, nowMs: Long): List<Effect> {
        val s = current?.takeIf { it.startMs == sessionMs } ?: Session(sessionMs, minutes).also { current = it }  // start missed
        return alert(s)
    }

    /** Called every second: the phone's own timer (watch silent). */
    fun tick(nowMs: Long): List<Effect> {
        val s = current ?: return emptyList()
        return if (nowMs >= s.startMs + s.minutes * 60_000L + answerMs + phoneSlackMs) alert(s) else emptyList()
    }

    private fun alert(s: Session): List<Effect> {
        if (s.alerted) return emptyList()
        s.alerted = true
        return listOf(Effect.Alert(s.startMs, s.minutes))
    }
}

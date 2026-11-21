package org.epiprot.phone.health

/**
 * Sensor-health monitor, real-time version of mobile-app/src/epiprot/app/health.py
 * (same thresholds; validated there on all 125 SeizeIT2 patients: ~1 warning per day).
 *
 * Every 5 s window: brain signal, head movement (headband), heart rate, body movement (watch)
 * are OK / MISSING / POOR. Per device: a warning when >= 75 % of the last 2 min are bad,
 * reminders after 15, 30, 60 min (then hourly), "fixed" after 30 s all good. Never while an
 * alarm or recovery monitoring is running; a warning that comes due then is sent right after.
 */
class HealthMonitor {
    enum class Quality { OK, MISSING, POOR }

    data class Episode(
        val device: String, val code: String, val impact: String, val problem: String,
        val signals: Set<String>, val badFromMs: Long, val warnedMs: Long,
        val reminders: MutableList<Long> = mutableListOf(), var fixedMs: Long? = null,
        val detail: String = "",           // e.g. the pads concerned ("L-bottom,R-top")
    )

    sealed interface Event {
        val episode: Episode
        data class Warning(override val episode: Episode) : Event
        data class Reminder(override val episode: Episode) : Event
        data class Fixed(override val episode: Episode) : Event
    }

    private class DeviceState(val device: String, val keys: List<String>, val others: List<String>) {
        val window = ArrayDeque<Map<String, Quality>>()
        var episode: Episode? = null
        var pending = false
        var goodRun = 0
    }

    private val devices = DEVICES.map { (d, keys) ->
        DeviceState(d, keys, DEVICES.filter { it.key != d }.values.flatten())
    }

    val openEpisodes: List<Episode> get() = devices.mapNotNull { it.episode }

    /** One 5 s window ending at [endMs]; [busy] = an alarm or recovery monitoring is running. */
    fun next(q: Map<String, Quality>, endMs: Long, busy: Boolean): List<Event> {
        val out = mutableListOf<Event>()
        for (d in devices) {
            d.window.addLast(q)
            if (d.window.size > BAD_WIN) d.window.removeFirst()
            if (d.window.size < BAD_WIN) continue
            val badNow = d.keys.any { q[it] != Quality.OK }
            val ep = d.episode
            if (ep == null) {
                val frac = d.window.count { w -> d.keys.any { w[it] != Quality.OK } }.toDouble() / BAD_WIN
                if (frac >= BAD_FRAC || d.pending) {
                    if (busy) { d.pending = true; continue }
                    d.pending = false
                    fun share(k: String, pred: (Quality?) -> Boolean) = d.window.count { pred(it[k]) }.toDouble() / BAD_WIN
                    val sig = d.keys.filter { share(it) { v -> v != Quality.OK } >= 0.5 }.toSet()
                        .ifEmpty { d.keys.filter { k -> d.window.any { it[k] != Quality.OK } }.toSet() }
                    if (sig.isEmpty()) continue
                    val missing = sig.all { share(it) { v -> v == Quality.MISSING } >= 0.5 }
                    val problem = if (missing) "missing" else "poor"
                    val otherBad = d.others.filter { share(it) { v -> v != Quality.OK } >= 0.5 }.toSet()
                    val e = Episode(d.device, warningCode(d.device, sig, problem), impactCode(sig, otherBad), problem,
                        sig, endMs - BAD_WIN * WINDOW_MS, endMs)
                    d.episode = e
                    d.goodRun = 0
                    out += Event.Warning(e)
                }
            } else {
                d.goodRun = if (badNow) 0 else d.goodRun + 1
                if (d.goodRun >= GOOD_WIN) {
                    ep.fixedMs = endMs
                    d.episode = null
                    out += Event.Fixed(ep)
                } else if (!busy) {
                    val last = ep.reminders.lastOrNull() ?: ep.warnedMs
                    if (endMs - last >= REMIND_MS[minOf(ep.reminders.size, REMIND_MS.size - 1)]) {
                        ep.reminders += endMs
                        out += Event.Reminder(ep)
                    }
                }
            }
        }
        return out
    }

    companion object {
        const val WINDOW_MS = 5_000L
        const val BAD_WIN = 24          // 2 min
        const val BAD_FRAC = 0.75
        const val GOOD_WIN = 6          // 30 s
        val REMIND_MS = longArrayOf(900_000, 1_800_000, 3_600_000)
        const val FLAT_LOG = 0.0        // log10 std in uV: 1 uV
        const val SAT_LOG = 3.3         // 2000 uV

        val DEVICES = linkedMapOf("headband" to listOf("brain", "head_mov"), "watch" to listOf("heart", "body_mov"))

        /**
         * Quality of one window from the model's own window features (no extra computation).
         * [contactBad]: the headband reported no contact on an electrode of the EEG channels in use
         * and no backup pair was free; without this a loose cable or a lost bias electrode would go
         * unnoticed (headband fault study).
         */
        fun quality(f: Map<String, Double>, contactBad: Boolean = false): Map<String, Quality> {
            var brain = Quality.OK                 // same order of checks as health.py (POOR > MISSING > OK)
            for (ch in listOf("eegL", "eegX")) {
                val rms = f["${ch}_rms"] ?: Double.NaN
                if (rms < FLAT_LOG || rms > SAT_LOG) brain = Quality.POOR
                if (rms.isNaN()) brain = Quality.MISSING
            }
            if (contactBad && brain == Quality.OK) brain = Quality.POOR
            fun present(k: String) = if ((f[k] ?: Double.NaN).isNaN()) Quality.MISSING else Quality.OK
            return mapOf("brain" to brain, "head_mov" to present("head_acc_std"),
                "heart" to present("ecg_hr"), "body_mov" to present("body_acc_std"))
        }

        fun impactCode(signals: Set<String>, otherBad: Set<String>): String {
            val bad = signals + otherBad
            return when {
                "brain" in bad -> "limited"
                "heart" in bad -> "weaker"
                bad.containsAll(listOf("head_mov", "body_mov")) -> "backup"
                else -> "none"
            }
        }

        fun warningCode(device: String, signals: Set<String>, problem: String): String =
            if (device == "headband") {
                if (problem == "missing" && signals == setOf("brain", "head_mov")) "headband_missing"
                else if ("brain" in signals) "brain_weak" else "head_mov_missing"
            } else {
                if (problem == "missing" && signals == setOf("heart", "body_mov")) "watch_missing"
                else if ("heart" in signals) "heart_missing" else "body_mov_missing"
            }
    }
}

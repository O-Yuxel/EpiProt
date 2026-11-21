package org.epiprot.phone.headband

import org.json.JSONObject

/**
 * Headband firmware update (device-firmware/HARDWARE.md D23, PROTOCOL.md "Firmware update").
 *
 * The new firmware comes inside the phone app (assets/firmware/manifest.json + the signed image); it is installed
 * only on the charger, with the battery at 30 % or more, after the patient confirms. The headband checks the
 * signature, boots the new image as a test and falls back to the old one if anything fails.
 *
 * Pure logic (no Android): version comparison, the conditions, the steps. The upload goes through a
 * [FirmwareTransport]; in this prototype it is [SimulatedTransport], because the band's firmware does not exist yet.
 */
object FirmwareUpdate {
    data class Manifest(val version: String, val sizeBytes: Int, val notesEn: String, val notesTr: String, val simulated: Boolean) {
        companion object {
            fun parse(json: String): Manifest {
                val j = JSONObject(json)
                val notes = j.optJSONObject("notes")
                return Manifest(j.getString("version"), j.optInt("size_bytes", 0), notes?.optString("en") ?: "",
                    notes?.optString("tr") ?: "", j.optBoolean("simulated", false))
            }
        }
    }

    enum class Step { UPLOADING, VERIFYING, RESTARTING, DONE, FAILED }

    data class Progress(val step: Step, val fraction: Float = 0f, val newVersion: String? = null)

    /** Why "Update now" is not possible yet (empty = it is). */
    enum class Blocker { NOT_CONNECTED, NOT_CHARGING, BATTERY_LOW }

    const val MIN_BATTERY_PCT = 30

    /** True when [candidate] is a newer version than [current] ("1.2.10" > "1.2.9"); unknown current = no update. */
    fun isNewer(candidate: String, current: String?): Boolean {
        if (current.isNullOrBlank()) return false
        fun parts(v: String) = v.trim().split('.').map { it.takeWhile(Char::isDigit).toIntOrNull() ?: 0 }
        val a = parts(candidate); val b = parts(current)
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }; val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }

    fun blockers(connected: Boolean, s: HeadbandState?): List<Blocker> = buildList {
        if (!connected || s == null) add(Blocker.NOT_CONNECTED)
        if (s?.chargerAttached != true) add(Blocker.NOT_CHARGING)
        if ((s?.batteryPct ?: -1) < MIN_BATTERY_PCT) add(Blocker.BATTERY_LOW)
    }
}

/** Sends a signed image to the headband (SMP over Bluetooth in the real product). */
interface FirmwareTransport {
    /** Uploads, then waits for the band's signature check, test boot and self-test; true = confirmed. */
    suspend fun install(onProgress: (FirmwareUpdate.Progress) -> Unit): Boolean
}

/** Prototype: the same steps and timing as a real update of ~300 KB, without a real image (D23). */
class SimulatedTransport(private val sizeBytes: Int, private val bytesPerSecond: Int = 6_000,
                         private val sleep: suspend (Long) -> Unit = { kotlinx.coroutines.delay(it) }) : FirmwareTransport {
    override suspend fun install(onProgress: (FirmwareUpdate.Progress) -> Unit): Boolean {
        val totalMs = (sizeBytes.toLong() * 1000 / bytesPerSecond).coerceAtLeast(2_000)
        val steps = 40
        for (i in 1..steps) {
            sleep(totalMs / steps)
            onProgress(FirmwareUpdate.Progress(FirmwareUpdate.Step.UPLOADING, i / steps.toFloat()))
        }
        onProgress(FirmwareUpdate.Progress(FirmwareUpdate.Step.VERIFYING, 1f)); sleep(2_000)
        onProgress(FirmwareUpdate.Progress(FirmwareUpdate.Step.RESTARTING, 1f)); sleep(4_000)
        return true
    }
}

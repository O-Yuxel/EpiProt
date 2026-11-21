package org.epiprot.watch.protocol

import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Messages between the EpiProt watch app and the EpiProt phone app (Wear OS Data Layer, MessageClient).
 *
 * Sensor data use a compact binary format (sent once per second); everything else is small JSON.
 * The phone app must use exactly the same paths and fields.
 */
object Paths {
    const val PREFIX = "/epiprot"

    // watch -> phone
    const val SENSOR = "/epiprot/sensor"
    const val PIN_RESULT = "/epiprot/pin"
    const val STATUS = "/epiprot/status"

    // phone -> watch
    const val ALARM_START = "/epiprot/alarm_start"
    const val ALARM_END = "/epiprot/alarm_end"
    const val CHECKIN = "/epiprot/checkin"
    const val SENSOR_WARNING = "/epiprot/sensor_warning"
    const val SENSOR_FIXED = "/epiprot/sensor_fixed"
    const val SETTINGS = "/epiprot/settings"
    /** Whether the user's consent allows monitoring; without it the watch does not run its sensors. */
    const val CONSENT = "/epiprot/consent"
}

/** Capability names declared in res/values/wear.xml of each app. */
const val PHONE_CAPABILITY = "epiprot_phone"
const val WATCH_CAPABILITY = "epiprot_watch"

/** One accelerometer or gyroscope sample; [offsetMs] is relative to [SensorBatch.startMs]. */
data class Sample(val offsetMs: Int, val x: Float, val y: Float, val z: Float)

/**
 * About one second of watch sensor data.
 *
 * Binary layout (little endian):
 *   u8 version | i32 seq | i64 startMs | f32 heartRate (NaN = no valid reading) | i8 onBody (-1 unknown, 0, 1)
 *   u16 nAcc | nAcc x (u16 offsetMs, f32 x, f32 y, f32 z)
 *   u16 nGyr | nGyr x (u16 offsetMs, f32 x, f32 y, f32 z)
 */
data class SensorBatch(
    val seq: Int,
    val startMs: Long,
    val heartRate: Float,
    val onBody: Boolean?,
    val acc: List<Sample>,
    val gyr: List<Sample>,
) {
    fun encode(): ByteArray {
        val size = 1 + 4 + 8 + 4 + 1 + 2 + acc.size * SAMPLE_BYTES + 2 + gyr.size * SAMPLE_BYTES
        val b = ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN)
        b.put(VERSION.toByte())
        b.putInt(seq)
        b.putLong(startMs)
        b.putFloat(heartRate)
        b.put(
            when (onBody) {
                null -> -1
                true -> 1
                false -> 0
            }.toByte()
        )
        putSamples(b, acc)
        putSamples(b, gyr)
        return b.array()
    }

    companion object {
        const val VERSION = 1
        private const val SAMPLE_BYTES = 2 + 3 * 4
        private const val MAX_SAMPLES = 0xFFFF

        private fun putSamples(b: ByteBuffer, s: List<Sample>) {
            require(s.size <= MAX_SAMPLES) { "too many samples" }
            b.putShort(s.size.toShort())
            for (x in s) {
                b.putShort(x.offsetMs.coerceIn(0, 0xFFFF).toShort())
                b.putFloat(x.x)
                b.putFloat(x.y)
                b.putFloat(x.z)
            }
        }

        private fun getSamples(b: ByteBuffer): List<Sample> {
            val n = b.short.toInt() and 0xFFFF
            return List(n) { Sample(b.short.toInt() and 0xFFFF, b.float, b.float, b.float) }
        }

        fun decode(bytes: ByteArray): SensorBatch {
            val b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val v = b.get().toInt()
            require(v == VERSION) { "unsupported sensor batch version $v" }
            val seq = b.int
            val start = b.long
            val hr = b.float
            val onBody = when (b.get().toInt()) {
                1 -> true
                0 -> false
                else -> null
            }
            return SensorBatch(seq, start, hr, onBody, getSamples(b), getSamples(b))
        }
    }
}

enum class PinContext(val wire: String) { ALARM("alarm"), CHECKIN("checkin") }

data class PinResult(val context: PinContext, val alarmId: Long, val ok: Boolean, val attempt: Int, val timeMs: Long) {
    fun encode(): ByteArray = JSONObject()
        .put("context", context.wire).put("alarm_id", alarmId).put("ok", ok)
        .put("attempt", attempt).put("time_ms", timeMs)
        .toString().toByteArray()

    companion object {
        fun decode(bytes: ByteArray): PinResult {
            val j = JSONObject(String(bytes))
            return PinResult(
                PinContext.entries.first { it.wire == j.getString("context") }, j.getLong("alarm_id"),
                j.getBoolean("ok"), j.getInt("attempt"), j.getLong("time_ms"),
            )
        }
    }
}

data class WatchStatus(
    val batteryPct: Int,
    val charging: Boolean,
    val onBody: Boolean?,
    val heartSensor: String,       // "device" | "simulated"
    val timeMs: Long,
    val alarmId: Long? = null,     // alarm the watch is showing / keeping, so the phone can end a stale one
    val monitoringAllowed: Boolean? = null,  // what the watch last heard about the consent
) {
    fun encode(): ByteArray = JSONObject()
        .put("battery_pct", batteryPct).put("charging", charging)
        .put("on_body", onBody ?: JSONObject.NULL).put("heart_sensor", heartSensor).put("time_ms", timeMs)
        .put("alarm_id", alarmId ?: JSONObject.NULL)
        .put("monitoring_allowed", monitoringAllowed ?: JSONObject.NULL)
        .toString().toByteArray()
}

/** Messages from the phone. Unknown or broken messages decode to null and are ignored. */
sealed interface PhoneMessage {
    data class AlarmStart(val alarmId: Long, val pinWindowS: Int) : PhoneMessage
    data class AlarmEnd(val alarmId: Long, val reason: String) : PhoneMessage
    data class CheckIn(val alarmId: Long, val number: Int) : PhoneMessage
    /**
     * [detail]: which part, e.g. the pads ("L-bottom,R-top"); [urgent]: vibrates also in night mode
     * (detection is not working or about to stop). The phone decides urgency (WarningPolicy).
     */
    data class SensorWarning(val code: String, val impact: String, val detail: String = "", val urgent: Boolean = true) : PhoneMessage
    data class SensorFixed(val code: String) : PhoneMessage
    /** Night mode: from [nightStartMin] to [nightEndMin] (minutes after midnight, watch's local time). */
    data class Settings(val pinSalt: String, val pinHash: String, val pinWindowS: Int,
                        val nightEnabled: Boolean = true, val nightStartMin: Int = 23 * 60, val nightEndMin: Int = 7 * 60) : PhoneMessage
    data class ConsentState(val monitoringAllowed: Boolean) : PhoneMessage

    companion object {
        fun decode(path: String, bytes: ByteArray): PhoneMessage? = try {
            val j = if (bytes.isEmpty()) JSONObject() else JSONObject(String(bytes))
            when (path) {
                Paths.ALARM_START -> AlarmStart(j.getLong("alarm_id"), j.optInt("pin_window_s", 30))
                Paths.ALARM_END -> AlarmEnd(j.getLong("alarm_id"), j.optString("reason", ""))
                Paths.CHECKIN -> CheckIn(j.getLong("alarm_id"), j.optInt("number", 1))
                Paths.SENSOR_WARNING -> SensorWarning(j.getString("code"), j.optString("impact", "none"),
                    j.optString("detail", ""), j.optBoolean("urgent", true))
                Paths.SENSOR_FIXED -> SensorFixed(j.getString("code"))
                Paths.SETTINGS -> Settings(j.getString("pin_salt"), j.getString("pin_hash"), j.optInt("pin_window_s", 30),
                    j.optBoolean("night_enabled", true), j.optInt("night_start_min", 23 * 60), j.optInt("night_end_min", 7 * 60))
                Paths.CONSENT -> ConsentState(j.getBoolean("monitoring_allowed"))
                else -> null
            }
        } catch (e: Exception) {
            null
        }

        /** Used by tests and by the phone side to build messages. */
        fun encode(msg: PhoneMessage): Pair<String, ByteArray> {
            val (path, j) = when (msg) {
                is AlarmStart -> Paths.ALARM_START to JSONObject().put("alarm_id", msg.alarmId).put("pin_window_s", msg.pinWindowS)
                is AlarmEnd -> Paths.ALARM_END to JSONObject().put("alarm_id", msg.alarmId).put("reason", msg.reason)
                is CheckIn -> Paths.CHECKIN to JSONObject().put("alarm_id", msg.alarmId).put("number", msg.number)
                is SensorWarning -> Paths.SENSOR_WARNING to JSONObject().put("code", msg.code).put("impact", msg.impact)
                    .put("detail", msg.detail).put("urgent", msg.urgent)
                is SensorFixed -> Paths.SENSOR_FIXED to JSONObject().put("code", msg.code)
                is Settings -> Paths.SETTINGS to JSONObject().put("pin_salt", msg.pinSalt).put("pin_hash", msg.pinHash)
                    .put("pin_window_s", msg.pinWindowS).put("night_enabled", msg.nightEnabled)
                    .put("night_start_min", msg.nightStartMin).put("night_end_min", msg.nightEndMin)
                is ConsentState -> Paths.CONSENT to JSONObject().put("monitoring_allowed", msg.monitoringAllowed)
            }
            return path to j.toString().toByteArray()
        }
    }
}

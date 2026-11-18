package org.epiprot.phone.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.epiprot.phone.health.HealthMonitor
import java.security.MessageDigest
import java.security.SecureRandom

/** User settings (on the phone only). */
class Settings(context: Context) {
    private val p = context.getSharedPreferences("epiprot", Context.MODE_PRIVATE)

    var patientName: String
        get() = p.getString("patient", "") ?: ""
        set(v) = p.edit().putString("patient", v.trim()).apply()

    var caregivers: List<String>
        get() = (p.getString("caregivers", "") ?: "").split('\n').filter { it.isNotBlank() }
        set(v) = p.edit().putString("caregivers", v.map { it.trim() }.filter { it.isNotEmpty() }.joinToString("\n")).apply()

    var doctorEmail: String
        get() = p.getString("doctor", "") ?: ""
        set(v) = p.edit().putString("doctor", v.trim()).apply()

    /** Off = test mode: messages are logged and shown, not sent. */
    var realSms: Boolean
        get() = p.getBoolean("real_sms", false)
        set(v) = p.edit().putBoolean("real_sms", v).apply()

    val pinSalt: String? get() = p.getString("pin_salt", null)
    val pinHash: String? get() = p.getString("pin_hash", null)

    /** Stores only a salted hash; the watch checks the PIN against the same hash. */
    fun setPin(pin: String) {
        require(pin.length == 4 && pin.all { it in '0'..'9' })
        val salt = ByteArray(16).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
        p.edit().putString("pin_salt", salt).putString("pin_hash", hashPin(pin, salt)).apply()
    }

    companion object {
        /** Same as watch-app PinVerifier.hashPin. */
        fun hashPin(pin: String, salt: String): String =
            MessageDigest.getInstance("SHA-256").digest((salt + pin).toByteArray()).joinToString("") { "%02x".format(it) }
    }
}

data class EventRow(
    val id: Long, val kind: String, val source: String, val demo: Boolean, val alarmMs: Long?, val onsetMs: Long?,
    val endMs: Long?, val caregiverNotifiedMs: Long?, val falseAlarmSentMs: Long?, val emergencyMs: Long?,
    val cancelledWithPin: Boolean, val confirmed: String?, val steps: List<StepRow>,
)
data class StepRow(val timeMs: Long, val step: String, val detail: String)
data class MessageRow(val timeMs: Long, val eventId: Long, val to: String, val text: String, val status: String)
data class SensorAlertRow(val warnedMs: Long, val device: String, val code: String, val impact: String,
                          val fixedMs: Long?, val reminders: Int, val demo: Boolean)

/**
 * Event log on the phone (SQLite), same content as mobile-app/src/epiprot/app/eventlog.py:
 * events, the alarm audit trail (steps), messages to the caregiver, sensor warnings.
 */
class EventLog(context: Context) : SQLiteOpenHelper(context, "epiprot.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, source TEXT, demo INTEGER,
            alarm_ms INTEGER, onset_ms INTEGER, end_ms INTEGER, caregiver_notified_ms INTEGER, false_alarm_sent_ms INTEGER,
            emergency_ms INTEGER, cancelled_with_pin INTEGER DEFAULT 0, recovery_response_ms INTEGER,
            recovery_escalated INTEGER DEFAULT 0, confirmed TEXT, confirmed_by TEXT)""")
        db.execSQL("CREATE TABLE steps (event_id INTEGER, t_ms INTEGER, step TEXT, detail TEXT)")
        db.execSQL("CREATE TABLE messages (t_ms INTEGER, event_id INTEGER, to_number TEXT, text TEXT, status TEXT)")
        db.execSQL("""CREATE TABLE sensor_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT, code TEXT, impact TEXT,
            problem TEXT, bad_from_ms INTEGER, warned_ms INTEGER, fixed_ms INTEGER, reminders INTEGER DEFAULT 0, demo INTEGER)""")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    fun addDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean): Long = writableDatabase.insert("events", null,
        ContentValues().apply {
            put("kind", "unconfirmed"); put("source", "device"); put("demo", if (demo) 1 else 0)
            put("alarm_ms", alarmMs); put("onset_ms", onsetMs)
        })

    fun step(eventId: Long, tMs: Long, step: String, detail: String) {
        writableDatabase.insert("steps", null, ContentValues().apply {
            put("event_id", eventId); put("t_ms", tMs); put("step", step); put("detail", detail)
        })
    }

    private val columns = setOf("kind", "end_ms", "caregiver_notified_ms", "false_alarm_sent_ms", "emergency_ms",
        "cancelled_with_pin", "recovery_response_ms", "recovery_escalated", "confirmed", "confirmed_by")

    fun update(eventId: Long, fields: Map<String, Any?>) {
        val cv = ContentValues()
        for ((k, v) in fields) {
            require(k in columns) { "unknown column $k" }
            when (v) {
                null -> cv.putNull(k)
                is Boolean -> cv.put(k, if (v) 1 else 0)
                is Long -> cv.put(k, v)
                is Int -> cv.put(k, v)
                else -> cv.put(k, v.toString())
            }
        }
        if (cv.size() > 0) writableDatabase.update("events", cv, "id = ?", arrayOf(eventId.toString()))
    }

    fun message(tMs: Long, eventId: Long, to: String, text: String, status: String) {
        writableDatabase.insert("messages", null, ContentValues().apply {
            put("t_ms", tMs); put("event_id", eventId); put("to_number", to); put("text", text); put("status", status)
        })
    }

    fun sensorWarning(e: HealthMonitor.Episode, demo: Boolean): Long = writableDatabase.insert("sensor_alerts", null,
        ContentValues().apply {
            put("device", e.device); put("code", e.code); put("impact", e.impact); put("problem", e.problem)
            put("bad_from_ms", e.badFromMs); put("warned_ms", e.warnedMs); put("demo", if (demo) 1 else 0)
        })

    fun sensorReminder(e: HealthMonitor.Episode) {
        writableDatabase.execSQL("UPDATE sensor_alerts SET reminders = reminders + 1 WHERE warned_ms = ? AND code = ?",
            arrayOf<Any>(e.warnedMs, e.code))
    }

    fun sensorFixed(e: HealthMonitor.Episode) {
        writableDatabase.execSQL("UPDATE sensor_alerts SET fixed_ms = ? WHERE warned_ms = ? AND code = ?",
            arrayOf<Any?>(e.fixedMs, e.warnedMs, e.code))
    }

    fun events(limit: Int = 50): List<EventRow> {
        val db = readableDatabase
        val out = ArrayList<EventRow>()
        db.rawQuery("SELECT id, kind, source, demo, alarm_ms, onset_ms, end_ms, caregiver_notified_ms, " +
            "false_alarm_sent_ms, emergency_ms, cancelled_with_pin, confirmed FROM events ORDER BY id DESC LIMIT $limit", null).use { c ->
            fun long(i: Int) = if (c.isNull(i)) null else c.getLong(i)
            while (c.moveToNext()) {
                val id = c.getLong(0)
                val steps = ArrayList<StepRow>()
                db.rawQuery("SELECT t_ms, step, detail FROM steps WHERE event_id = ? ORDER BY t_ms, rowid", arrayOf(id.toString())).use { s ->
                    while (s.moveToNext()) steps += StepRow(s.getLong(0), s.getString(1), s.getString(2))
                }
                out += EventRow(id, c.getString(1), c.getString(2), c.getInt(3) == 1, long(4), long(5), long(6), long(7),
                    long(8), long(9), c.getInt(10) == 1, c.getString(11), steps)
            }
        }
        return out
    }

    fun messages(limit: Int = 30): List<MessageRow> = readableDatabase.rawQuery(
        "SELECT t_ms, event_id, to_number, text, status FROM messages ORDER BY t_ms DESC, rowid DESC LIMIT $limit", null).use { c ->
        buildList { while (c.moveToNext()) add(MessageRow(c.getLong(0), c.getLong(1), c.getString(2), c.getString(3), c.getString(4))) }
    }

    fun sensorAlerts(limit: Int = 30): List<SensorAlertRow> = readableDatabase.rawQuery(
        "SELECT warned_ms, device, code, impact, fixed_ms, reminders, demo FROM sensor_alerts ORDER BY warned_ms DESC LIMIT $limit", null).use { c ->
        buildList {
            while (c.moveToNext()) add(SensorAlertRow(c.getLong(0), c.getString(1), c.getString(2), c.getString(3),
                if (c.isNull(4)) null else c.getLong(4), c.getInt(5), c.getInt(6) == 1))
        }
    }
}

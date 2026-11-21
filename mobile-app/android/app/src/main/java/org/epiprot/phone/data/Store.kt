package org.epiprot.phone.data

import android.content.ContentValues
import android.content.Context
import net.zetetic.database.sqlcipher.SQLiteDatabase
import net.zetetic.database.sqlcipher.SQLiteOpenHelper
import org.epiprot.phone.privacy.Vault
import org.epiprot.phone.health.HealthMonitor
import java.security.MessageDigest
import java.security.SecureRandom

/** User settings (on the phone only). */
class Settings(context: Context) {
    private val p = context.getSharedPreferences("epiprot", Context.MODE_PRIVATE)

    // personal fields are stored encrypted (Vault, Android Keystore)
    var patientName: String
        get() = Vault.decrypt(p.getString("patient", null))
        set(v) = p.edit().putString("patient", Vault.encrypt(v.trim())).apply()

    var caregivers: List<String>
        get() = Vault.decrypt(p.getString("caregivers", null)).split('\n').filter { it.isNotBlank() }
        set(v) = p.edit().putString("caregivers", Vault.encrypt(v.map { it.trim() }.filter { it.isNotEmpty() }.joinToString("\n"))).apply()

    var doctorEmail: String
        get() = Vault.decrypt(p.getString("doctor", null))
        set(v) = p.edit().putString("doctor", Vault.encrypt(v.trim())).apply()

    /**
     * Who uses this phone: "patient" (monitoring, the whole app) or "caregiver" (only rings the seizure alarm when a
     * followed patient's phone sends an EpiProt SMS); null = not chosen yet (first start).
     */
    var role: String?
        get() = p.getString("role", null)
        set(v) = p.edit().putString("role", v).apply()

    /** Caregiver mode: the patients this phone follows, "name\tnumber" per line (encrypted). */
    var followed: List<Pair<String, String>>
        get() = Vault.decrypt(p.getString("followed", null)).split('\n').filter { '\t' in it }
            .map { it.substringBefore('\t') to it.substringAfter('\t') }
        set(v) = p.edit().putString("followed", Vault.encrypt(v.joinToString("\n") { "${it.first.trim()}\t${it.second.trim()}" })).apply()

    /** Caregiver mode: the last received EpiProt messages as JSON lines, newest first (encrypted). */
    var caregiverLog: List<String>
        get() = Vault.decrypt(p.getString("caregiver_log", null)).split('\n').filter { it.isNotBlank() }
        set(v) = p.edit().putString("caregiver_log", Vault.encrypt(v.take(30).joinToString("\n"))).apply()

    /** Caregiver mode: the caregiver's own name, sent with "I am going" (encrypted). */
    var caregiverName: String
        get() = Vault.decrypt(p.getString("cg_name", null))
        set(v) = p.edit().putString("cg_name", Vault.encrypt(v.trim())).apply()

    /** Caregiver mode: an alarm is ringing now; the alarm volume to restore afterwards (-1 = none saved). */
    var caregiverRinging: Boolean
        get() = p.getBoolean("cg_ringing", false)
        set(v) = p.edit().putBoolean("cg_ringing", v).apply()
    var savedAlarmVolume: Int
        get() = p.getInt("cg_volume", -1)
        set(v) = p.edit().putInt("cg_volume", v).apply()

    /** Prototype only: firmware version "installed" by the simulated update (D23); null = none. */
    var simulatedFirmware: String?
        get() = p.getString("sim_fw", null)
        set(v) = p.edit().putString("sim_fw", v).apply()

    /** Pads: when they were last changed (0 = never told) and how many spare pads are left (-1 = not told). */
    var padChangedMs: Long
        get() = p.getLong("pad_changed", 0)
        set(v) = p.edit().putLong("pad_changed", v).apply()
    var padStock: Int
        get() = p.getInt("pad_stock", -1)
        set(v) = p.edit().putInt("pad_stock", v).apply()
    /** Last time a pad reminder was shown (at most one a day). */
    var padReminderMs: Long
        get() = p.getLong("pad_reminder", 0)
        set(v) = p.edit().putLong("pad_reminder", v).apply()

    /** History and Settings open only after the phone's own screen lock / fingerprint (if the phone has one). */
    var appLock: Boolean
        get() = p.getBoolean("app_lock", true)
        set(v) = p.edit().putBoolean("app_lock", v).apply()

    /** Time of the last doctor report (the default period starts there). */
    var lastReportMs: Long
        get() = p.getLong("last_report", 0)
        set(v) = p.edit().putLong("last_report", v).apply()

    /** Off = test mode: messages are logged and shown, not sent. */
    var realSms: Boolean
        get() = p.getBoolean("real_sms", false)
        set(v) = p.edit().putBoolean("real_sms", v).apply()

    /** Night mode on the watch: non-urgent warnings without vibration (minutes after midnight). */
    var nightEnabled: Boolean
        get() = p.getBoolean("night_enabled", true)
        set(v) = p.edit().putBoolean("night_enabled", v).apply()
    var nightStartMin: Int
        get() = p.getInt("night_start_min", 23 * 60)
        set(v) = p.edit().putInt("night_start_min", v.coerceIn(0, 24 * 60 - 1)).apply()
    var nightEndMin: Int
        get() = p.getInt("night_end_min", 7 * 60)
        set(v) = p.edit().putInt("night_end_min", v.coerceIn(0, 24 * 60 - 1)).apply()

    /** The paired headband (Bluetooth address); null = none yet. */
    var headbandAddress: String?
        get() = p.getString("headband_address", null)
        set(v) = p.edit().putString("headband_address", v).apply()

    /** "Delete all my data". */
    fun clearAll() { p.edit().clear().apply() }

    fun exportJson(): org.json.JSONObject = org.json.JSONObject()
        .put("patient_name", patientName).put("caregivers", org.json.JSONArray(caregivers))
        .put("doctor_email", doctorEmail).put("real_sms", realSms).put("pin_set", pinHash != null)

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
    val confirmedBy: String? = null, val recoveryResponseMs: Long? = null,
)
data class StepRow(val timeMs: Long, val step: String, val detail: String)
data class MessageRow(val timeMs: Long, val eventId: Long, val to: String, val text: String, val status: String)
data class SensorAlertRow(val warnedMs: Long, val device: String, val code: String, val impact: String,
                          val fixedMs: Long?, val reminders: Int, val demo: Boolean)

/**
 * Event log on the phone (SQLite), same content as mobile-app/src/epiprot/app/eventlog.py:
 * events, the alarm audit trail (steps), messages to the caregiver, sensor warnings.
 */
/**
 * The event log, in an SQLCipher database encrypted with AES-256 (passphrase from [Vault], key in the Android Keystore).
 * Create it with [EventLog.open].
 */
class EventLog private constructor(context: Context, passphrase: String) :
    SQLiteOpenHelper(context, NAME, passphrase, null, 2, 0, null, null, false) {

    companion object {
        private const val NAME = "epiprot.db"

        fun open(context: Context): EventLog {
            System.loadLibrary("sqlcipher")
            val pass = Vault.databasePassphrase(context)
            encryptOldPlaintextDatabase(context, pass)
            return EventLog(context, pass)
        }

        /** Databases written before encryption existed are converted once (sqlcipher_export); on failure they are removed. */
        private fun encryptOldPlaintextDatabase(context: Context, pass: String) {
            val f = context.getDatabasePath(NAME)
            if (!f.exists()) return
            val head = f.inputStream().use { s -> ByteArray(16).also { s.read(it) } }
            if (String(head, Charsets.ISO_8859_1) != "SQLite format 3\u0000") return
            val tmp = context.getDatabasePath("$NAME.enc")
            tmp.delete()
            try {
                val db = SQLiteDatabase.openOrCreateDatabase(f, "", null, null, null)
                db.execSQL("ATTACH DATABASE '${tmp.path}' AS enc KEY '$pass'")
                db.rawQuery("SELECT sqlcipher_export('enc')", null).use { it.moveToFirst() }
                db.execSQL("PRAGMA enc.user_version = 1")
                db.execSQL("DETACH DATABASE enc")
                db.close()
                if (!tmp.renameTo(f.also { it.delete() })) throw IllegalStateException("rename failed")
            } catch (e: Exception) {
                android.util.Log.w("EpiProt", "could not encrypt the old log; removing it", e)
                f.delete(); tmp.delete()
            }
            context.getDatabasePath("$NAME-journal").delete()
        }
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, source TEXT, demo INTEGER,
            alarm_ms INTEGER, onset_ms INTEGER, end_ms INTEGER, caregiver_notified_ms INTEGER, false_alarm_sent_ms INTEGER,
            emergency_ms INTEGER, cancelled_with_pin INTEGER DEFAULT 0, recovery_response_ms INTEGER,
            recovery_escalated INTEGER DEFAULT 0, confirmed TEXT, confirmed_by TEXT)""")
        db.execSQL("CREATE TABLE steps (event_id INTEGER, t_ms INTEGER, step TEXT, detail TEXT)")
        db.execSQL("CREATE TABLE messages (t_ms INTEGER, event_id INTEGER, to_number TEXT, text TEXT, status TEXT)")
        db.execSQL("""CREATE TABLE sensor_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT, code TEXT, impact TEXT,
            problem TEXT, bad_from_ms INTEGER, warned_ms INTEGER, fixed_ms INTEGER, reminders INTEGER DEFAULT 0, demo INTEGER)""")
        createSignals(db)
    }

    /** Signals around each alarm (only with the "signals" consent), compressed, inside the encrypted database. */
    private fun createSignals(db: SQLiteDatabase) =
        db.execSQL("CREATE TABLE IF NOT EXISTS signals (event_id INTEGER PRIMARY KEY, created_ms INTEGER, data BLOB)")

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) { if (oldVersion < 2) createSignals(db) }

    fun saveSignal(eventId: Long, data: ByteArray, nowMs: Long = System.currentTimeMillis()) {
        writableDatabase.insertWithOnConflict("signals", null, ContentValues().apply {
            put("event_id", eventId); put("created_ms", nowMs); put("data", data)
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun signal(eventId: Long): ByteArray? = readableDatabase.rawQuery("SELECT data FROM signals WHERE event_id = ?",
        arrayOf(eventId.toString())).use { if (it.moveToFirst()) it.getBlob(0) else null }

    fun signalIds(): Set<Long> = readableDatabase.rawQuery("SELECT event_id FROM signals", null).use { c ->
        buildSet { while (c.moveToNext()) add(c.getLong(0)) }
    }

    /** Consent withdrawn: every stored signal is deleted. */
    fun deleteSignals() { writableDatabase.delete("signals", null, null) }

    /** Retention: signals older than [maxAgeMs] are deleted automatically. */
    fun deleteSignalsOlderThan(maxAgeMs: Long, nowMs: Long = System.currentTimeMillis()) {
        writableDatabase.delete("signals", "created_ms < ?", arrayOf((nowMs - maxAgeMs).toString()))
    }

    fun addDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean): Long = writableDatabase.insert("events", null,
        ContentValues().apply {
            put("kind", "unconfirmed"); put("source", "device"); put("demo", if (demo) 1 else 0)
            put("alarm_ms", alarmMs); put("onset_ms", onsetMs)
        })

    /**
     * A seizure the patient or a caregiver adds by hand (the device did not raise an alarm: headband not worn, or
     * missed). [type] = tonic_clonic | other | unsure; [worn] = yes | no | unknown (headband on at that time);
     * [note] free text. Stored like an alarm (time in alarm_ms) with source "manual"; the details are its first step.
     */
    fun addManualEvent(timeMs: Long, type: String, worn: String, note: String, nowMs: Long = System.currentTimeMillis()): Long {
        val id = writableDatabase.insert("events", null, ContentValues().apply {
            put("kind", "seizure"); put("source", "manual"); put("demo", 0)
            put("alarm_ms", timeMs); put("onset_ms", timeMs); put("confirmed", "yes"); put("confirmed_by", "manual")
        })
        step(id, nowMs, "manual", "type=$type;worn=$worn;note=${note.replace(';', ',').trim()}")
        return id
    }

    /** Shower mode: no answer after the timer (shown like a help call in the history and the report). */
    fun addShowerEvent(timeMs: Long, minutes: Int): Long {
        val id = writableDatabase.insert("events", null, ContentValues().apply {
            put("kind", "help"); put("source", "shower"); put("demo", 0); put("alarm_ms", timeMs)
        })
        step(id, timeMs, "shower", "no answer after the $minutes min shower timer + 2 min")
        return id
    }

    /** The patient pressed "Call for help" on the watch. */
    fun addHelpEvent(timeMs: Long): Long = writableDatabase.insert("events", null, ContentValues().apply {
        put("kind", "help"); put("source", "watch"); put("demo", 0); put("alarm_ms", timeMs)
    })

    fun deleteEvent(eventId: Long) {
        writableDatabase.delete("events", "id = ?", arrayOf(eventId.toString()))
        writableDatabase.delete("steps", "event_id = ?", arrayOf(eventId.toString()))
    }

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

    fun message(tMs: Long, eventId: Long, to: String, text: String, status: String): Long =
        writableDatabase.insert("messages", null, ContentValues().apply {
            put("t_ms", tMs); put("event_id", eventId); put("to_number", to); put("text", text); put("status", status)
        })

    /** New state of a message already in the log (sending -> sent / failed). */
    fun messageStatus(rowId: Long, status: String) {
        writableDatabase.update("messages", ContentValues().apply { put("status", status) }, "rowid = ?", arrayOf(rowId.toString()))
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

    fun events(limit: Int = 50): List<EventRow> = eventsWhere("1", limit)

    /** Every event whose alarm time is in [fromMs, toMs] (doctor report). */
    fun eventsBetween(fromMs: Long, toMs: Long): List<EventRow> = eventsWhere("alarm_ms BETWEEN $fromMs AND $toMs", 100_000)

    fun sensorAlertsBetween(fromMs: Long, toMs: Long): List<SensorAlertRow> = readableDatabase.rawQuery(
        "SELECT warned_ms, device, code, impact, fixed_ms, reminders, demo FROM sensor_alerts WHERE warned_ms BETWEEN $fromMs AND $toMs", null).use { c ->
        buildList {
            while (c.moveToNext()) add(SensorAlertRow(c.getLong(0), c.getString(1), c.getString(2), c.getString(3),
                if (c.isNull(4)) null else c.getLong(4), c.getInt(5), c.getInt(6) == 1))
        }
    }

    private fun eventsWhere(where: String, limit: Int): List<EventRow> {
        val db = readableDatabase
        val out = ArrayList<EventRow>()
        db.rawQuery("SELECT id, kind, source, demo, alarm_ms, onset_ms, end_ms, caregiver_notified_ms, " +
            "false_alarm_sent_ms, emergency_ms, cancelled_with_pin, confirmed, confirmed_by, recovery_response_ms " +
            "FROM events WHERE $where ORDER BY id DESC LIMIT $limit", null).use { c ->
            fun long(i: Int) = if (c.isNull(i)) null else c.getLong(i)
            while (c.moveToNext()) {
                val id = c.getLong(0)
                val steps = ArrayList<StepRow>()
                db.rawQuery("SELECT t_ms, step, detail FROM steps WHERE event_id = ? ORDER BY t_ms, rowid", arrayOf(id.toString())).use { s ->
                    while (s.moveToNext()) steps += StepRow(s.getLong(0), s.getString(1), s.getString(2))
                }
                out += EventRow(id, c.getString(1), c.getString(2), c.getInt(3) == 1, long(4), long(5), long(6), long(7),
                    long(8), long(9), c.getInt(10) == 1, c.getString(11), steps, c.getString(12), long(13))
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

    /** "Delete all my data": every event, step, message and sensor warning. */
    fun clearAll() {
        writableDatabase.apply {
            for (t in listOf("events", "steps", "messages", "sensor_alerts", "signals")) delete(t, null, null)
            execSQL("VACUUM")
        }
    }

    /** "Download my data": the whole log as JSON (KVKK m.11 / GDPR art. 15 and 20). */
    fun exportJson(): org.json.JSONObject {
        fun table(sql: String) = org.json.JSONArray().also { arr ->
            readableDatabase.rawQuery(sql, null).use { c ->
                while (c.moveToNext()) arr.put(org.json.JSONObject().also { o ->
                    for (i in 0 until c.columnCount) o.put(c.getColumnName(i), when (c.getType(i)) {
                        android.database.Cursor.FIELD_TYPE_NULL -> org.json.JSONObject.NULL
                        android.database.Cursor.FIELD_TYPE_INTEGER -> c.getLong(i)
                        android.database.Cursor.FIELD_TYPE_FLOAT -> c.getDouble(i)
                        android.database.Cursor.FIELD_TYPE_BLOB -> android.util.Base64.encodeToString(c.getBlob(i), android.util.Base64.NO_WRAP)
                        else -> c.getString(i)
                    })
                })
            }
        }
        return org.json.JSONObject()
            .put("events", table("SELECT * FROM events ORDER BY id"))
            .put("steps", table("SELECT * FROM steps ORDER BY event_id, t_ms"))
            .put("messages", table("SELECT * FROM messages ORDER BY t_ms"))
            .put("sensor_alerts", table("SELECT * FROM sensor_alerts ORDER BY warned_ms"))
            .put("signals_note", "signals: zlib-compressed SignalSnippet (see signals/Signals.kt), base64")
            .put("signals", table("SELECT * FROM signals ORDER BY event_id"))
    }
}

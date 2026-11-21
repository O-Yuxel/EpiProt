package org.epiprot.phone.caregiver

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.RingtoneManager
import android.provider.Telephony
import androidx.core.app.NotificationCompat
import org.epiprot.phone.R
import org.epiprot.phone.data.Settings
import org.epiprot.phone.ui.CaregiverAlarmActivity
import org.epiprot.phone.ui.MainActivity
import org.json.JSONObject

/** One EpiProt message received in caregiver mode. */
data class Received(val timeMs: Long, val patient: String, val number: String, val kind: CaregiverSms.Kind, val text: String) {
    fun toJson(): String = JSONObject().put("t", timeMs).put("p", patient).put("n", number).put("k", kind.name).put("x", text).toString()

    companion object {
        fun fromJson(s: String): Received? = try {
            val o = JSONObject(s)
            Received(o.getLong("t"), o.getString("p"), o.getString("n"), CaregiverSms.Kind.valueOf(o.getString("k")), o.getString("x"))
        } catch (e: Exception) { null }
    }
}

/**
 * Caregiver mode (Settings.role == "caregiver"): this phone belongs to a caregiver. It does no monitoring; it rings a
 * loud alarm when the phone of a followed patient sends an EpiProt SMS (seizure, emergency, no answer, handover) and
 * stops it when the "false alarm" SMS arrives. Works without internet; nothing leaves this phone.
 *
 * The alarm is a full-screen notification whose sound uses the ALARM stream, so it plays when the phone is on silent
 * (like an alarm clock), at full alarm volume, repeating until the caregiver reacts (FLAG_INSISTENT). With "Do Not
 * Disturb" access it also rings through Do Not Disturb.
 */
object CaregiverMode {
    private const val CHANNEL = "epiprot_caregiver_alarm_v1"
    private const val INFO_CHANNEL = "epiprot_caregiver_info_v1"
    const val ALARM_ID = 4242
    private const val INFO_ID = 4243

    fun followed(c: Context) = Settings(c).followed
    fun follow(c: Context, name: String, number: String) {
        val s = Settings(c)
        s.followed = s.followed.filterNot { CaregiverSms.sameNumber(it.second, number) } + (name.trim() to number.trim())
    }
    fun unfollow(c: Context, number: String) { val s = Settings(c); s.followed = s.followed.filterNot { it.second == number } }
    fun find(c: Context, sender: String) = Settings(c).followed.firstOrNull { CaregiverSms.sameNumber(it.second, sender) }

    fun log(c: Context): List<Received> = Settings(c).caregiverLog.mapNotNull(Received::fromJson)
    private fun addLog(c: Context, r: Received) { val s = Settings(c); s.caregiverLog = listOf(r.toJson()) + s.caregiverLog }

    /** The alarm on screen now (null = none). */
    fun current(c: Context): Received? = if (Settings(c).caregiverRinging) log(c).firstOrNull() else null

    /** An incoming SMS (from [CaregiverSmsReceiver], or the "test the alarm" button). */
    fun handle(c: Context, sender: String, text: String, nowMs: Long) {
        if (Settings(c).role != "caregiver") return
        val kind = CaregiverSms.kind(text) ?: return
        val p = find(c, sender)
        if (p == null) {
            // only the introduction of a new patient is shown from an unknown number; an alarm never rings from one
            if (kind == CaregiverSms.Kind.INTRO) info(c, c.getString(R.string.cg_intro_unknown_title),
                c.getString(R.string.cg_intro_unknown, sender), Intent(c, MainActivity::class.java).putExtra(EXTRA_NUMBER, sender))
            return
        }
        val r = Received(nowMs, p.first, p.second, kind, text)
        addLog(c, r)
        when {
            kind.rings -> ring(c, r)
            kind == CaregiverSms.Kind.FALSE_ALARM -> { stop(c); info(c, c.getString(R.string.cg_false_alarm, p.first), CaregiverSms.readable(text)) }
            else -> info(c, c.getString(R.string.cg_intro, p.first), CaregiverSms.readable(text))
        }
    }

    fun channels(c: Context) {
        val nm = c.getSystemService(NotificationManager::class.java)
        val sound = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, c.getString(R.string.cg_channel_alarm), NotificationManager.IMPORTANCE_HIGH).apply {
            setSound(sound, AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 800, 400, 800, 400, 800)
            setBypassDnd(true)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        })
        nm.createNotificationChannel(NotificationChannel(INFO_CHANNEL, c.getString(R.string.cg_channel_info), NotificationManager.IMPORTANCE_DEFAULT))
    }

    fun ring(c: Context, r: Received) {
        channels(c)
        val s = Settings(c)
        s.caregiverRinging = true
        val am = c.getSystemService(AudioManager::class.java)
        if (s.savedAlarmVolume < 0) s.savedAlarmVolume = am.getStreamVolume(AudioManager.STREAM_ALARM)
        try { am.setStreamVolume(AudioManager.STREAM_ALARM, am.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0) } catch (_: Exception) { }
        val open = PendingIntent.getActivity(c, 7, Intent(c, CaregiverAlarmActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val body = CaregiverSms.readable(r.text)
        val n = NotificationCompat.Builder(c, CHANNEL)
            .setSmallIcon(R.drawable.ic_epiprot)
            .setContentTitle(c.getString(titleOf(r.kind), r.patient))
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setFullScreenIntent(open, true)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        n.flags = n.flags or Notification.FLAG_INSISTENT          // the sound repeats until the caregiver reacts
        try { c.getSystemService(NotificationManager::class.java).notify(ALARM_ID, n) } catch (_: SecurityException) { }
    }

    /** "I am going" on the alarm screen, or the false-alarm SMS: silence and restore the alarm volume. */
    fun stop(c: Context) {
        val s = Settings(c)
        s.caregiverRinging = false
        c.getSystemService(NotificationManager::class.java).cancel(ALARM_ID)
        if (s.savedAlarmVolume >= 0) {
            try { c.getSystemService(AudioManager::class.java).setStreamVolume(AudioManager.STREAM_ALARM, s.savedAlarmVolume, 0) }
            catch (_: Exception) { }
            s.savedAlarmVolume = -1
        }
    }

    private fun info(c: Context, title: String, text: String, open: Intent = Intent(c, MainActivity::class.java)) {
        channels(c)
        val pi = PendingIntent.getActivity(c, 8, open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(c, INFO_CHANNEL).setSmallIcon(R.drawable.ic_epiprot)
            .setContentTitle(title).setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setAutoCancel(true).setContentIntent(pi).build()
        try { c.getSystemService(NotificationManager::class.java).notify(INFO_ID, n) } catch (_: SecurityException) { }
    }

    fun titleOf(k: CaregiverSms.Kind) = when (k) {
        CaregiverSms.Kind.SEIZURE -> R.string.cg_alarm_seizure
        CaregiverSms.Kind.EMERGENCY -> R.string.cg_alarm_emergency
        CaregiverSms.Kind.NO_ANSWER -> R.string.cg_alarm_no_answer
        CaregiverSms.Kind.HANDOVER -> R.string.cg_alarm_handover
        CaregiverSms.Kind.FALSE_ALARM -> R.string.cg_false_alarm
        CaregiverSms.Kind.INTRO -> R.string.cg_intro
        CaregiverSms.Kind.SOS -> R.string.cg_alarm_sos
    }

    const val EXTRA_NUMBER = "cg_number"
}

/** Every incoming SMS; only EpiProt messages from a followed patient do anything (caregiver mode only). */
class CaregiverSmsReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        parts.groupBy { it.originatingAddress ?: "" }.forEach { (sender, msgs) ->
            CaregiverMode.handle(c, sender, msgs.joinToString("") { it.messageBody ?: "" }, System.currentTimeMillis())
        }
    }
}

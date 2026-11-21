package org.epiprot.phone.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import org.epiprot.phone.R
import org.epiprot.phone.ui.MainActivity

/**
 * Warnings on the patient's own phone (the watch shows them too). Needed because the watch can be empty, charging
 * or not worn: then a warning such as "headband not sending, alarms do NOT work" must still reach someone.
 *
 * Shown on the phone: every urgent warning, and every warning while the watch is not connected.
 * A warning disappears by itself when it is fixed.
 */
object PhoneAlerts {
    private const val CHANNEL = "epiprot_warnings"
    private const val SMS_FAILED_BASE = 5_000

    private fun channel(c: Context) {
        c.getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, c.getString(R.string.channel_warnings), NotificationManager.IMPORTANCE_HIGH))
    }

    /** One notification per warning code, so a new warning of the same kind replaces the old one. */
    private fun idOf(code: String) = 1_000 + (code.hashCode() and 0xFFF)

    /** The warning in words, as on the watch: what is wrong + what it means for detection. */
    fun text(c: Context, code: String, impact: String, detail: String): String {
        val res = c.resources
        val pkg = c.packageName
        val warnId = res.getIdentifier("warn_$code", "string", pkg)
        val impactId = res.getIdentifier("impact_$impact", "string", pkg)
        val what = when {
            warnId == 0 -> code.replace('_', ' ')
            code.startsWith("pad_") -> c.getString(warnId, padNames(c, detail))
            code.endsWith("battery_low") || code.endsWith("battery_critical") || code.startsWith("pads_") -> c.getString(warnId, detail)
            code == "headband_off" -> c.getString(when (detail) {
                "disconnected" -> R.string.warn_headband_disconnected
                "unpaired" -> R.string.warn_headband_unpaired
                else -> R.string.warn_headband_off
            })
            else -> c.getString(warnId)
        }
        // texts that already say what happens to detection need no second sentence
        val saysItself = code in setOf("headband_charging", "headband_off") || code.startsWith("phone_battery") ||
            code == "watch_battery_low"
        return if (impactId == 0 || saysItself || impact == "none") what else "$what ${c.getString(impactId)}"
    }

    private fun padNames(c: Context, detail: String) = detail.split(",").filter { it.isNotBlank() }.joinToString("; ") {
        c.getString(when (it) {
            "L-top" -> R.string.pad_l_top
            "L-bottom" -> R.string.pad_l_bottom
            "R-top" -> R.string.pad_r_top
            "R-bottom" -> R.string.pad_r_bottom
            else -> R.string.pad_bias
        })
    }

    fun warning(c: Context, code: String, impact: String, detail: String, urgent: Boolean) {
        channel(c)
        val body = text(c, code, impact, detail)
        val open = PendingIntent.getActivity(c, 3, Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(c, CHANNEL)
            .setSmallIcon(R.drawable.ic_epiprot)
            .setContentTitle(c.getString(R.string.notif_warning_title))
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(if (urgent) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .build()
        try { c.getSystemService(NotificationManager::class.java).notify(idOf(code), n) } catch (_: SecurityException) { }
    }

    fun fixed(c: Context, code: String) = c.getSystemService(NotificationManager::class.java).cancel(idOf(code))

    /** A caregiver SMS could not be sent after all tries. */
    fun smsFailed(c: Context, to: String) {
        channel(c)
        val body = c.getString(R.string.notif_sms_failed_text, to)
        val n = NotificationCompat.Builder(c, CHANNEL)
            .setSmallIcon(R.drawable.ic_epiprot)
            .setContentTitle(c.getString(R.string.notif_sms_failed_title))
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        try { c.getSystemService(NotificationManager::class.java).notify(SMS_FAILED_BASE + (to.hashCode() and 0xFF), n) }
        catch (_: SecurityException) { }
    }
}

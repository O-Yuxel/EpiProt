package org.epiprot.watch.feedback

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.core.app.NotificationCompat
import org.epiprot.watch.R
import org.epiprot.watch.ui.MainActivity

/** Vibration patterns. */
class Haptics(context: Context) {
    private val vibrator: Vibrator =
        if (Build.VERSION.SDK_INT >= 31) context.getSystemService(VibratorManager::class.java).defaultVibrator
        else @Suppress("DEPRECATION") context.getSystemService(Vibrator::class.java)

    /** Strong, repeating until [stop]. */
    fun alarm() = vibrator.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 700, 300), 0))

    fun checkIn() = vibrator.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 400, 200, 400, 200, 400), -1))

    fun warning() = vibrator.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 250, 150, 250), -1))

    fun short() = vibrator.vibrate(VibrationEffect.createOneShot(120, VibrationEffect.DEFAULT_AMPLITUDE))

    fun stop() = vibrator.cancel()
}

object Notifications {
    const val CHANNEL_MONITORING = "monitoring"
    const val CHANNEL_ALARM = "alarm"
    const val ID_MONITORING = 1
    private const val ID_WAKE = 2
    private const val ID_RESUME = 3

    fun createChannels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_MONITORING, context.getString(R.string.channel_monitoring), NotificationManager.IMPORTANCE_LOW)
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ALARM, context.getString(R.string.channel_alarm), NotificationManager.IMPORTANCE_HIGH)
                .apply { enableVibration(false) }   // vibration is done by Haptics
        )
    }

    private fun openApp(context: Context, request: Int) = PendingIntent.getActivity(
        context, request,
        Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    fun monitoring(context: Context) = NotificationCompat.Builder(context, CHANNEL_MONITORING)
        .setSmallIcon(R.drawable.ic_epiprot)
        .setContentTitle(context.getString(R.string.app_name))
        .setContentText(context.getString(R.string.notif_monitoring))
        .setOngoing(true)
        .setContentIntent(openApp(context, 0))
        .build()

    /** "EpiProt is not running – tap to open" (the app starts the service from the foreground). */
    fun resume(context: Context) {
        createChannels(context)
        val n = NotificationCompat.Builder(context, CHANNEL_ALARM)
            .setSmallIcon(R.drawable.ic_epiprot)
            .setContentTitle(context.getString(R.string.notif_resume_title))
            .setContentText(context.getString(R.string.notif_resume_text))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setOngoing(true)
            .setContentIntent(openApp(context, 2))
            .build()
        try { context.getSystemService(NotificationManager::class.java).notify(ID_RESUME, n) } catch (e: SecurityException) { }
    }

    fun clearResume(context: Context) = context.getSystemService(NotificationManager::class.java).cancel(ID_RESUME)

    /**
     * Brings the app to the front for an alarm, check-in or warning. Apps may not open screens from the
     * background directly, so a full-screen notification is used as well.
     */
    fun wake(context: Context) {
        try {
            context.startActivity(
                Intent(context, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            )
        } catch (e: Exception) {
            // blocked from the background: the full-screen notification below opens it
        }
        val n = NotificationCompat.Builder(context, CHANNEL_ALARM)
            .setSmallIcon(R.drawable.ic_epiprot)
            .setContentTitle(context.getString(R.string.app_name))
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setFullScreenIntent(openApp(context, 1), true)
            .setAutoCancel(true)
            .setTimeoutAfter(60_000)
            .build()
        try {
            context.getSystemService(NotificationManager::class.java).notify(ID_WAKE, n)
        } catch (e: SecurityException) {
            // notification permission not granted
        }
    }
}

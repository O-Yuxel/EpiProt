package org.epiprot.phone.service

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import org.epiprot.phone.EpiProtPhoneApp
import org.epiprot.phone.R
import org.epiprot.phone.ui.MainActivity

/**
 * Keeps monitoring running with the screen off: receives the watch (and later headband) data,
 * runs the detector every 5 s and handles alarms. Foreground service ("connected device";
 * plus "location" when started from the app and allowed, so the caregiver message can include the position).
 *
 * Staying on: the user's choice is remembered ([wanted]); the service is sticky (Android restarts it after killing
 * the process), comes back after a reboot or an app update ([RestartReceiver]), and if Android refuses to start it
 * in the background a notification asks the user to tap to resume.
 */
class MonitoringService : LifecycleService() {
    private var wakeLock: PowerManager.WakeLock? = null
    private var started = false

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (started) return START_STICKY
        val monitor = EpiProtPhoneApp.monitor(this)
        if (!monitor.consents.value.canMonitor) { stopSelf(); return START_NOT_STICKY }
        createChannels(this)
        // location may only be used by a service the user started from the app (while-in-use permission)
        val fromApp = intent?.getBooleanExtra(EXTRA_FROM_APP, false) == true
        var types = ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
        if (fromApp && monitor.consents.value.locationAllowed &&
            (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED))
            types = types or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        try {
            ServiceCompat.startForeground(this, NOTIFICATION_ID, notification(), types)
        } catch (e: Exception) {                 // background start not allowed on this Android version / state
            Log.w("EpiProt", "foreground start refused", e)
            askToResume(this)
            stopSelf()
            return START_NOT_STICKY
        }
        started = true
        getSystemService(NotificationManager::class.java).cancel(RESUME_ID)
        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "epiprot:phone-monitoring").apply { acquire() }
        monitor.start()
        return START_STICKY
    }

    override fun onDestroy() {
        EpiProtPhoneApp.monitor(this).stop()
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    private fun notification(): Notification = NotificationCompat.Builder(this, CHANNEL)
        .setSmallIcon(R.drawable.ic_epiprot)
        .setContentTitle(getString(R.string.notif_monitoring))
        .setContentText(getString(R.string.notif_monitoring_text))
        .setOngoing(true)
        .setContentIntent(PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE))
        .build()

    companion object {
        private const val CHANNEL = "monitoring"
        private const val CHANNEL_ALERTS = "monitoring_alerts"
        private const val NOTIFICATION_ID = 1
        private const val RESUME_ID = 2
        const val EXTRA_FROM_APP = "from_app"
        const val EXTRA_RESUME = "resume_monitoring"

        private fun prefs(c: Context) = c.getSharedPreferences("epiprot_run", Context.MODE_PRIVATE)

        /** The user wants monitoring on (kept across restarts, reboots and updates). */
        fun wanted(c: Context) = prefs(c).getBoolean("wanted", false)
        private fun setWanted(c: Context, v: Boolean) = prefs(c).edit().putBoolean("wanted", v).apply()

        /** Started by the user in the app. */
        fun start(c: Context) {
            setWanted(c, true)
            ContextCompat.startForegroundService(c, Intent(c, MonitoringService::class.java).putExtra(EXTRA_FROM_APP, true))
        }

        /** Stopped by the user, or because the consent was withdrawn: it does not come back by itself. */
        fun stop(c: Context) {
            setWanted(c, false)
            c.stopService(Intent(c, MonitoringService::class.java))
        }

        /** After a reboot / app update: restart only if the user had it on and the consent still allows it. */
        fun restartIfWanted(c: Context) {
            if (!wanted(c) || !EpiProtPhoneApp.monitor(c).consents.value.canMonitor) return
            try {
                ContextCompat.startForegroundService(c, Intent(c, MonitoringService::class.java))
            } catch (e: Exception) {
                Log.w("EpiProt", "restart refused", e)
                askToResume(c)
            }
        }

        fun createChannels(c: Context) {
            val nm = c.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(CHANNEL, c.getString(R.string.channel_monitoring),
                NotificationManager.IMPORTANCE_LOW))
            nm.createNotificationChannel(NotificationChannel(CHANNEL_ALERTS, c.getString(R.string.channel_monitoring_alerts),
                NotificationManager.IMPORTANCE_HIGH))
        }

        /** "Monitoring is not running – tap to resume" (opens the app, which starts the service in the foreground). */
        fun askToResume(c: Context) {
            createChannels(c)
            val open = PendingIntent.getActivity(c, 1, Intent(c, MainActivity::class.java).putExtra(EXTRA_RESUME, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val n = NotificationCompat.Builder(c, CHANNEL_ALERTS)
                .setSmallIcon(R.drawable.ic_epiprot)
                .setContentTitle(c.getString(R.string.notif_resume_title))
                .setContentText(c.getString(R.string.notif_resume_text))
                .setStyle(NotificationCompat.BigTextStyle().bigText(c.getString(R.string.notif_resume_text)))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setOngoing(true)
                .setContentIntent(open)
                .build()
            try { c.getSystemService(NotificationManager::class.java).notify(RESUME_ID, n) } catch (_: SecurityException) { }
        }
    }
}

/** Brings monitoring back after a reboot or an app update. */
class RestartReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED -> MonitoringService.restartIfWanted(context)
        }
    }
}

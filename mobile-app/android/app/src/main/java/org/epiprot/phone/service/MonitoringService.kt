package org.epiprot.phone.service

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.PowerManager
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
 * plus "location" when allowed, so the caregiver message can include the position).
 */
class MonitoringService : LifecycleService() {
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.channel_monitoring),
            NotificationManager.IMPORTANCE_LOW))
        var types = ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
        if (EpiProtPhoneApp.monitor(this).consents.value.locationAllowed &&
            (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED))
            types = types or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notification(), types)
        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "epiprot:phone-monitoring").apply { acquire() }
        EpiProtPhoneApp.monitor(this).start()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
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
        private const val NOTIFICATION_ID = 1

        fun start(c: Context) = ContextCompat.startForegroundService(c, Intent(c, MonitoringService::class.java))
        fun stop(c: Context) = c.stopService(Intent(c, MonitoringService::class.java))
    }
}

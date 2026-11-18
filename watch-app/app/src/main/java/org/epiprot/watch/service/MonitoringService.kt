package org.epiprot.watch.service

import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.PowerManager
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import org.epiprot.watch.EpiProtApp
import org.epiprot.watch.feedback.Notifications

/**
 * Keeps sensors and the phone link running while the screen is off ("health" foreground service).
 * A partial wake lock keeps the 1-second send loop going; battery use must be measured on a real watch.
 */
class MonitoringService : LifecycleService() {
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        ServiceCompat.startForeground(
            this, Notifications.ID_MONITORING, Notifications.monitoring(this),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_HEALTH,
        )
        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "epiprot:monitoring")
            .apply { acquire() }
        EpiProtApp.controller(this).startMonitoring()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        return START_STICKY
    }

    override fun onDestroy() {
        EpiProtApp.controller(this).stopMonitoring()
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    companion object {
        fun start(context: Context) =
            ContextCompat.startForegroundService(context, Intent(context, MonitoringService::class.java))
    }
}

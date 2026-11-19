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
        try {
            ServiceCompat.startForeground(
                this, Notifications.ID_MONITORING, Notifications.monitoring(this),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_HEALTH,
            )
        } catch (e: Exception) {          // not allowed from the background on this watch: ask the user to open the app
            android.util.Log.w("EpiProt", "foreground start refused", e)
            Notifications.resume(this)
            stopSelf()
            return
        }
        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "epiprot:monitoring")
            .apply { acquire() }
        Notifications.clearResume(this)
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
        private fun prefs(c: Context) = c.getSharedPreferences("epiprot_run", Context.MODE_PRIVATE)

        /** Started from the app: remembered, so it comes back after a reboot or an update. */
        fun start(context: Context) {
            prefs(context).edit().putBoolean("wanted", true).apply()
            ContextCompat.startForegroundService(context, Intent(context, MonitoringService::class.java))
        }

        fun restartIfWanted(context: Context) {
            if (!prefs(context).getBoolean("wanted", false)) return
            try {
                ContextCompat.startForegroundService(context, Intent(context, MonitoringService::class.java))
            } catch (e: Exception) {
                Notifications.resume(context)
            }
        }
    }
}

/** Brings the watch side back after a reboot or an app update. */
class RestartReceiver : android.content.BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED || intent.action == Intent.ACTION_MY_PACKAGE_REPLACED)
            MonitoringService.restartIfWanted(context)
    }
}

package org.epiprot.watch.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch
import org.epiprot.watch.EpiProtApp
import org.epiprot.watch.core.Screen
import org.epiprot.watch.service.MonitoringService

class MainActivity : ComponentActivity() {

    private var sensorPermission by mutableStateOf(false)

    private val askPermissions =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            sensorPermission = hasSensorPermission()
            MonitoringService.start(this)
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        val controller = EpiProtApp.controller(this)

        sensorPermission = hasSensorPermission()
        if (sensorPermission) MonitoringService.start(this) else requestPermissions()

        // keep the screen on while an alarm or check-in is shown
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                controller.screen.collect { s ->
                    val urgent = s is Screen.Alarm || s is Screen.AlarmActive || s is Screen.CheckIn
                    if (urgent) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                }
            }
        }

        setContent {
            EpiProtWatchApp(
                controller = controller,
                sensorPermission = sensorPermission,
                onRequestPermission = ::requestPermissions,
            )
        }
    }

    private fun heartPermission() =
        if (Build.VERSION.SDK_INT >= 36) "android.permission.health.READ_HEART_RATE" else Manifest.permission.BODY_SENSORS

    private fun hasSensorPermission() =
        ContextCompat.checkSelfPermission(this, heartPermission()) == PackageManager.PERMISSION_GRANTED

    private fun requestPermissions() {
        val wanted = buildList {
            add(heartPermission())
            if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
        }
        askPermissions.launch(wanted.toTypedArray())
    }
}

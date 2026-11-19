package org.epiprot.phone

import android.app.Application
import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.epiprot.phone.alarm.AlarmFlow
import org.epiprot.phone.alarm.FlowEffect
import org.epiprot.phone.comm.CaregiverMessenger
import org.epiprot.phone.comm.LocationProvider
import org.epiprot.phone.comm.WatchLink
import org.epiprot.phone.data.EventLog
import org.epiprot.phone.data.Settings
import org.epiprot.phone.engine.DemoRecording
import org.epiprot.phone.engine.EngineActions
import org.epiprot.phone.engine.EngineStatus
import org.epiprot.phone.engine.MonitoringEngine
import org.epiprot.phone.engine.WindowAssembler
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.model.DetectorConfig
import org.epiprot.phone.model.DetectorModels
import org.epiprot.phone.protocol.Paths
import org.epiprot.phone.protocol.PhoneMessage
import org.epiprot.phone.protocol.PinResult
import org.epiprot.phone.protocol.SensorBatch

class EpiProtPhoneApp : Application() {
    val monitor by lazy { PhoneMonitor(this) }

    companion object {
        fun monitor(c: Context) = (c.applicationContext as EpiProtPhoneApp).monitor
    }
}

data class DemoProgress(val window: Int, val windows: Int, val onsetS: Double, val score: Double, val finished: Boolean)

data class WatchState(val lastDataMs: Long = 0, val heartRate: Float = Float.NaN, val batteryPct: Int? = null)

/**
 * Connects the monitoring engine to the phone: watch messages in, 5 s windows through the
 * engine (on one thread), effects out (event log, SMS with location, watch messages).
 */
class PhoneMonitor(private val app: Context) {
    val settings = Settings(app)
    val log = EventLog(app)
    private val watchLink = WatchLink(app)
    private val messenger = CaregiverMessenger(app, settings, log, LocationProvider(app))

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    @OptIn(ExperimentalCoroutinesApi::class)
    private val engineThread = Dispatchers.Default.limitedParallelism(1)

    private val _running = MutableStateFlow(false)
    val running: StateFlow<Boolean> = _running
    private val _status = MutableStateFlow(EngineStatus())
    val status: StateFlow<EngineStatus> = _status
    private val _watch = MutableStateFlow(WatchState())
    val watch: StateFlow<WatchState> = _watch
    private val _demo = MutableStateFlow<DemoProgress?>(null)
    val demo: StateFlow<DemoProgress?> = _demo
    /** Increases whenever the event log changes (the screens reload their lists). */
    private val _logVersion = MutableStateFlow(0)
    val logVersion: StateFlow<Int> = _logVersion

    private var assembler: WindowAssembler? = null
    private var loop: Job? = null
    private var demoJob: Job? = null

    private val actions = object : EngineActions {
        override fun newDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean) =
            log.addDeviceEvent(alarmMs, onsetMs, demo).also { changed() }

        override fun flow(effect: FlowEffect, demo: Boolean) {
            when (effect) {
                is FlowEffect.Step -> log.step(effect.eventId, effect.timeMs, effect.step, effect.detail)
                is FlowEffect.Update -> log.update(effect.eventId, effect.fields)
                is FlowEffect.Sms -> scope.launch(Dispatchers.IO) {
                    messenger.send(effect.eventId, effect.message, demo); changed()
                }
                is FlowEffect.Watch -> Unit      // sent via watch()
            }
            changed()
        }

        override fun sensor(event: HealthMonitor.Event, demo: Boolean) {
            when (event) {
                is HealthMonitor.Event.Warning -> log.sensorWarning(event.episode, demo)
                is HealthMonitor.Event.Reminder -> log.sensorReminder(event.episode)
                is HealthMonitor.Event.Fixed -> log.sensorFixed(event.episode)
            }
            changed()
        }

        override fun watch(message: PhoneMessage) { scope.launch(Dispatchers.IO) { watchLink.send(message) } }
    }

    private val engine: MonitoringEngine by lazy {
        val a = app.assets
        val cfg = DetectorConfig.parse(a.open("model/detector.json").bufferedReader().readText())
        MonitoringEngine(cfg, DetectorModels.load(cfg) { f -> a.open("model/$f").bufferedReader().readText() }, actions)
    }

    private fun changed() { _logVersion.value++ }
    private fun publish() { _status.value = engine.status }

    fun start() {
        if (_running.value) return
        _running.value = true
        sendSettingsToWatch()
        loop = scope.launch(engineThread) {
            assembler = WindowAssembler(System.currentTimeMillis())
            while (isActive) {
                val now = System.currentTimeMillis()
                try {
                    for ((w, end) in assembler!!.closeReady(now)) if (!engine.demo) engine.onWindow(w, end)
                    engine.tick(now)
                    publish()
                } catch (e: Exception) {
                    Log.e("EpiProt", "monitoring loop", e)
                }
                delay(1_000)
            }
        }
    }

    fun stop() {
        loop?.cancel(); loop = null
        assembler = null
        _running.value = false
    }

    fun onWatchMessage(path: String, data: ByteArray) {
        scope.launch(engineThread) {
            val now = System.currentTimeMillis()
            try {
                when (path) {
                    Paths.SENSOR -> {
                        val b = SensorBatch.decode(data)
                        assembler?.addWatch(b)
                        _watch.value = _watch.value.copy(lastDataMs = now,
                            heartRate = if (b.heartRate.isFinite()) b.heartRate else _watch.value.heartRate)
                    }
                    Paths.PIN_RESULT -> { engine.onPin(PinResult.decode(data), now); publish() }
                    Paths.STATUS -> {
                        val j = org.json.JSONObject(String(data))
                        _watch.value = _watch.value.copy(batteryPct = j.optInt("battery_pct"))
                        // messages are not queued: a watch that was off / not listening missed the PIN
                        if (now - lastSettingsSentMs > 60_000) sendSettingsToWatch()
                        // the watch still shows an alarm the phone no longer has (phone restarted, demo stopped)
                        if (!j.isNull("alarm_id")) {
                            val wa = j.optLong("alarm_id")
                            if (wa != 0L && engine.flow.currentId() != wa) actions.watch(PhoneMessage.AlarmEnd(wa, "sync"))
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w("EpiProt", "bad watch message on $path", e)
            }
        }
    }

    fun resolveByCaregiver(wasSeizure: Boolean?) {
        scope.launch(engineThread) { engine.resolveByCaregiver(System.currentTimeMillis(), wasSeizure); publish() }
    }

    fun setPin(pin: String) { settings.setPin(pin); sendSettingsToWatch() }

    @Volatile private var lastSettingsSentMs = 0L

    private fun sendSettingsToWatch() {
        val salt = settings.pinSalt ?: return
        val hash = settings.pinHash ?: return
        lastSettingsSentMs = System.currentTimeMillis()
        actions.watch(PhoneMessage.Settings(salt, hash, 30))
    }

    /** Replays a recorded seizure: fast until the alarm, then real time; waits until the alarm flow is over. */
    fun startDemo() {
        if (demoJob?.isActive == true) return
        sendSettingsToWatch()
        demoJob = scope.launch(engineThread) {
            val rec = DemoRecording.parse(app.assets.open("demo/demo_seizure.bin").readBytes())
            engine.reset(demo = true)
            var realTime = false
            for ((i, w) in rec.windows.withIndex()) {
                val r = engine.onWindow(w, System.currentTimeMillis())
                if (r.alarm) realTime = true
                _demo.value = DemoProgress(i + 1, rec.windows.size, rec.onsetS, r.score, false)
                publish()
                if (realTime) repeat(5) { delay(1_000); engine.tick(System.currentTimeMillis()); publish() }
                else delay(400)
            }
            _demo.value = _demo.value?.copy(finished = true)
            while (engine.flow.state != AlarmFlow.State.Idle) {
                delay(1_000); engine.tick(System.currentTimeMillis()); publish()
            }
            endDemo()
        }
    }

    fun stopDemo() {
        demoJob?.cancel()
        scope.launch(engineThread) {
            if (engine.flow.state != AlarmFlow.State.Idle) engine.resolveByCaregiver(System.currentTimeMillis(), null)
            endDemo()
        }
    }

    private fun endDemo() {
        engine.reset(demo = false)
        _demo.value = null
        publish()
    }
}

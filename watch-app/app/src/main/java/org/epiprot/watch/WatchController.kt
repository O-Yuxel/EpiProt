package org.epiprot.watch

import android.content.Context
import android.os.BatteryManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.epiprot.watch.core.Effect
import org.epiprot.watch.core.Impact
import org.epiprot.watch.core.NightMode
import org.epiprot.watch.core.PinVerifier
import org.epiprot.watch.core.Screen
import org.epiprot.watch.core.SensorBatcher
import org.epiprot.watch.core.WarningCode
import org.epiprot.watch.core.WatchStateMachine
import org.epiprot.watch.feedback.Haptics
import org.epiprot.watch.feedback.Notifications
import org.epiprot.watch.link.PhoneLink
import org.epiprot.watch.protocol.Paths
import org.epiprot.watch.protocol.PhoneMessage
import org.epiprot.watch.protocol.PinResult
import org.epiprot.watch.protocol.WatchStatus
import org.epiprot.watch.sensors.DeviceSensors
import org.epiprot.watch.sensors.SensorSource
import org.epiprot.watch.sensors.SimulatedSensors

/**
 * Glue between the pure alarm logic (WatchStateMachine), the sensors, the phone link and the UI.
 * All state changes happen on the main thread.
 */
class WatchController(private val app: Context) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val machine = WatchStateMachine()
    private val haptics = Haptics(app)
    private val prefs = app.getSharedPreferences("epiprot", Context.MODE_PRIVATE)
    private var pin: PinVerifier = loadPin()

    val link = PhoneLink(app)
    private val batcher = SensorBatcher()
    private var sensors: SensorSource? = null
    private var jobs = mutableListOf<Job>()

    private val _screen = MutableStateFlow<Screen>(Screen.Home)
    val screen: StateFlow<Screen> = _screen
    private val _activeAlarm = MutableStateFlow<Long?>(null)
    /** Alarm running in the background while the home screen is shown. */
    val activeAlarm: StateFlow<Long?> = _activeAlarm
    private val _warnings = MutableStateFlow<Map<WarningCode, Impact>>(emptyMap())
    val warnings: StateFlow<Map<WarningCode, Impact>> = _warnings
    private val _warningDetails = MutableStateFlow<Map<WarningCode, String>>(emptyMap())
    val warningDetails: StateFlow<Map<WarningCode, String>> = _warningDetails
    private val nightMode = NightMode(prefs.getBoolean("night_enabled", true),
        prefs.getInt("night_start_min", 23 * 60), prefs.getInt("night_end_min", 7 * 60))
    private val _night = MutableStateFlow(false)
    /** Night mode active: non-urgent warnings do not vibrate. */
    val night: StateFlow<Boolean> = _night
    private val _heartRate = MutableStateFlow(Float.NaN)
    val heartRate: StateFlow<Float> = _heartRate
    private val _simulated = MutableStateFlow(false)
    val simulated: StateFlow<Boolean> = _simulated
    private val _demoPin = MutableStateFlow(pin.isDemo)
    val demoPin: StateFlow<Boolean> = _demoPin
    val phoneConnected: StateFlow<Boolean> get() = link.connected
    /** The phone's consent state: without it the sensors stay off (privacy first: off until the phone says yes). */
    private val _monitoringAllowed = MutableStateFlow(prefs.getBoolean("monitoring_allowed", false))
    val monitoringAllowed: StateFlow<Boolean> = _monitoringAllowed
    private var running = false
    private var sensorJob: Job? = null

    private var phoneLostSinceMs: Long? = null

    init {
        machine.setPinWindow(prefs.getInt("pin_window_s", 30))
        scope.launch {
            while (isActive) {
                apply(machine.setNight(nightMode.isNight(minuteOfDay()), now()) + machine.tick(now()))
                delay(250)
            }
        }
    }

    // ---------------------------------------------------------------- monitoring (from MonitoringService)

    fun startMonitoring() {
        if (running) return
        running = true
        updateSensors()
        jobs += scope.launch {        // find the phone, watch the connection
            while (isActive) {
                link.refresh()
                checkPhone()
                delay(10_000)
            }
        }
        jobs += scope.launch {        // status once a minute
            while (isActive) {
                sendStatus()
                delay(60_000)
            }
        }
    }

    fun stopMonitoring() {
        running = false
        jobs.forEach { it.cancel() }
        jobs.clear()
        stopSensors()
    }

    /** Sensors run only while monitoring is on AND the phone says the consent allows it. */
    private fun updateSensors() {
        if (running && _monitoringAllowed.value) startSensors() else stopSensors()
    }

    private fun startSensors() {
        if (sensors != null) return
        val device = DeviceSensors(app, batcher)
        val src: SensorSource = if (device.isReal) device else SimulatedSensors(batcher, scope)
        _simulated.value = !src.isReal
        src.start()
        sensors = src
        sensorJob = scope.launch {    // one sensor batch per second
            while (isActive) {
                delay(1000)
                val batch = batcher.flush(now(), src.onBody)
                _heartRate.value = batch.heartRate
                link.send(Paths.SENSOR, batch.encode())
            }
        }
    }

    private fun stopSensors() {
        sensorJob?.cancel()
        sensorJob = null
        sensors?.stop()
        sensors = null
        _heartRate.value = Float.NaN
    }

    // ---------------------------------------------------------------- phone messages

    fun onPhoneMessage(path: String, data: ByteArray) {
        val msg = PhoneMessage.decode(path, data) ?: return
        scope.launch { handle(msg) }
    }

    private fun handle(msg: PhoneMessage) {
        val t = now()
        when (msg) {
            is PhoneMessage.AlarmStart -> {
                machine.setPinWindow(msg.pinWindowS)
                apply(machine.alarmStart(msg.alarmId, t))
            }
            is PhoneMessage.AlarmEnd -> apply(machine.alarmEnd(msg.alarmId, t))
            is PhoneMessage.CheckIn -> apply(machine.checkIn(msg.alarmId, msg.number, t))
            is PhoneMessage.SensorWarning -> WarningCode.fromWire(msg.code)?.let {
                apply(machine.sensorWarning(it, Impact.fromWire(msg.impact), t, msg.detail, msg.urgent))
            }
            is PhoneMessage.SensorFixed -> WarningCode.fromWire(msg.code)?.let { apply(machine.sensorFixed(it, t)) }
            is PhoneMessage.ConsentState -> {
                prefs.edit().putBoolean("monitoring_allowed", msg.monitoringAllowed).apply()
                _monitoringAllowed.value = msg.monitoringAllowed
                updateSensors()
            }
            is PhoneMessage.CaregiverComing -> {
                _coming.value = msg.name
                haptics.short()
                Notifications.wake(app)
            }
            is PhoneMessage.Settings -> {
                prefs.edit().putString("pin_salt", msg.pinSalt).putString("pin_hash", msg.pinHash)
                    .putInt("pin_window_s", msg.pinWindowS).putBoolean("night_enabled", msg.nightEnabled)
                    .putInt("night_start_min", msg.nightStartMin).putInt("night_end_min", msg.nightEndMin).apply()
                nightMode.enabled = msg.nightEnabled
                nightMode.startMin = msg.nightStartMin
                nightMode.endMin = msg.nightEndMin
                pin = loadPin()
                _demoPin.value = pin.isDemo
                machine.setPinWindow(msg.pinWindowS)
            }
        }
    }

    // ---------------------------------------------------------------- user actions (from the UI)

    fun enterPin(digits: String) = apply(machine.pinEntered(pin.verify(digits), now()))

    fun dismiss() = apply(machine.dismiss(now()))
    fun goHome() = apply(machine.goHome())
    fun reopenAlarm() = apply(machine.reopenAlarm())

    fun openWarning(code: WarningCode) = apply(machine.openWarning(code))

    /** Night mode on / off by hand (until the schedule changes next). */
    fun toggleNight() {
        nightMode.toggle(minuteOfDay())
        apply(machine.setNight(nightMode.isNight(minuteOfDay()), now()))
    }

    // ---------------------------------------------------------------- demo without a phone

    private var demoAlarmId = 9000L

    // ---------------------------------------------------------------- call for help (SOS)
    /** null = nothing; COUNTDOWN until [sosAtMs]; SENT; QUEUED = phone not reachable, sent when it is back. */
    enum class Sos { COUNTDOWN, SENT, QUEUED }
    private val _sos = MutableStateFlow<Sos?>(null)
    val sos: StateFlow<Sos?> = _sos
    var sosAtMs = 0L
        private set
    private var sosJob: Job? = null

    /** "Call for help": 5 s to cancel a mistaken tap, then the phone alerts the caregivers. */
    fun sosStart() {
        if (_sos.value == Sos.COUNTDOWN) return
        sosAtMs = now() + SOS_COUNTDOWN_MS
        _sos.value = Sos.COUNTDOWN
        haptics.short()
        sosJob?.cancel()
        sosJob = scope.launch {
            delay(SOS_COUNTDOWN_MS)
            if (_sos.value != Sos.COUNTDOWN) return@launch
            val reachable = link.connected.value
            link.send(Paths.SOS, org.epiprot.watch.protocol.SosRequest(now()).encode())   // kept and sent later if offline
            _sos.value = if (reachable) Sos.SENT else Sos.QUEUED
            haptics.short()
        }
    }

    fun sosCancel() { sosJob?.cancel(); _sos.value = null }

    // ---------------------------------------------------------------- a caregiver answered "I am going"
    private val _coming = MutableStateFlow<String?>(null)
    /** Name of the caregiver on the way ("" = name unknown); null = nobody announced. */
    val coming: StateFlow<String?> = _coming
    fun dismissComing() { _coming.value = null }

    // ---------------------------------------------------------------- shower mode
    /**
     * CHOOSE the time; RUNNING until [showerEndsMs]; ASKING "Are you out?" for [SHOWER_ANSWER_MS]; NO_ANSWER = the
     * phone was told and alerts the caregiver. The phone runs the same timer as a backup (watch empty, out of reach).
     */
    enum class Shower { CHOOSE, RUNNING, ASKING, NO_ANSWER }
    private val _shower = MutableStateFlow<Shower?>(null)
    val shower: StateFlow<Shower?> = _shower
    var showerEndsMs = 0L
        private set
    private var showerSession = 0L
    private var showerMinutes = 15
    private var showerJob: Job? = null

    fun showerChoose() { if (_shower.value == null) _shower.value = Shower.CHOOSE }

    fun showerStart(minutes: Int) {
        showerSession = now(); showerMinutes = minutes
        showerEndsMs = showerSession + minutes * 60_000L
        _shower.value = Shower.RUNNING
        haptics.short()
        scope.launch { link.send(Paths.SHOWER, org.epiprot.watch.protocol.ShowerMessage("start", showerSession, minutes).encode()) }
        showerJob?.cancel()
        showerJob = scope.launch {
            delay((showerEndsMs - now()).coerceAtLeast(0))
            if (_shower.value != Shower.RUNNING) return@launch
            _shower.value = Shower.ASKING
            Notifications.wake(app)
            haptics.checkIn()
            delay(SHOWER_ANSWER_MS)
            if (_shower.value != Shower.ASKING) return@launch
            _shower.value = Shower.NO_ANSWER
            haptics.stop()
            link.send(Paths.SHOWER, org.epiprot.watch.protocol.ShowerMessage("overdue", showerSession, showerMinutes).encode())
        }
    }

    /** "I am out" (also after the caregiver was alerted: then the phone tells the caregiver all is well). */
    fun showerEnd() {
        showerJob?.cancel()
        haptics.stop()
        if (_shower.value != null && _shower.value != Shower.CHOOSE)
            scope.launch { link.send(Paths.SHOWER, org.epiprot.watch.protocol.ShowerMessage("end", showerSession, showerMinutes).encode()) }
        _shower.value = null
    }

    fun showerCancelChoose() { if (_shower.value == Shower.CHOOSE) _shower.value = null }
    fun sosClose() { _sos.value = null }

    fun demoAlarm() = handle(PhoneMessage.AlarmStart(++demoAlarmId, 30))
    fun demoCheckIn() = handle(PhoneMessage.CheckIn(demoAlarmId, 1))
    fun demoAlarmEnd() = handle(PhoneMessage.AlarmEnd(demoAlarmId, "demo"))
    fun demoWarning() = handle(PhoneMessage.SensorWarning(WarningCode.BRAIN_WEAK.wire, Impact.LIMITED.wire))
    fun demoFixed() = handle(PhoneMessage.SensorFixed(WarningCode.BRAIN_WEAK.wire))
    fun demoPad() = handle(PhoneMessage.SensorWarning(WarningCode.PAD_REPLACE.wire, Impact.NONE.wire, "L-bottom", urgent = false))
    fun demoShaking(on: Boolean) {
        (sensors as? SimulatedSensors)?.shaking = on
    }

    // ---------------------------------------------------------------- internals

    private fun apply(effects: List<Effect>) {
        _screen.value = machine.screen
        _activeAlarm.value = machine.activeAlarm
        _warnings.value = machine.activeWarnings.toMap()
        _warningDetails.value = machine.activeDetails.toMap()
        _night.value = machine.night
        for (e in effects) when (e) {
            is Effect.SendPin -> scope.launch {
                link.send(Paths.PIN_RESULT, PinResult(e.context, e.alarmId, e.ok, e.attempt, now()).encode())
            }
            Effect.VibrateAlarm -> haptics.alarm()
            Effect.VibrateCheckIn -> haptics.checkIn()
            Effect.VibrateWarning -> haptics.warning()
            Effect.VibrateShort -> haptics.short()
            Effect.StopVibration -> haptics.stop()
            Effect.WakeScreen -> Notifications.wake(app)
        }
    }

    /** The phone runs the detection model: without it there are no alarms, so the patient must know. */
    private fun checkPhone() {
        val t = now()
        if (link.connected.value) {
            phoneLostSinceMs = null
            if (WarningCode.PHONE_DISCONNECTED in machine.activeWarnings) {
                apply(machine.sensorFixed(WarningCode.PHONE_DISCONNECTED, t))
            }
        } else {
            val since = phoneLostSinceMs ?: t.also { phoneLostSinceMs = it }
            if (t - since >= PHONE_LOST_WARN_MS && WarningCode.PHONE_DISCONNECTED !in machine.activeWarnings) {
                apply(machine.sensorWarning(WarningCode.PHONE_DISCONNECTED, Impact.NO_ALARMS, t))
            }
        }
    }

    private suspend fun sendStatus() {
        val bm = app.getSystemService(BatteryManager::class.java)
        val status = WatchStatus(
            batteryPct = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY),
            charging = bm.isCharging,
            onBody = sensors?.onBody,
            heartSensor = if (_simulated.value) "simulated" else "device",
            timeMs = now(),
            alarmId = machine.runningAlarm(),
            monitoringAllowed = _monitoringAllowed.value,
        )
        link.send(Paths.STATUS, status.encode(), keepIfOffline = false)
    }

    private fun loadPin(): PinVerifier {
        val salt = prefs.getString("pin_salt", null)
        val hash = prefs.getString("pin_hash", null)
        return if (salt != null && hash != null) PinVerifier(salt, hash) else PinVerifier.demo()
    }

    private fun now() = System.currentTimeMillis()

    private fun minuteOfDay(): Int {
        val c = java.util.Calendar.getInstance()
        return c.get(java.util.Calendar.HOUR_OF_DAY) * 60 + c.get(java.util.Calendar.MINUTE)
    }

    companion object {
        const val PHONE_LOST_WARN_MS = 60_000L
        const val SOS_COUNTDOWN_MS = 5_000L
        const val SHOWER_ANSWER_MS = 120_000L
    }
}

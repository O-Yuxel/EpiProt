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


/** Semi-dry pads last several days (HARDWARE.md D1); the contact check warns earlier if one dries out. */
private const val PAD_DAYS = 5
/** One set of pads: L-top, L-bottom, R-top, R-bottom and the small bias pad. */
private const val PADS_PER_SET = 5

class EpiProtPhoneApp : Application() {
    val monitor by lazy { PhoneMonitor(this) }

    companion object {
        fun monitor(c: Context) = (c.applicationContext as EpiProtPhoneApp).monitor
    }
}

data class DemoProgress(val window: Int, val windows: Int, val onsetS: Double, val score: Double, val finished: Boolean,
                        val headband: Boolean = false)

data class WatchState(val lastDataMs: Long = 0, val heartRate: Float = Float.NaN, val batteryPct: Int? = null)

/**
 * Connects the monitoring engine to the phone: watch messages in, 5 s windows through the
 * engine (on one thread), effects out (event log, SMS with location, watch messages).
 */
class PhoneMonitor(private val app: Context) {
    val settings = Settings(app)
    val log = EventLog.open(app)
    val consentStore = org.epiprot.phone.privacy.ConsentStore(app)
    private val _consents = MutableStateFlow(consentStore.state())
    /** Current consent answers (the screens and every data flow check these). */
    val consents: StateFlow<org.epiprot.phone.privacy.ConsentState> = _consents
    private val watchLink = WatchLink(app)
    /** Signals around alarms (only with consent) -> encrypted database. */
    private val recorder = org.epiprot.phone.signals.SignalRecorder({ _consents.value.signalsAllowed }) { s ->
        scope.launch(Dispatchers.IO) { log.saveSignal(s.eventId, org.epiprot.phone.signals.SignalSnippet.encode(s)); changed() }
    }
    private val messenger = CaregiverMessenger(app, settings, log, LocationProvider(app)) { _consents.value }

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

    /** Live 5 s windows (headband + watch) and late headband data after a gap; null while monitoring is off. */
    private var pipeline: org.epiprot.phone.headband.HeadbandPipeline? = null

    // ---------------------------------------------------------------- headband (Bluetooth LE)
    private val _headbandLink = MutableStateFlow(org.epiprot.phone.headband.HeadbandLink.State.IDLE)
    val headbandLink: StateFlow<org.epiprot.phone.headband.HeadbandLink.State> = _headbandLink
    private var hbReceiver: org.epiprot.phone.headband.HeadbandReceiver? = null
    private var hbLastPublish = 0L
    private var hbAckJob: Job? = null
    private val _hbPaired = MutableStateFlow(settings.headbandAddress != null)
    /** A headband is paired with this phone (bonded with the passkey, or the test band connected once). */
    val headbandPaired: StateFlow<Boolean> = _hbPaired
    private val _hbNote = MutableStateFlow<String?>(null)
    /** Last thing the patient did / what went wrong: pair_failed, off, disconnected (null = nothing to say). */
    val headbandNote: StateFlow<String?> = _hbNote

    /** Live headband data go into the same 5 s windows as the watch data (only while monitoring runs). */
    private val hbSink = object : org.epiprot.phone.headband.HeadbandSink {
        override fun eeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) { pipeline?.eeg(firstMs, uv, leadOff) }
        override fun movement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) { pipeline?.movement(tMs, accG, gyrDps) }
        override fun lateEeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) { pipeline?.lateEeg(firstMs, uv, leadOff) }
        override fun lateMovement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) { pipeline?.lateMovement(tMs, accG, gyrDps) }
    }

    private val hbLink by lazy {
        org.epiprot.phone.headband.HeadbandLink(app, object : org.epiprot.phone.headband.HeadbandLink.Listener {
            override fun onInfo(info: org.epiprot.phone.headband.HeadbandProtocol.DeviceInfo, address: String) {
                settings.headbandAddress = address
                _hbPaired.value = true
                _hbNote.value = null
                scope.launch(engineThread) { hbReceiver = org.epiprot.phone.headband.HeadbandReceiver(info, hbSink) }
            }
            override fun onPacket(arrivalMs: Long, bytes: ByteArray) {
                scope.launch(engineThread) {
                    val rx = hbReceiver ?: return@launch
                    try { rx.onPacket(arrivalMs, bytes) } catch (e: Exception) { Log.w("EpiProt", "bad headband packet", e); return@launch }
                    val type = bytes[0].toInt() and 0xFF
                    val stateChanged = type == org.epiprot.phone.headband.HeadbandProtocol.TYPE_STATUS ||
                        type == org.epiprot.phone.headband.HeadbandProtocol.TYPE_CONTACT
                    if (!engine.demo && (stateChanged || arrivalMs - hbLastPublish > 1_000)) {
                        engine.onHeadbandState(rx.state, arrivalMs)
                        hbLastPublish = arrivalMs
                        publish()
                    }
                }
            }
            override fun onState(state: org.epiprot.phone.headband.HeadbandLink.State) { _headbandLink.value = state }
            override fun onPairResult(ok: Boolean, address: String?) {
                if (ok && address != null) { settings.headbandAddress = address; _hbPaired.value = true; _hbNote.value = null }
                else _hbNote.value = "pair_failed"
            }
        })
    }

    fun hasBluetoothPermission(): Boolean = android.os.Build.VERSION.SDK_INT < 31 ||
        listOf(android.Manifest.permission.BLUETOOTH_SCAN, android.Manifest.permission.BLUETOOTH_CONNECT).all {
            androidx.core.content.ContextCompat.checkSelfPermission(app, it) == android.content.pm.PackageManager.PERMISSION_GRANTED
        }

    /** First use: find the headband in pairing mode and bond (Android asks for the passkey). */
    fun pairHeadband(): Boolean = startLink { hbLink.pair() }

    /** Test headband (second phone) only: no passkey. */
    fun connectHeadbandWithoutPasskey(): Boolean = startLink { hbLink.connectWithoutPasskey() }

    /** Connect to the paired headband; also done by itself when monitoring starts. */
    fun connectHeadband(): Boolean = startLink { hbLink.connect(settings.headbandAddress) }

    private fun startLink(go: () -> Unit): Boolean {
        if (!hasBluetoothPermission()) return false
        _hbNote.value = null
        go()
        if (hbAckJob?.isActive != true) hbAckJob = scope.launch(engineThread) {
            while (isActive) {
                delay(5_000)
                hbReceiver?.ackSeq()?.takeIf { it >= 0 }?.let { hbLink.sendAck(it) }
            }
        }
        return true
    }

    /** The patient disconnects in the app: the band stays on, but its data are not used (detection off). */
    fun disconnectHeadband() {
        hbLink.disconnect(); hbAckJob?.cancel()
        turnedOff("disconnected")
    }

    // ---------------------------------------------------------------- pads (semi-dry, changed every few days)
    /**
     * The patient put on new pads: remember the day, take one set (4 pads + the small bias pad) from the spare
     * pads and measure the contact at once.
     */
    fun padsChanged(nowMs: Long = System.currentTimeMillis()) {
        settings.padChangedMs = nowMs
        if (settings.padStock >= 0) settings.padStock = (settings.padStock - PADS_PER_SET).coerceAtLeast(0)
        settings.padReminderMs = 0
        org.epiprot.phone.service.PhoneAlerts.fixed(app, "pads_change_due")
        requestContactCheck()
    }

    /** At most one reminder a day: pads older than [PAD_DAYS] days, or fewer than two sets of spare pads. */
    private fun checkPads(nowMs: Long) {
        val s = settings
        if (s.padChangedMs == 0L || nowMs - s.padReminderMs < 24 * 3_600_000L) return
        val days = ((nowMs - s.padChangedMs) / (24 * 3_600_000L)).toInt()
        var shown = false
        if (days >= PAD_DAYS) {
            org.epiprot.phone.service.PhoneAlerts.warning(app, "pads_change_due", "none", "$days", urgent = false); shown = true
        }
        if (s.padStock in 0 until 2 * PADS_PER_SET) {
            org.epiprot.phone.service.PhoneAlerts.warning(app, "pads_stock_low", "none", "${s.padStock}", urgent = false); shown = true
        }
        if (shown) s.padReminderMs = nowMs
    }

    /** A seizure added by hand (seizure diary); see EventLog.addManualEvent. */
    fun addManualSeizure(timeMs: Long, type: String, worn: String, note: String) {
        scope.launch(Dispatchers.IO) { log.addManualEvent(timeMs, type, worn, note); changed() }
    }

    fun deleteManualSeizure(eventId: Long) { scope.launch(Dispatchers.IO) { log.deleteEvent(eventId); changed() } }

    /** This phone became a caregiver phone: let go of the headband without telling the watch anything. */
    fun disconnectHeadbandQuietly() { hbLink.disconnect(); hbAckJob?.cancel() }

    /** The patient switches the headband off in the app. */
    fun powerOffHeadband() {
        hbLink.powerOff()
        turnedOff("off")
    }

    /** The patient unpairs the headband (e.g. new phone or new band). */
    fun unpairHeadband() {
        hbLink.unpair(); hbAckJob?.cancel()
        settings.headbandAddress = null
        _hbPaired.value = false
        turnedOff("unpaired")
    }

    private fun turnedOff(how: String) {
        _hbNote.value = how
        scope.launch(engineThread) {
            if (!engine.demo) { engine.onHeadbandTurnedOff(how, System.currentTimeMillis()); publish() }
        }
    }

    fun requestContactCheck() = hbLink.requestContactCheck()
    private var loop: Job? = null
    private var demoJob: Job? = null

    private val actions = object : EngineActions {
        override fun newDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean) =
            log.addDeviceEvent(alarmMs, onsetMs, demo).also { id ->
                Log.i("EpiProt", "seizure alarm id=$id alarmMs=$alarmMs estimatedOnsetMs=$onsetMs demo=$demo")
                recorder.onAlarm(id, alarmMs, onsetMs); changed()
            }

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
            val ep = event.episode
            if (!demo) when (event) {   // on the phone too: the watch may be empty, charging or not worn
                is HealthMonitor.Event.Warning -> {
                    val urgent = org.epiprot.phone.headband.WarningPolicy.urgent(ep.code, ep.impact)
                    val watchOk = System.currentTimeMillis() - _watch.value.lastDataMs < 15_000
                    if (urgent || !watchOk) org.epiprot.phone.service.PhoneAlerts.warning(app, ep.code, ep.impact, ep.detail, urgent)
                }
                is HealthMonitor.Event.Fixed -> org.epiprot.phone.service.PhoneAlerts.fixed(app, ep.code)
                else -> Unit
            }
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

    // ------------------------------------------------------------------ consents

    /** Re-reads the stored answers after a change. Withdrawing the health-data consent stops monitoring at once. */
    fun consentsChanged() {
        _consents.value = consentStore.state()
        actions.watch(PhoneMessage.ConsentState(_consents.value.canMonitor))
        if (!_consents.value.signalsAllowed) scope.launch(Dispatchers.IO) { log.deleteSignals() }   // withdrawn: delete them
        if (!_consents.value.canMonitor && _running.value) {
            org.epiprot.phone.service.MonitoringService.stop(app)
            stop()
        }
        changed()
    }

    /** Newly added caregivers get one SMS telling them who added them and how to opt out (only with the SMS consent). */
    fun sendCaregiverIntro(numbers: List<String>) {
        if (numbers.isEmpty()) return
        scope.launch(Dispatchers.IO) { for (n in numbers) messenger.sendIntro(n); changed() }
    }

    // ------------------------------------------------------------------ doctor report

    private val reportDir get() = java.io.File(app.cacheDir, "reports")

    init {   // retention: signals around alarms are kept for at most 12 months
        scope.launch(Dispatchers.IO) { runCatching { log.deleteSignalsOlderThan(365L * 86_400_000) } }
    }

    /** Stored signal snippets of the given events (at most [max], newest first). */
    fun signalsFor(eventIds: List<Long>, max: Int = 12): Map<Long, org.epiprot.phone.signals.SignalSnippet> {
        val have = log.signalIds()
        return eventIds.filter { it in have }.sortedDescending().take(max).mapNotNull { id ->
            log.signal(id)?.let { runCatching { org.epiprot.phone.signals.SignalSnippet.decode(it) }.getOrNull() }?.let { id to it }
        }.toMap()
    }

    fun reportData(fromMs: Long, toMs: Long, includeDemo: Boolean) = org.epiprot.phone.report.ReportData.build(
        log.eventsBetween(fromMs, toMs), log.sensorAlertsBetween(fromMs, toMs), fromMs, toMs, includeDemo)

    /** Writes the PDF into the app's cache (old reports are removed first). */
    fun createReport(d: org.epiprot.phone.report.ReportData, withSignals: Boolean = true): java.io.File {
        reportDir.listFiles()?.forEach { it.delete() }
        val name = "EpiProt-report-" + java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).format(java.util.Date()) + ".pdf"
        val f = java.io.File(reportDir, name)
        val signals = if (withSignals) signalsFor(d.events.map { it.eventId }) else emptyMap()
        org.epiprot.phone.report.ReportPdf.write(app, d, settings.patientName, f, signals)
        return f
    }

    fun reportShared(d: org.epiprot.phone.report.ReportData) {
        settings.lastReportMs = d.toMs
        consentStore.reportShared(d.fromMs, d.toMs, d.events.size)
        consentsChanged()
    }

    /** True while an alarm or the recovery follow-up is running: consents cannot be changed then (safety). */
    val alarmBusy: Boolean get() = engine.flow.state != AlarmFlow.State.Idle

    /** "Delete all my data": stops monitoring, erases the log, settings, consents and their history. */
    fun deleteAllData() {
        org.epiprot.phone.service.MonitoringService.stop(app)
        stop()
        demoJob?.cancel()
        log.clearAll()
        settings.clearAll()
        reportDir.listFiles()?.forEach { it.delete() }
        consentStore.clearAll()
        _demo.value = null
        consentsChanged()
    }

    /** "Download my data": one JSON file in the phone's Downloads folder. Returns its name, or null on failure. */
    fun exportData(): String? = try {
        val json = org.json.JSONObject()
            .put("exported_at", java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssZ", java.util.Locale.US).format(java.util.Date()))
            .put("app", "EpiProt").put("note", "All data EpiProt keeps on this phone.")
            .put("settings", settings.exportJson())
            .put("consents", org.json.JSONObject()
                .put("current", consentJson())
                .put("history", consentStore.historyJson()))
            .put("log", log.exportJson())
        val name = "epiprot-data-" + java.text.SimpleDateFormat("yyyyMMdd-HHmm", java.util.Locale.US).format(java.util.Date()) + ".json"
        val values = android.content.ContentValues().apply {
            put(android.provider.MediaStore.Downloads.DISPLAY_NAME, name)
            put(android.provider.MediaStore.Downloads.MIME_TYPE, "application/json")
        }
        val uri = app.contentResolver.insert(android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)!!
        app.contentResolver.openOutputStream(uri)!!.use { it.write(json.toString(2).toByteArray()) }
        name
    } catch (e: Exception) {
        Log.w("EpiProt", "export failed", e); null
    }

    private fun consentJson(): org.json.JSONObject {
        val c = _consents.value
        return org.json.JSONObject().put("region", c.region?.key).put("child_under13", c.childUnder13).put("role", c.role?.key).put("consenter", c.consenter).put("text_version", c.doneVersion)
            .put("acknowledged", org.json.JSONArray(c.acks.map { it.key }))
            .put("granted", org.json.JSONArray(c.granted.map { it.key }))
            .put("declined", org.json.JSONArray((c.decided - c.granted).map { it.key }))
    }
    private fun publish() { _status.value = engine.status }

    fun start() {
        if (_running.value) return
        if (!_consents.value.canMonitor) return          // no health-data consent: nothing is processed
        _running.value = true
        sendSettingsToWatch()
        if (_hbPaired.value) connectHeadband()           // the paired headband is connected by itself
        loop = scope.launch(engineThread) {
            pipeline = org.epiprot.phone.headband.HeadbandPipeline(System.currentTimeMillis(),
                onWindow = { w, end -> if (!engine.demo) { recorder.add(w, end); engine.onWindow(w, end) } },
                onLateWindow = { w, end ->
                    if (!engine.demo) {
                        engine.onLateWindow(w, end)
                        recorder.replace(w, end)
                        Log.i("EpiProt", "late headband window rebuilt, end=$end")
                    }
                })
            var lastBatteryMs = 0L
            while (isActive) {
                val now = System.currentTimeMillis()
                try {
                    if (now - lastBatteryMs > 60_000 && !engine.demo) {      // the phone's own battery, once a minute
                        lastBatteryMs = now
                        checkPads(now)
                        val bm = app.getSystemService(android.os.BatteryManager::class.java)
                        engine.onDeviceBattery("phone", bm.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY),
                            bm.isCharging, now)
                    }
                    pipeline!!.tick(now)
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
        pipeline = null
        _running.value = false
    }

    fun onWatchMessage(path: String, data: ByteArray) {
        scope.launch(engineThread) {
            val now = System.currentTimeMillis()
            try {
                when (path) {
                    Paths.SENSOR -> {
                        val b = SensorBatch.decode(data)
                        pipeline?.addWatch(b)
                        _watch.value = _watch.value.copy(lastDataMs = now,
                            heartRate = if (b.heartRate.isFinite()) b.heartRate else _watch.value.heartRate)
                    }
                    Paths.PIN_RESULT -> { engine.onPin(PinResult.decode(data), now); publish() }
                    Paths.SOS -> {                  // "Call for help" on the watch: caregivers get an SMS with the location
                        val t = org.epiprot.phone.protocol.SosRequest.decode(data).timeMs
                        val id = log.addHelpEvent(t)
                        log.step(id, now, "help", "patient pressed \"Call for help\" on the watch")
                        changed()
                        scope.launch(Dispatchers.IO) { messenger.send(id, org.epiprot.phone.alarm.CaregiverMessage.SOS, false); changed() }
                    }
                    Paths.STATUS -> {
                        val j = org.json.JSONObject(String(data))
                        _watch.value = _watch.value.copy(batteryPct = j.optInt("battery_pct"))
                        if (!engine.demo) engine.onDeviceBattery("watch", j.optInt("battery_pct", -1), j.optBoolean("charging"), now)
                        // messages are not queued: a watch that was off / not listening missed the PIN
                        if (now - lastSettingsSentMs > 60_000) sendSettingsToWatch()
                        // the watch's idea of the consent differs (message missed): tell it again
                        val allowed = _consents.value.canMonitor
                        if (j.isNull("monitoring_allowed") || j.optBoolean("monitoring_allowed") != allowed)
                            actions.watch(PhoneMessage.ConsentState(allowed))
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
        actions.watch(PhoneMessage.Settings(salt, hash, 30, settings.nightEnabled, settings.nightStartMin, settings.nightEndMin))
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
                val endMs = System.currentTimeMillis()
                recorder.add(w, endMs)
                val r = engine.onWindow(w, endMs)
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

    /**
     * Virtual headband: a real seizure (SeizeIT2 sub-058) as Bluetooth packets of the designed headband
     * (assets/demo/headband_demo.ehb, tools/make_headband_demo.py), through the same receiver, window
     * assembler, model and alarm flow as a real headband. Fast until the alarm, then real time.
     */
    fun startHeadbandDemo() {
        if (demoJob?.isActive == true) return
        sendSettingsToWatch()
        demoJob = scope.launch(engineThread) {
            val stream = org.epiprot.phone.headband.HeadbandStream.parse(app.assets.open("demo/headband_demo.ehb").readBytes())
            val onset = stream.meta.optDouble("onset_s", 600.0)
            val total = (stream.meta.optDouble("dur_s", 900.0) / 5).toInt()
            engine.reset(demo = true)
            var realTime = false
            var i = 0
            var checkStream = 0L        // contact-check time in the stream's own clock ...
            var checkWall = 0L          // ... and when it was replayed
            for (step in org.epiprot.phone.headband.HeadbandReplay(stream).steps()) {
                val now = System.currentTimeMillis()
                when (step) {
                    is org.epiprot.phone.headband.HeadbandReplay.Step.State -> {
                        val s = step.state
                        if (s.lastContactCheckMs != checkStream) { checkStream = s.lastContactCheckMs; checkWall = now }
                        engine.onHeadbandState(s.copy(lastPacketMs = now, lastContactCheckMs = checkWall), now); publish()
                    }
                    is org.epiprot.phone.headband.HeadbandReplay.Step.Window -> {
                        i++
                        recorder.add(step.input, now)
                        val r = engine.onWindow(step.input, now)
                        if (r.alarm) realTime = true
                        _demo.value = DemoProgress(i, total, onset, r.score, false, headband = true)
                        publish()
                        if (realTime) repeat(5) { delay(1_000); engine.tick(System.currentTimeMillis()); publish() }
                        else delay(400)
                    }
                }
            }
            _demo.value = _demo.value?.copy(finished = true)
            while (engine.flow.state != AlarmFlow.State.Idle) {
                delay(1_000); engine.tick(System.currentTimeMillis()); publish()
            }
            endDemo()
        }
    }

    /** Night mode of the watch (non-urgent warnings without vibration); sent to the watch at once. */
    fun setNightMode(enabled: Boolean, startMin: Int, endMin: Int) {
        settings.nightEnabled = enabled
        settings.nightStartMin = startMin
        settings.nightEndMin = endMin
        sendSettingsToWatch()
    }

    fun stopDemo() {
        demoJob?.cancel()
        scope.launch(engineThread) {
            if (engine.flow.state != AlarmFlow.State.Idle) engine.resolveByCaregiver(System.currentTimeMillis(), null)
            endDemo()
        }
    }

    private fun endDemo() {
        recorder.flush()
        engine.reset(demo = false)
        _demo.value = null
        publish()
    }
}

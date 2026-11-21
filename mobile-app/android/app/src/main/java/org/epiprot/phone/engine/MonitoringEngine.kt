package org.epiprot.phone.engine

import org.epiprot.phone.alarm.AlarmFlow
import org.epiprot.phone.alarm.FlowEffect
import org.epiprot.phone.headband.HeadbandAlerts
import org.epiprot.phone.headband.HeadbandState
import org.epiprot.phone.headband.WarningPolicy
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.model.Detector
import org.epiprot.phone.model.DetectorConfig
import org.epiprot.phone.model.DetectorModels
import org.epiprot.phone.model.WindowFeatures
import org.epiprot.phone.model.WindowInput
import org.epiprot.phone.model.WindowResult
import org.epiprot.phone.protocol.PhoneMessage
import org.epiprot.phone.protocol.PinResult

/** What the engine needs from the phone (event log, SMS, watch); faked in the unit tests. */
interface EngineActions {
    fun newDeviceEvent(alarmMs: Long, onsetMs: Long, demo: Boolean): Long
    fun flow(effect: FlowEffect, demo: Boolean)
    fun sensor(event: HealthMonitor.Event, demo: Boolean)
    fun watch(message: PhoneMessage)
}

data class EngineStatus(
    val windows: Long = 0,
    val lastScore: Double = 0.0,
    val fallback: Boolean = false,
    val noHeartRate: Boolean = false,
    val quality: Map<String, HealthMonitor.Quality> = emptyMap(),
    val heartRate: Double = Double.NaN,
    val flowState: AlarmFlow.State = AlarmFlow.State.Idle,
    val openWarnings: List<HealthMonitor.Episode> = emptyList(),
    val demo: Boolean = false,
    val headband: HeadbandState? = null,
    val channels: org.epiprot.phone.headband.Channels.Choice? = null,   // EEG channels of the last headband window
)

/**
 * The phone's monitoring chain for every 5 s window:
 * window features -> sensor health (warnings to the watch) -> detector -> alarm flow.
 * Headband reports (contact, pads, battery, charging) give their own warnings (HeadbandAlerts);
 * every warning goes to the watch with its urgency for night mode (WarningPolicy).
 */
class MonitoringEngine(
    private val cfg: DetectorConfig,
    private val models: DetectorModels,
    private val actions: EngineActions,
) {
    private var detector = Detector(cfg, models)
    private var health = HealthMonitor()
    private var alerts = HeadbandAlerts()
    /** Headband warnings of the health monitor held back while the band is charging ("charging" says it). */
    private val heldBack = HashSet<String>()
    private val ends = ArrayDeque<Long>()           // end times of the last processed windows, newest last
    val flow = AlarmFlow()
    var demo = false
        private set
    var status = EngineStatus()
        private set

    /** Fresh detector / health state, e.g. for a demo replay or after a long interruption. */
    fun reset(demo: Boolean) {
        detector = Detector(cfg, models)
        health = HealthMonitor()
        alerts = HeadbandAlerts()
        heldBack.clear()
        ends.clear()
        this.demo = demo
        status = EngineStatus(demo = demo)
    }

    fun onWindow(w: WindowInput, endMs: Long): WindowResult {
        val f = WindowFeatures.compute(w)
        val q = HealthMonitor.quality(f)          // electrode contact: HeadbandAlerts, from the lead-off bits
        for (e in health.next(q, endMs, flow.busy)) sendHealth(e)
        w.channels?.let { c -> for (e in alerts.onWindow(w.leadOff, c.contactOk, endMs)) send(e) }
        val r = detector.next(f, w)
        ends.addLast(endMs); if (ends.size > 150) ends.removeFirst()
        if (r.alarm) {
            val onsetMs = endMs - (r.index - r.onsetIndex!! + 1) * WindowAssembler.WINDOW_MS
            val id = actions.newDeviceEvent(endMs, onsetMs, demo)
            dispatch(flow.onAlarm(id, endMs, onsetMs))
        }
        r.seizureEndedIndex?.let { e ->
            dispatch(flow.onSeizureEnded(endMs - (r.index - e) * WindowAssembler.WINDOW_MS, endMs))
        }
        dispatch(flow.tick(endMs))
        status = status.copy(windows = r.index + 1, lastScore = r.score, fallback = r.fallback, noHeartRate = r.noHeartRate, quality = q,
            heartRate = f["ecg_hr"] ?: Double.NaN, flowState = flow.state, openWarnings = openWarnings(),
            channels = w.channels ?: status.channels)
        return r
    }

    /**
     * Headband data that arrived late (after a Bluetooth gap) for the window ending at [endMs]: the
     * detector's memory of the recent past gets the real values (no score, no alarm for the past).
     */
    fun onLateWindow(w: WindowInput, endMs: Long) {
        val pos = ends.lastIndexOf(endMs)
        if (pos < 0) return
        detector.backfill(ends.size - 1 - pos, WindowFeatures.compute(w), w)
    }

    /** New headband state (status packet or contact check), from the headband receiver. */
    fun onHeadbandState(s: HeadbandState, nowMs: Long) {
        val wasCharging = alerts.charging
        for (e in alerts.onState(s, nowMs)) send(e)
        if (wasCharging && !alerts.charging) {     // charging over: problems that are still there are now told
            for (ep in health.openEpisodes) if (ep.code in heldBack) send(HealthMonitor.Event.Warning(ep))
            heldBack.clear()
        }
        status = status.copy(headband = s, openWarnings = openWarnings())
    }

    private fun openWarnings() = health.openEpisodes.filter { it.code !in heldBack } + alerts.openEpisodes

    private fun sendHealth(e: HealthMonitor.Event) {
        val ep = e.episode
        if (ep.device == "headband" && alerts.charging) {
            if (e is HealthMonitor.Event.Warning) heldBack += ep.code
            return
        }
        if (ep.code in heldBack) {
            if (e is HealthMonitor.Event.Fixed) heldBack -= ep.code
            return
        }
        send(e)
    }

    private fun send(e: HealthMonitor.Event) {
        actions.sensor(e, demo)
        val ep = e.episode
        actions.watch(when (e) {
            is HealthMonitor.Event.Fixed -> PhoneMessage.SensorFixed(ep.code)
            else -> PhoneMessage.SensorWarning(ep.code, ep.impact, ep.detail, WarningPolicy.urgent(ep.code, ep.impact))
        })
    }

    fun tick(nowMs: Long) { dispatch(flow.tick(nowMs)); status = status.copy(flowState = flow.state) }

    fun onPin(r: PinResult, nowMs: Long) { dispatch(flow.onPin(r, nowMs)); status = status.copy(flowState = flow.state) }

    fun resolveByCaregiver(nowMs: Long, wasSeizure: Boolean?) {
        dispatch(flow.resolveByCaregiver(nowMs, wasSeizure)); status = status.copy(flowState = flow.state)
    }

    private fun dispatch(effects: List<FlowEffect>) {
        for (e in effects) {
            if (e is FlowEffect.Watch) actions.watch(e.message)
            actions.flow(e, demo)
        }
    }
}

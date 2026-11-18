package org.epiprot.phone.engine

import org.epiprot.phone.alarm.AlarmFlow
import org.epiprot.phone.alarm.FlowEffect
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.model.Detector
import org.epiprot.phone.model.DetectorConfig
import org.epiprot.phone.model.Gbdt
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
    val quality: Map<String, HealthMonitor.Quality> = emptyMap(),
    val heartRate: Double = Double.NaN,
    val flowState: AlarmFlow.State = AlarmFlow.State.Idle,
    val openWarnings: List<HealthMonitor.Episode> = emptyList(),
    val demo: Boolean = false,
)

/**
 * The phone's monitoring chain for every 5 s window:
 * window features -> sensor health (warnings to the watch) -> detector -> alarm flow.
 */
class MonitoringEngine(
    private val cfg: DetectorConfig,
    private val modelA: Gbdt,
    private val modelFb: Gbdt,
    private val modelB: Gbdt?,
    private val actions: EngineActions,
) {
    private var detector = Detector(cfg, modelA, modelFb, modelB)
    private var health = HealthMonitor()
    val flow = AlarmFlow()
    var demo = false
        private set
    var status = EngineStatus()
        private set

    /** Fresh detector / health state, e.g. for a demo replay or after a long interruption. */
    fun reset(demo: Boolean) {
        detector = Detector(cfg, modelA, modelFb, modelB)
        health = HealthMonitor()
        this.demo = demo
        status = EngineStatus(demo = demo)
    }

    fun onWindow(w: WindowInput, endMs: Long): WindowResult {
        val f = WindowFeatures.compute(w)
        val q = HealthMonitor.quality(f)
        for (e in health.next(q, endMs, flow.busy)) {
            actions.sensor(e, demo)
            actions.watch(when (e) {
                is HealthMonitor.Event.Warning -> PhoneMessage.SensorWarning(e.episode.code, e.episode.impact)
                is HealthMonitor.Event.Reminder -> PhoneMessage.SensorWarning(e.episode.code, e.episode.impact)
                is HealthMonitor.Event.Fixed -> PhoneMessage.SensorFixed(e.episode.code)
            })
        }
        val r = detector.next(f, w)
        if (r.alarm) {
            val onsetMs = endMs - (r.index - r.onsetIndex!! + 1) * WindowAssembler.WINDOW_MS
            val id = actions.newDeviceEvent(endMs, onsetMs, demo)
            dispatch(flow.onAlarm(id, endMs, onsetMs))
        }
        r.seizureEndedIndex?.let { e ->
            dispatch(flow.onSeizureEnded(endMs - (r.index - e) * WindowAssembler.WINDOW_MS, endMs))
        }
        dispatch(flow.tick(endMs))
        status = status.copy(windows = r.index + 1, lastScore = r.score, fallback = r.fallback, quality = q,
            heartRate = f["ecg_hr"] ?: Double.NaN, flowState = flow.state, openWarnings = health.openEpisodes)
        return r
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

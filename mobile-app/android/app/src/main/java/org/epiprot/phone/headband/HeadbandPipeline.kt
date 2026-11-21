package org.epiprot.phone.headband

import org.epiprot.phone.engine.WindowAssembler
import org.epiprot.phone.model.WindowInput
import org.epiprot.phone.protocol.SensorBatch

/**
 * Live 5 s windows from the headband and the watch, plus late headband data after a gap.
 *
 * Live samples go into the window assembler as before; finished windows go to [onWindow] (detection).
 * Stored data the headband sends after a Bluetooth gap ("catch-up") arrive too late for detection, but
 * not too late for the model's memory: they are collected into the same 5 s grid and, once the catch-up
 * has finished, each past window is rebuilt (headband part from the catch-up, watch part from the live
 * window) and handed to [onLateWindow], which lets the detector replace the stand-in values it used
 * while the data were missing (Detector.backfill). Found with the real Bluetooth test: a 1.5 min gap
 * 5 min before a seizure delayed the alarm from 15 s to 88 s.
 */
class HeadbandPipeline(
    private val startMs: Long,
    private val onWindow: (WindowInput, Long) -> Unit,
    private val onLateWindow: (WindowInput, Long) -> Unit,
) : HeadbandSink {
    private val live = WindowAssembler(startMs)
    private val recent = LinkedHashMap<Long, WindowInput>()      // window end -> live window
    private var late: WindowAssembler? = null
    private var lateLastMs = 0.0
    private var lateTouched = false
    var lateWindows = 0
        private set

    override fun eeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) = live.addHeadbandEeg(firstMs, uv, leadOff)
    override fun movement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) = live.addHeadMovement(tMs, accG, gyrDps)

    override fun lateEeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) {
        live.addHeadbandEeg(firstMs, uv, leadOff)                 // windows still open take them directly
        lateAssembler(firstMs).addHeadbandEeg(firstMs, uv, leadOff)
        lateLastMs = maxOf(lateLastMs, firstMs + uv[0].size * 1000.0 / 256)
        lateTouched = true
    }

    override fun lateMovement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) {
        live.addHeadMovement(tMs, accG, gyrDps)
        lateAssembler(tMs).addHeadMovement(tMs, accG, gyrDps)
        lateLastMs = maxOf(lateLastMs, tMs)
        lateTouched = true
    }

    fun addWatch(b: SensorBatch) = live.addWatch(b)

    /** Call about once a second with the phone clock. */
    fun tick(nowMs: Long) {
        for ((w, end) in live.closeReady(nowMs)) {
            recent[end] = w
            if (recent.size > KEEP) recent.remove(recent.keys.first())
            onWindow(w, end)
        }
        if (late != null && !lateTouched) flushLate()            // catch-up finished (nothing new since last tick)
        lateTouched = false
    }

    private fun lateAssembler(tMs: Double): WindowAssembler = late ?: run {
        val k = Math.floorDiv(tMs.toLong() - startMs, WindowAssembler.WINDOW_MS)
        WindowAssembler(startMs + k * WindowAssembler.WINDOW_MS).also { late = it }
    }

    private fun flushLate() {
        val a = late ?: return
        late = null
        for ((w, end) in a.closeReady(lateLastMs.toLong() + WindowAssembler.WINDOW_MS + 2_000)) {
            val l = recent[end] ?: continue                       // not closed live yet: the live window got the data
            if (w.eegUv == null && w.mov.isEmpty()) continue
            val merged = merge(l, w)
            recent[end] = merged
            lateWindows++
            onLateWindow(merged, end)
        }
    }

    /** Live window + late headband data: live samples win, late ones fill what is missing. */
    private fun merge(live: WindowInput, late: WindowInput): WindowInput {
        val eeg = when {
            live.eegUv == null -> late.eegUv
            late.eegUv == null || live.channels != late.channels -> live.eegUv
            else -> Array(live.eegUv.size) { c ->
                FloatArray(live.eegUv[c].size) { i -> live.eegUv[c][i].takeIf { it.isFinite() } ?: late.eegUv[c][i] }
            }
        }
        val mov = HashMap(live.mov)
        for ((k, v) in late.mov) {
            val cur = mov[k]
            mov[k] = if (cur == null) v else Array(3) { a -> FloatArray(cur[a].size) { i -> cur[a][i].takeIf { it.isFinite() } ?: v[a][i] } }
        }
        val useLate = live.eegUv == null
        return WindowInput(eeg, mov, live.heartRate,
            contactBad = if (useLate) late.contactBad else live.contactBad,
            channels = if (useLate) late.channels else live.channels,
            leadOff = live.leadOff or late.leadOff)
    }

    companion object { const val KEEP = 150 }     // 12.5 min of live windows
}

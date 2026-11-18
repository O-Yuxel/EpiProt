package org.epiprot.phone.engine

import org.epiprot.phone.model.WindowFeatures
import org.epiprot.phone.model.WindowInput
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * A real tonic-clonic seizure from SeizeIT2 (assets/demo/demo_seizure.bin, made by
 * tools/make_demo_asset.py), replayed as if it came from the headband and the watch.
 */
class DemoRecording(val windows: List<WindowInput>, val onsetS: Double, val durationS: Double, val label: String) {
    companion object {
        fun parse(bytes: ByteArray): DemoRecording {
            val b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val hl = b.int
            val h = JSONObject(String(bytes, 4, hl, Charsets.UTF_8))
            b.position(4 + hl)
            val n = h.getInt("windows")
            val hr = h.getJSONArray("heart_rate")
            val keys = WindowFeatures.MOV_KEYS
            val ws = List(n) { i ->
                val eeg = Array(2) { FloatArray(WindowFeatures.EEG_N) { b.float } }
                val mov = keys.associateWith { Array(3) { FloatArray(WindowFeatures.MOV_N) { b.float } } }
                val v = if (hr.isNull(i)) Float.NaN else hr.getDouble(i).toFloat()
                WindowInput(eeg, mov, if (v.isNaN()) FloatArray(0) else floatArrayOf(v, v))
            }
            return DemoRecording(ws, h.getDouble("onset_s"), h.getDouble("duration_s"),
                "${h.getString("sub")} ${h.getString("type")}")
        }
    }
}

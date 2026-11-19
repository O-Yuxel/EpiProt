package org.epiprot.phone

import org.epiprot.phone.engine.DemoRecording
import org.epiprot.phone.model.Detector
import org.epiprot.phone.model.WindowFeatures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The phone's stuck-heart-rate rule gives the same windows as stuck_mask() in Python (hr_robustness.py). */
class HrStuckTest {
    @Test
    fun stuckHeartRateSwitchesToTheBackupModelsLikePython() = with(Fixtures) {
        val hb = config.hrBackup!!
        assertTrue("export with --stuck-hr", hb.stuckBpm > 0)
        val nan = Double.NaN
        val hr = doubleArrayOf(70.0, 71.0, 70.0, 72.0) + DoubleArray(12) { 80.0 } + DoubleArray(3) { 80.4 } + doubleArrayOf(nan) + DoubleArray(12) { 90.0 }
        // stuck_mask(hr, 1.0) in Python: windows 15-18 and 31
        val expected = BooleanArray(hr.size) { it in 15..18 || it == 31 }
        val w = DemoRecording.parse(File("src/main/assets/demo/demo_seizure.bin").readBytes()).windows[0]
        val base = WindowFeatures.compute(w)
        val d = Detector(config, models)
        hr.forEachIndexed { i, v ->
            val r = d.next(base + (hb.whenMissing to v), w)
            assertEquals("window $i", expected[i] || v.isNaN(), r.noHeartRate)
        }
    }
}

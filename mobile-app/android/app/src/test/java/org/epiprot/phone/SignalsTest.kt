package org.epiprot.phone

import org.epiprot.phone.model.WindowFeatures
import org.epiprot.phone.model.WindowInput
import org.epiprot.phone.privacy.Ack
import org.epiprot.phone.privacy.Consent
import org.epiprot.phone.privacy.ConsentState
import org.epiprot.phone.signals.SignalRecorder
import org.epiprot.phone.signals.SignalSnippet
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SignalsTest {
    private fun window(i: Int, eeg: Boolean = true) = WindowInput(
        if (eeg) Array(2) { ch -> FloatArray(WindowFeatures.EEG_N) { (i * 1000 + ch).toFloat() } } else null,
        mapOf("head_acc" to Array(3) { FloatArray(WindowFeatures.MOV_N) { if (it == 0) 3f else 4f } }.let {
            arrayOf(FloatArray(WindowFeatures.MOV_N) { 3f }, FloatArray(WindowFeatures.MOV_N) { 4f }, FloatArray(WindowFeatures.MOV_N) { 0f }) }),
        floatArrayOf(70f + i, 70f + i, 70f + i))

    @Test
    fun recordsTwoMinutesBeforeAndFiveAfterTheAlarm() {
        val saved = ArrayList<SignalSnippet>()
        val rec = SignalRecorder({ true }) { saved += it }
        for (i in 0 until 40) rec.add(window(i), (i + 1) * 5_000L)       // 40 windows before the alarm
        rec.onAlarm(7, 200_000, 180_000)
        for (i in 40 until 120) rec.add(window(i), (i + 1) * 5_000L)
        assertEquals(1, saved.size)
        val s = saved[0]
        assertEquals(SignalSnippet.PRE_WINDOWS + SignalSnippet.POST_WINDOWS, s.heartRate.size)
        assertEquals(200_000L - SignalSnippet.PRE_WINDOWS * 5_000L, s.startMs)      // 2 min before the alarm
        assertEquals(16 * 1000f, s.eeg[0][0])                                       // window 16 = 40 - 24
        assertEquals(5f, s.movement[0], 1e-5f)                                      // |(3, 4, 0)|
        assertEquals(86f, s.heartRate[0], 1e-5f)
    }

    @Test
    fun nothingIsKeptWithoutConsentAndGapsAreNaN() {
        val saved = ArrayList<SignalSnippet>()
        var allowed = false
        val rec = SignalRecorder({ allowed }) { saved += it }
        for (i in 0 until 30) rec.add(window(i), (i + 1) * 5_000L)
        rec.onAlarm(1, 150_000, 140_000); rec.flush()
        assertTrue(saved.isEmpty())
        allowed = true
        rec.add(window(0, eeg = false), 5_000); rec.onAlarm(2, 5_000, 0); rec.flush()
        assertTrue(saved.single().eeg[0].all { it.isNaN() })
    }

    @Test
    fun snippetSurvivesEncoding() {
        val s = SignalRecorder.build(3, 50_000, 45_000, List(5) { window(it) }, 25_000)
        val back = SignalSnippet.decode(SignalSnippet.encode(s))
        assertEquals(s.eventId, back.eventId); assertEquals(s.startMs, back.startMs); assertEquals(s.onsetMs, back.onsetMs)
        assertTrue(s.eeg[1].contentEquals(back.eeg[1])); assertTrue(s.movement.contentEquals(back.movement))
        assertTrue(s.heartRate.contentEquals(back.heartRate))
    }

    @Test
    fun signalsNeedBothConsents() {
        fun st(vararg g: Consent) = ConsentState(doneVersion = ConsentState.TEXT_VERSION, acks = setOf(Ack.NOTICE, Ack.LIMITS), granted = g.toSet())
        assertFalse(st(Consent.SIGNALS).signalsAllowed)
        assertFalse(st(Consent.HEALTH_DATA).signalsAllowed)
        assertTrue(st(Consent.HEALTH_DATA, Consent.SIGNALS).signalsAllowed)
    }
}

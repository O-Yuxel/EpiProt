package org.epiprot.watch

import org.epiprot.watch.core.BackupBuffer
import org.epiprot.watch.core.Effect
import org.epiprot.watch.core.Impact
import org.epiprot.watch.core.InfoKind
import org.epiprot.watch.core.PinVerifier
import org.epiprot.watch.core.Screen
import org.epiprot.watch.core.SensorBatcher
import org.epiprot.watch.core.WarningCode
import org.epiprot.watch.core.WatchStateMachine
import org.epiprot.watch.protocol.Paths
import org.epiprot.watch.protocol.PhoneMessage
import org.epiprot.watch.protocol.PinContext
import org.epiprot.watch.protocol.PinResult
import org.epiprot.watch.protocol.Sample
import org.epiprot.watch.protocol.SensorBatch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StateMachineTest {
    private val t0 = 1_000_000L

    @Test
    fun correctPinDuringAlarmSendsFalseAlarmAndStopsVibration() {
        val m = WatchStateMachine()
        val start = m.alarmStart(7, t0)
        assertTrue(Effect.VibrateAlarm in start)
        assertTrue(Effect.WakeScreen in start)
        val fx = m.pinEntered(ok = true, now = t0 + 5_000)
        assertEquals(Effect.SendPin(PinContext.ALARM, 7, ok = true, attempt = 1), fx[0])
        assertTrue(Effect.StopVibration in fx)
        assertEquals(InfoKind.FALSE_ALARM_SENT, (m.screen as Screen.Info).kind)
    }

    @Test
    fun wrongPinKeepsAlarmAndCountsAttempts() {
        val m = WatchStateMachine()
        m.alarmStart(7, t0)
        val fx = m.pinEntered(ok = false, now = t0 + 3_000)
        assertEquals(Effect.SendPin(PinContext.ALARM, 7, ok = false, attempt = 1), fx[0])
        assertEquals(1, (m.screen as Screen.Alarm).wrongAttempts)
        m.pinEntered(ok = true, now = t0 + 6_000)
        assertTrue(m.screen is Screen.Info)
    }

    @Test
    fun pinWindowExpiresAfter30s() {
        val m = WatchStateMachine()
        m.alarmStart(7, t0)
        assertTrue(m.tick(t0 + 29_000).isEmpty())
        val fx = m.tick(t0 + 30_000)
        assertEquals(Screen.AlarmActive(7), m.screen)
        assertTrue(Effect.StopVibration in fx)
        assertTrue("no cancel after the window", m.pinEntered(ok = true, now = t0 + 31_000).isEmpty())
    }

    @Test
    fun checkInAnsweredWithPin() {
        val m = WatchStateMachine()
        m.alarmStart(7, t0)
        m.tick(t0 + 30_000)
        val ask = m.checkIn(7, 1, t0 + 300_000)
        assertTrue(Effect.VibrateCheckIn in ask)
        assertEquals(Screen.CheckIn(7, 1), m.screen)
        assertTrue(Effect.VibrateShort in m.pinEntered(ok = false, now = t0 + 301_000))
        val fx = m.pinEntered(ok = true, now = t0 + 302_000)
        assertEquals(Effect.SendPin(PinContext.CHECKIN, 7, ok = true, attempt = 2), fx[0])
        assertEquals(InfoKind.RECOVERY_OK, (m.screen as Screen.Info).kind)
    }

    @Test
    fun sensorWarningWaitsUntilAlarmIsOver() {
        val m = WatchStateMachine()
        m.alarmStart(7, t0)
        assertTrue(m.sensorWarning(WarningCode.HEART_MISSING, Impact.WEAKER, t0 + 1_000).isEmpty())
        assertTrue(m.screen is Screen.Alarm)
        m.alarmEnd(7, t0 + 60_000)
        assertEquals(InfoKind.ALARM_ENDED, (m.screen as Screen.Info).kind)
        val fx = m.tick(t0 + 70_000)        // info times out -> pending warning shown
        assertEquals(Screen.Warning(WarningCode.HEART_MISSING, Impact.WEAKER), m.screen)
        assertTrue(Effect.VibrateWarning in fx)
    }

    @Test
    fun dismissedWarningStaysOpenAndReminderShowsItAgain() {
        val m = WatchStateMachine()
        m.sensorWarning(WarningCode.BRAIN_WEAK, Impact.LIMITED, t0)
        m.dismiss(t0 + 1_000)
        assertEquals(Screen.Home, m.screen)
        assertTrue(WarningCode.BRAIN_WEAK in m.activeWarnings)
        m.sensorWarning(WarningCode.BRAIN_WEAK, Impact.LIMITED, t0 + 900_000)   // reminder
        assertEquals(Screen.Warning(WarningCode.BRAIN_WEAK, Impact.LIMITED), m.screen)
    }

    @Test
    fun fixedWarningShowsInfoAndIsRemoved() {
        val m = WatchStateMachine()
        m.sensorWarning(WarningCode.BRAIN_WEAK, Impact.LIMITED, t0)
        m.sensorFixed(WarningCode.BRAIN_WEAK, t0 + 5_000)
        assertEquals(InfoKind.SENSOR_FIXED, (m.screen as Screen.Info).kind)
        assertTrue(m.activeWarnings.isEmpty())
        m.tick(t0 + 10_000)
        assertEquals(Screen.Home, m.screen)
    }

    @Test
    fun alarmEndForAnotherAlarmIsIgnored() {
        val m = WatchStateMachine()
        m.alarmStart(8, t0)
        assertTrue(m.alarmEnd(7, t0 + 1_000).isEmpty())
        assertTrue(m.screen is Screen.Alarm)
    }
}

class PinVerifierTest {
    @Test
    fun demoPinIs1234() {
        val p = PinVerifier.demo()
        assertTrue(p.isDemo)
        assertTrue(p.verify("1234"))
        assertFalse(p.verify("1235"))
        assertFalse(p.verify("123"))
        assertFalse(p.verify("12a4"))
    }

    @Test
    fun pinFromPhoneSettings() {
        val salt = "s3cret-salt"
        val p = PinVerifier(salt, PinVerifier.hashPin("0815", salt))
        assertFalse(p.isDemo)
        assertTrue(p.verify("0815"))
        assertFalse(p.verify("1234"))
    }
}

class ProtocolTest {
    @Test
    fun sensorBatchRoundTrip() {
        val b = SensorBatch(
            seq = 42, startMs = 1_731_900_000_000L, heartRate = 72.5f, onBody = true,
            acc = listOf(Sample(0, 0.1f, 0.2f, 9.8f), Sample(40, 0.3f, -0.2f, 9.7f)),
            gyr = listOf(Sample(20, 0.01f, 0.02f, 0.03f)),
        )
        assertEquals(b, SensorBatch.decode(b.encode()))
    }

    @Test
    fun missingHeartRateStaysNaN() {
        val b = SensorBatch(1, 0L, Float.NaN, null, emptyList(), emptyList())
        val d = SensorBatch.decode(b.encode())
        assertTrue(d.heartRate.isNaN())
        assertNull(d.onBody)
    }

    @Test
    fun phoneMessagesRoundTrip() {
        val msgs = listOf(
            PhoneMessage.AlarmStart(5, 30), PhoneMessage.AlarmEnd(5, "patient answered"),
            PhoneMessage.CheckIn(5, 2), PhoneMessage.SensorWarning("brain_weak", "limited"),
            PhoneMessage.SensorFixed("brain_weak"), PhoneMessage.Settings("salt", "hash", 30),
        )
        for (m in msgs) {
            val (path, bytes) = PhoneMessage.encode(m)
            assertEquals(m, PhoneMessage.decode(path, bytes))
        }
    }

    @Test
    fun brokenMessagesAreIgnored() {
        assertNull(PhoneMessage.decode(Paths.ALARM_START, "not json".toByteArray()))
        assertNull(PhoneMessage.decode(Paths.ALARM_START, "{}".toByteArray()))
        assertNull(PhoneMessage.decode("/epiprot/unknown", "{}".toByteArray()))
    }

    @Test
    fun pinResultRoundTrip() {
        val r = PinResult(PinContext.CHECKIN, 9, ok = true, attempt = 2, timeMs = 123L)
        assertEquals(r, PinResult.decode(r.encode()))
    }
}

class BuffersTest {
    @Test
    fun backupBufferDropsOldest() {
        val b = BackupBuffer<Int>(3)
        (1..5).forEach(b::add)
        assertEquals(3, b.size)
        assertEquals(3, b.removeFirst())
        assertEquals(4, b.peek())
    }

    @Test
    fun batcherBuildsOneSecondBatches() {
        val s = SensorBatcher(heartRateMaxAgeMs = 5_000)
        s.addHeartRate(1_000, 80f, reliable = true)
        s.addAcc(1_040, 1f, 2f, 3f)
        s.addAcc(1_000, 0f, 0f, 9.8f)
        s.addGyr(1_020, 0f, 0f, 1f)
        val b = s.flush(nowMs = 2_000, onBody = true)
        assertEquals(0, b.seq)
        assertEquals(1_000L, b.startMs)
        assertEquals(listOf(0, 40), b.acc.map { it.offsetMs })
        assertEquals(80f, b.heartRate)
        val next = s.flush(nowMs = 7_000, onBody = true)
        assertEquals(1, next.seq)
        assertTrue(next.acc.isEmpty())
        assertTrue("heart rate older than 5 s is not reported", next.heartRate.isNaN())
    }

    @Test
    fun unreliableHeartRateIgnored() {
        val s = SensorBatcher()
        s.addHeartRate(1_000, 75f, reliable = false)
        assertTrue(s.currentHeartRate(1_500).isNaN())
    }

    @Test
    fun steadyHeartRateStaysValidButLostContactClearsIt() {
        val s = SensorBatcher()                      // default: on-change sensor, 30 s
        s.addHeartRate(1_000, 72f, reliable = true)
        assertEquals(72f, s.currentHeartRate(20_000))
        assertTrue(s.currentHeartRate(32_000).isNaN())
        s.addHeartRate(40_000, 70f, reliable = true)
        s.addHeartRate(41_000, 0f, reliable = false)  // watch taken off
        assertTrue(s.currentHeartRate(41_500).isNaN())
    }
}

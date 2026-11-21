package org.epiprot.phone

import kotlinx.coroutines.runBlocking
import org.epiprot.phone.headband.FirmwareUpdate
import org.epiprot.phone.headband.FirmwareUpdate.Blocker
import org.epiprot.phone.headband.HeadbandAlerts
import org.epiprot.phone.headband.HeadbandState
import org.epiprot.phone.headband.SimulatedTransport
import org.epiprot.phone.headband.WarningPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FirmwareUpdateTest {
    @Test
    fun versionsAreComparedNumerically() {
        assertTrue(FirmwareUpdate.isNewer("1.1.0", "1.0.0"))
        assertTrue(FirmwareUpdate.isNewer("1.2.10", "1.2.9"))
        assertTrue(FirmwareUpdate.isNewer("2.0", "1.9.9"))
        assertFalse(FirmwareUpdate.isNewer("1.0.0", "1.0.0"))
        assertFalse(FirmwareUpdate.isNewer("1.0.0", "1.1.0"))
        assertFalse(FirmwareUpdate.isNewer("1.1.0", null))                 // band not connected yet: nothing offered
    }

    @Test
    fun onlyOnTheChargerWithEnoughBattery() {
        assertEquals(listOf(Blocker.NOT_CONNECTED, Blocker.NOT_CHARGING, Blocker.BATTERY_LOW), FirmwareUpdate.blockers(false, null))
        assertEquals(listOf(Blocker.NOT_CHARGING), FirmwareUpdate.blockers(true, HeadbandState(batteryPct = 80)))
        assertEquals(listOf(Blocker.BATTERY_LOW), FirmwareUpdate.blockers(true, HeadbandState(batteryPct = 29, chargerAttached = true)))
        assertTrue(FirmwareUpdate.blockers(true, HeadbandState(batteryPct = 30, chargerAttached = true)).isEmpty())
    }

    @Test
    fun simulatedInstallGoesThroughEveryStep() = runBlocking {
        val steps = mutableListOf<FirmwareUpdate.Step>()
        val ok = SimulatedTransport(312_000, sleep = {}).install { if (steps.lastOrNull() != it.step) steps += it.step }
        assertTrue(ok)
        assertEquals(listOf(FirmwareUpdate.Step.UPLOADING, FirmwareUpdate.Step.VERIFYING, FirmwareUpdate.Step.RESTARTING), steps)
    }

    @Test
    fun updatingWarningIsQuietAndClears() {
        val a = HeadbandAlerts()
        val w = a.updating(true, 0).single().episode
        assertEquals("headband_updating", w.code)
        assertEquals("no_alarms", w.impact)
        assertFalse(WarningPolicy.urgent(w.code, w.impact))                   // on the charger, chosen by the patient
        assertTrue(a.updating(true, 1).isEmpty())
        assertTrue(a.updating(false, 2).single() is org.epiprot.phone.health.HealthMonitor.Event.Fixed)
    }

    @Test
    fun theBundledManifestIsReadable() {
        val m = FirmwareUpdate.Manifest.parse(java.io.File("src/main/assets/firmware/manifest.json").readText())
        assertEquals("1.1.0", m.version)
        assertTrue(m.simulated)
        assertTrue(m.notesTr.isNotBlank() && m.notesEn.isNotBlank())
    }
}

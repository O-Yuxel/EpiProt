package org.epiprot.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.epiprot.phone.caregiver.CaregiverSms
import org.junit.Test

class CaregiverSmsTest {
    @Test
    fun readsEveryKindAndTheLocation() {
        val alert = "EpiProt: olası NÖBET – Ayşe, 03:12. Konum: https://maps.google.com/?q=41.01234,28.97654 (±12 m). Lütfen hemen git.\n[EP:A]"
        assertEquals(CaregiverSms.Kind.SEIZURE, CaregiverSms.kind(alert))
        assertEquals("https://maps.google.com/?q=41.01234,28.97654", CaregiverSms.mapsLink(alert))
        assertFalse(CaregiverSms.readable(alert).contains("[EP:"))
        assertEquals(CaregiverSms.Kind.FALSE_ALARM, CaregiverSms.kind("EpiProt: YANLIŞ ALARM.\n[EP:F]"))
        assertEquals(CaregiverSms.Kind.EMERGENCY, CaregiverSms.kind("x [EP:E]"))
        assertTrue(CaregiverSms.Kind.EMERGENCY.rings)
        assertFalse(CaregiverSms.Kind.FALSE_ALARM.rings)
        assertNull(CaregiverSms.kind("Merhaba, akşam yemeğe geliyor musun?"))
        assertNull(CaregiverSms.mapsLink("Konum: paylaşılmıyor [EP:A]"))
        assertTrue(CaregiverSms.isDemo("[DEMO] EpiProt: ... [EP:A]"))
        assertEquals(CaregiverSms.Kind.SOS, CaregiverSms.kind("EpiProt: Ayşe YARDIM İSTİYOR\n[EP:S]"))
        assertTrue(CaregiverSms.Kind.SOS.rings)
    }

    @Test
    fun sameNumberInEveryWritingStyle() {
        assertTrue(CaregiverSms.sameNumber("+90 532 123 45 67", "05321234567"))
        assertTrue(CaregiverSms.sameNumber("905321234567", "0532 123 4567"))
        assertFalse(CaregiverSms.sameNumber("05321234567", "05321234568"))
        assertFalse(CaregiverSms.sameNumber("112", "112"))                  // short numbers never match
    }
}

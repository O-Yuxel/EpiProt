package org.epiprot.phone

import org.epiprot.phone.privacy.Ack
import org.epiprot.phone.privacy.Consent
import org.epiprot.phone.privacy.ConsentState
import org.epiprot.phone.privacy.LegalTexts
import org.epiprot.phone.privacy.Region
import org.epiprot.phone.privacy.Role
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** What the app may do for every combination of answers. */
class ConsentTest {
    private val numbers = listOf("+90 555 111 22 33", "0555 444 55 66")
    private fun st(vararg g: Consent, acks: Set<Ack> = setOf(Ack.NOTICE, Ack.LIMITS), ok: Set<String> = emptySet(), done: Int = ConsentState.TEXT_VERSION) =
        ConsentState(doneVersion = done, region = Region.TR, role = Role.SELF, consenter = "A", acks = acks,
            decided = Consent.entries.toSet(), granted = g.toSet(), confirmedCaregivers = ok)

    @Test
    fun firstStartAndChangedTextsNeedTheSetup() {
        assertTrue(ConsentState().setupNeeded)
        assertTrue(st(done = ConsentState.TEXT_VERSION - 1).setupNeeded)
        assertFalse(st().setupNeeded)
    }

    @Test
    fun monitoringNeedsNoticeLimitsAndHealthConsent() {
        assertTrue(st(Consent.HEALTH_DATA).canMonitor)
        assertFalse(st().canMonitor)                                              // declined
        assertFalse(st(Consent.HEALTH_DATA, acks = setOf(Ack.NOTICE)).canMonitor)   // limits not confirmed
        assertFalse(st(Consent.HEALTH_DATA, acks = setOf(Ack.LIMITS)).canMonitor)   // notice not shown
        assertTrue("optional consents never block monitoring", st(Consent.HEALTH_DATA).let { it.canMonitor && !it.smsAllowed })
    }

    @Test
    fun smsOnlyWithConsentAndOnlyToCaregiversWhoAgreed() {
        val ok = setOf(ConsentState.normalize(numbers[0]))
        assertEquals(emptyList<String>(), st(Consent.HEALTH_DATA, ok = ok).recipients(numbers))           // no SMS consent
        assertEquals(listOf(numbers[0]), st(Consent.HEALTH_DATA, Consent.CAREGIVER_SMS, ok = ok).recipients(numbers))
        assertEquals(emptyList<String>(), st(Consent.CAREGIVER_SMS).recipients(numbers))                  // nobody agreed
    }

    @Test
    fun locationOnlyWithBothConsents() {
        assertFalse(st(Consent.LOCATION).locationAllowed)                      // location without SMS is meaningless
        assertFalse(st(Consent.CAREGIVER_SMS).locationAllowed)
        assertTrue(st(Consent.CAREGIVER_SMS, Consent.LOCATION).locationAllowed)
    }

    @Test
    fun caregiverNumbersMatchWhateverTheFormatting() {
        val s = st(Consent.CAREGIVER_SMS, ok = setOf(ConsentState.normalize("05554445566")))
        assertTrue(s.caregiverConfirmed("0555 444 55 66"))
        assertFalse(s.caregiverConfirmed("0555 444 55 67"))
    }

    @Test
    fun onlyHealthDataIsRequired() {
        assertEquals(listOf(Consent.HEALTH_DATA), Consent.entries.filter { it.required })
        assertTrue(Role.PARENT.forSomeoneElse && Role.GUARDIAN.forSomeoneElse && !Role.SELF.forSomeoneElse)
    }

    @Test
    fun regionIsGuessedFromTheCountry() {
        assertEquals(Region.TR, Region.guess("TR"))
        assertEquals(Region.US, Region.guess("us"))
        assertEquals(Region.EU, Region.guess("de"))
        assertEquals(Region.EU, Region.guess("gb"))
        assertEquals(Region.OTHER, Region.guess("jp"))
        assertEquals(Region.OTHER, Region.guess(""))
        assertEquals("911", Region.US.emergency)
        assertEquals(null, Region.OTHER.emergency)
    }

    @Test
    fun textFileFollowsRegionAndLanguageWithFallbacks() {
        val files = java.io.File("src/main/assets/legal").list()!!.toSet()
        assertEquals("texts_us_en.json", LegalTexts.fileFor(Region.US, "en") { it in files })
        assertEquals("texts_us_tr.json", LegalTexts.fileFor(Region.US, "tr") { it in files })
        assertEquals("texts_us_en.json", LegalTexts.fileFor(Region.US, "de") { it in files })
        assertEquals("texts_eu_tr.json", LegalTexts.fileFor(Region.EU, "tr") { it in files })
        assertEquals("texts_eu_en.json", LegalTexts.fileFor(Region.OTHER, "ja") { it in files })
        assertEquals("texts_tr_tr.json", LegalTexts.fileFor(Region.TR, "tr") { it in files })
        assertEquals("texts_tr_en.json", LegalTexts.fileFor(null, "en") { it in files })
    }

    @Test
    fun everyTextFileHasEveryFieldTheAppReads() {
        java.io.File("src/main/assets/legal").listFiles()!!.forEach { f ->
            val t = LegalTexts(org.json.JSONObject(f.readText()))
            assertTrue(f.name, t.welcome.isNotEmpty() && t.noticeFull.isNotEmpty() && t.limits.isNotEmpty())
            Consent.entries.forEach { c -> assertTrue("${f.name} ${c.key}", t.consent(c).yes.isNotEmpty() && t.consent(c).no.isNotEmpty()) }
            Role.entries.forEach { r -> t.role(r) }
            listOf("notifications", "bluetooth", "sms", "location").forEach { t.permission(it) }
            if (f.name.startsWith("texts_us")) assertTrue("COPPA text", t.coppa.isNotEmpty())
            if (!f.name.startsWith("texts_tr")) assertFalse("${f.name} mentions KVKK", f.readText().contains("KVKK"))
        }
    }

    @Test
    fun usChildUnder13NeedsTheParentsSignedConsent() {
        val base = st(Consent.HEALTH_DATA).copy(region = Region.US, childUnder13 = true, role = Role.PARENT)
        assertFalse(base.canMonitor)
        assertTrue(base.copy(acks = base.acks + org.epiprot.phone.privacy.Ack.PARENTAL).canMonitor)
        assertTrue(base.copy(region = Region.EU).canMonitor)          // COPPA is US law
    }

    @Test
    fun parentIsRemindedWhenTheChildBecomesAnAdult() {
        val s = st(Consent.HEALTH_DATA).copy(role = Role.PARENT, birthYear = 2010)
        assertFalse(s.patientNowAdult(2027))
        assertTrue(s.patientNowAdult(2028))
        assertFalse(s.copy(role = Role.SELF).patientNowAdult(2040))
    }

    @Test
    fun everyTextFileHasAChildPage() {
        java.io.File("src/main/assets/legal").listFiles()!!.forEach { f ->
            assertTrue(f.name, LegalTexts(org.json.JSONObject(f.readText())).childSummary.size >= 4)
        }
    }
}

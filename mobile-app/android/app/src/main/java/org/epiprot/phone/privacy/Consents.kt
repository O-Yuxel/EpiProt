package org.epiprot.phone.privacy

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Consent model of EpiProt (KVKK m.5/6/10/11, GDPR art. 6/7/8/9; Google Play "prominent disclosure").
 *
 * Principles:
 *  - The privacy notice (aydınlatma metni) is INFORMATION, shown before anything is processed and separately from the
 *    consents; reading it is not consent and is never bundled with a consent (KVKK Board principle decision 2026/347).
 *  - Every consent is separate, specific and freely given: its own screen, "I agree" and "I don't agree" buttons with the
 *    same weight, the consequences of both answers shown, nothing pre-selected; going back / leaving is not consent.
 *  - Optional consents never block the app; only HEALTH_DATA is needed for monitoring (nothing can be detected without
 *    processing the sensor data).
 *  - Every decision is recorded with time, text version and who decided; it can be changed at any time.
 *  - Under 18: the parent / legal representative decides; the patient can ask to withdraw at any time.
 */
enum class Consent(val key: String, val required: Boolean) {
    /** Processing the brain signal, heart rate and movement on the phone to detect seizures; keeping the event log. */
    HEALTH_DATA("health_data", true),
    /** Sending health information (a possible seizure, its follow-up) to the caregivers by SMS. */
    CAREGIVER_SMS("caregiver_sms", false),
    /** Adding the phone's location to the alarm SMS. Only meaningful together with CAREGIVER_SMS. */
    LOCATION("location", false),
    /** Keeping the signals of 2 min before to 5 min after each alarm (encrypted, max 12 months) for the doctor report. */
    SIGNALS("signals", false),
    /** Anonymised data for research / improving the model. Nothing is sent today; default off. */
    RESEARCH("research", false),
}

/**
 * Where the patient lives: decides which legal texts are shown (and the emergency number).
 *  TR  : KVKK (Turkey)
 *  EU  : GDPR (EU / EEA; also used for the UK and Switzerland, which have GDPR-like laws)
 *  US  : FTC Act + Health Breach Notification Rule, state consumer-health laws (Washington MHMDA, Nevada, Connecticut),
 *        state privacy laws for sensitive data, COPPA for children under 13
 *  OTHER: the GDPR texts (the strictest common baseline), local emergency number
 */
enum class Region(val key: String, val emergency: String?) {
    TR("tr", "112"), EU("eu", "112"), US("us", "911"), OTHER("other", null);

    companion object {
        fun of(key: String?) = entries.firstOrNull { it.key == key }

        private val EU_LIKE = setOf(
            "at", "be", "bg", "hr", "cy", "cz", "dk", "ee", "fi", "fr", "de", "gr", "hu", "ie", "it", "lv", "lt", "lu",
            "mt", "nl", "pl", "pt", "ro", "sk", "si", "es", "se",      // EU
            "is", "li", "no",                                          // EEA
            "gb", "ch",                                                // GDPR-like
        )

        /** Best guess from the SIM / network / locale country (ISO 3166 alpha-2); the user confirms it. */
        fun guess(country: String?): Region = when (val c = country?.lowercase()?.trim()) {
            null, "" -> OTHER
            "tr" -> TR
            "us", "pr", "gu", "vi", "as", "mp" -> US
            in EU_LIKE -> EU
            else -> OTHER
        }
    }
}

/** Things the user has read / confirmed that are not consents. */
enum class Ack(val key: String) {
    NOTICE("notice"),            // the privacy notice was shown (information, not consent)
    LIMITS("limits"),            // understood that EpiProt is not a medical device and can miss seizures
    PARENTAL("parental"),        // US, patient under 13: the parent's signed consent (COPPA)
}

/** Who makes the decisions. */
enum class Role(val key: String) {
    SELF("self"),                // the patient, 18 or older
    PARENT("parent"),            // parent of a patient under 18
    GUARDIAN("guardian"),        // legal guardian / representative of the patient
    ;
    val forSomeoneElse: Boolean get() = this != SELF

    companion object { fun of(key: String?) = entries.firstOrNull { it.key == key } }
}

data class ConsentRecord(val timeMs: Long, val item: String, val granted: Boolean, val version: Int, val by: String, val role: String)

/** Pure decision logic (unit-tested): what the app may do with the current answers. */
data class ConsentState(
    val doneVersion: Int = 0,                         // text version of the completed setup (0 = never)
    val region: Region? = null,
    val childUnder13: Boolean = false,                // US: patient under 13 -> parental consent (COPPA) needed
    val birthYear: Int? = null,                       // patient's birth year when a parent decides (adult reminder)
    val role: Role? = null,
    val consenter: String = "",
    val acks: Set<Ack> = emptySet(),
    val decided: Set<Consent> = emptySet(),           // answered (yes or no)
    val granted: Set<Consent> = emptySet(),
    val confirmedCaregivers: Set<String> = emptySet(),// numbers whose owner agreed to receive alerts
) {
    /** The first-start setup must be (re)done: never done, or the texts changed since. */
    val setupNeeded: Boolean get() = doneVersion < TEXT_VERSION

    fun has(c: Consent) = c in granted

    /** Monitoring may run: notice shown, limits understood, health data consent given. */
    val canMonitor: Boolean get() = Ack.NOTICE in acks && Ack.LIMITS in acks && has(Consent.HEALTH_DATA) && parentalOk

    /** A parent decided for a child who is now 18 (or turns 18 this year): the patient should decide from now on. */
    fun patientNowAdult(currentYear: Int): Boolean = role == Role.PARENT && birthYear != null && currentYear - birthYear >= 18

    /** COPPA: for a US patient under 13 the parent's consent must be on record. */
    val parentalOk: Boolean get() = !(region == Region.US && childUnder13) || Ack.PARENTAL in acks

    val smsAllowed: Boolean get() = has(Consent.CAREGIVER_SMS)

    /** Signals around alarms are kept only with the health-data consent AND the signals consent. */
    val signalsAllowed: Boolean get() = has(Consent.HEALTH_DATA) && has(Consent.SIGNALS)

    /** The location is added to the SMS only with both consents. */
    val locationAllowed: Boolean get() = smsAllowed && has(Consent.LOCATION)

    /** Caregivers that may be messaged: SMS consent + the caregiver agreed. */
    fun recipients(numbers: List<String>): List<String> =
        if (!smsAllowed) emptyList() else numbers.filter { normalize(it) in confirmedCaregivers }

    fun caregiverConfirmed(number: String) = normalize(number) in confirmedCaregivers

    companion object {
        /** Increase when the notice or a consent text changes: everybody sees the setup again. */
        const val TEXT_VERSION = 3          // 2: country / region choice; 3: signals around alarms

        fun normalize(number: String) = number.filter { it.isDigit() || it == '+' }
    }
}

/** Stores the answers on the phone (SharedPreferences) and keeps the history of every decision. */
class ConsentStore(context: Context) {
    private val p = context.getSharedPreferences("epiprot_consent", Context.MODE_PRIVATE)

    fun state(): ConsentState = ConsentState(
        doneVersion = p.getInt("done_version", 0),
        region = Region.of(p.getString("region", null)),
        childUnder13 = p.getBoolean("child_under13", false),
        birthYear = p.getInt("birth_year", 0).takeIf { it > 0 },
        role = Role.of(p.getString("role", null)),
        consenter = Vault.decrypt(p.getString("consenter", null)),
        acks = Ack.entries.filter { p.getBoolean("ack_${it.key}", false) }.toSet(),
        decided = Consent.entries.filter { p.contains("c_${it.key}") }.toSet(),
        granted = Consent.entries.filter { p.getBoolean("c_${it.key}", false) }.toSet(),
        confirmedCaregivers = p.getStringSet("cg_ok", emptySet())!!.toSet(),
    )

    fun setWho(role: Role, consenter: String, now: Long = System.currentTimeMillis()) {
        p.edit().putString("role", role.key).putString("consenter", Vault.encrypt(consenter.trim())).apply()
        record(ConsentRecord(now, "who:${role.key}", true, ConsentState.TEXT_VERSION, consenter.trim(), role.key))
    }

    fun setRegion(r: Region, now: Long = System.currentTimeMillis()) {
        p.edit().putString("region", r.key).apply()
        record(now, "region:${r.key}", true)
    }

    fun setBirthYear(year: Int?, now: Long = System.currentTimeMillis()) {
        if (year == null) p.edit().remove("birth_year").apply() else p.edit().putInt("birth_year", year).apply()
        if (year != null) record(now, "birth_year", true)
    }

    fun setChildUnder13(v: Boolean, now: Long = System.currentTimeMillis()) {
        p.edit().putBoolean("child_under13", v).apply()
        if (!v) p.edit().remove("ack_${Ack.PARENTAL.key}").apply()
        record(now, "child_under13", v)
    }

    /** COPPA signature: the parent's typed full name is kept with the record. */
    fun parentalConsent(signature: String, now: Long = System.currentTimeMillis()) {
        p.edit().putBoolean("ack_${Ack.PARENTAL.key}", true).putString("parental_signature", Vault.encrypt(signature.trim())).apply()
        record(ConsentRecord(now, "ack:parental", true, ConsentState.TEXT_VERSION, signature.trim(), "parent"))
    }

    fun ack(a: Ack, now: Long = System.currentTimeMillis()) {
        p.edit().putBoolean("ack_${a.key}", true).apply()
        record(now, "ack:${a.key}", true)
    }

    fun set(c: Consent, granted: Boolean, now: Long = System.currentTimeMillis()) {
        p.edit().putBoolean("c_${c.key}", granted).apply()
        record(now, c.key, granted)
    }

    fun setCaregiverConfirmed(number: String, ok: Boolean, now: Long = System.currentTimeMillis()) {
        val n = ConsentState.normalize(number)
        if (n.isEmpty()) return
        val s = p.getStringSet("cg_ok", emptySet())!!.toMutableSet()
        if ((n in s) == ok) return
        if (ok) s += n else s -= n
        p.edit().putStringSet("cg_ok", s).apply()
        record(now, "caregiver_agreed:${mask(n)}", ok)
    }

    /** The patient confirmed and shared a doctor report (each sharing is its own decision). */
    fun reportShared(fromMs: Long, toMs: Long, events: Int, now: Long = System.currentTimeMillis()) =
        record(now, "report_shared:$fromMs-$toMs:$events", true)

    fun finishSetup(now: Long = System.currentTimeMillis()) {
        p.edit().putInt("done_version", ConsentState.TEXT_VERSION).apply()
        record(now, "setup_completed", true)
    }

    /** Starts the setup again, e.g. a new person decides (the patient turned 18, a new guardian). */
    fun restartSetup(now: Long = System.currentTimeMillis()) {
        p.edit().putInt("done_version", 0).apply()
        record(now, "setup_restarted", true)
    }

    fun history(): List<ConsentRecord> {
        val a = JSONArray(Vault.decrypt(p.getString("history", null)).ifEmpty { "[]" })
        return List(a.length()) { i ->
            val o = a.getJSONObject(i)
            ConsentRecord(o.getLong("t"), o.getString("item"), o.getBoolean("granted"), o.getInt("v"), o.optString("by"), o.optString("role"))
        }.sortedByDescending { it.timeMs }
    }

    fun historyJson(): JSONArray = JSONArray(Vault.decrypt(p.getString("history", null)).ifEmpty { "[]" })

    /** Everything, including the history (part of "delete all my data"). */
    fun clearAll() { p.edit().clear().apply() }

    private fun record(now: Long, item: String, granted: Boolean) {
        val st = state()
        record(ConsentRecord(now, item, granted, ConsentState.TEXT_VERSION, st.consenter, st.role?.key ?: ""))
    }

    private fun record(r: ConsentRecord) {
        val a = JSONArray(Vault.decrypt(p.getString("history", null)).ifEmpty { "[]" })
        a.put(JSONObject().put("t", r.timeMs).put("item", r.item).put("granted", r.granted).put("v", r.version)
            .put("by", r.by).put("role", r.role))
        p.edit().putString("history", Vault.encrypt(a.toString())).apply()     // names inside: stored encrypted
    }

    /** History shows only the last 3 digits of a caregiver number. */
    private fun mask(n: String) = if (n.length <= 3) n else "•••" + n.takeLast(3)
}

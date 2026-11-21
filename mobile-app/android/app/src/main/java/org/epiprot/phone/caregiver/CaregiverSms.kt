package org.epiprot.phone.caregiver

/**
 * The machine-readable tag at the end of every EpiProt caregiver SMS (sent by the patient's phone app,
 * mobile-app/android/app/.../comm/Comm.kt CaregiverTag). Plain Kotlin, unit-tested.
 */
object CaregiverSms {
    enum class Kind(val tag: Char, val rings: Boolean) {
        SEIZURE('A', true), FALSE_ALARM('F', false), EMERGENCY('E', true), NO_ANSWER('N', true),
        HANDOVER('H', true), INTRO('I', false), SOS('S', true), SHOWER('W', true), SHOWER_OK('O', false),
        /** Caregiver -> patient's phone: "I am going" (the argument is the caregiver's name). */
        COMING('C', false),
        /** Patient's phone -> the other caregivers: someone is on the way (argument: their name). */
        ON_THE_WAY('K', false)
    }

    private val TAG = Regex("""\[EP:([AFENHISWOCK])(?::([^\]]{0,40}))?]""")
    private val MAPS = Regex("""https://maps\.google\.com/\?q=[-0-9.,]+""")

    /** The kind of an EpiProt SMS, or null when it is not one. */
    fun kind(text: String): Kind? = TAG.findAll(text).lastOrNull()?.let { m -> Kind.entries.first { it.tag == m.groupValues[1][0] } }

    /** The argument of the tag, e.g. the caregiver's name in "[EP:C:Mehmet]" ("" when there is none). */
    fun arg(text: String): String = TAG.findAll(text).lastOrNull()?.groupValues?.get(2)?.trim() ?: ""

    /** The tag for [kind], with an optional argument (no brackets or colons inside it). */
    fun tag(kind: Kind, arg: String = ""): String {
        val a = arg.filterNot { it == ']' || it == '[' || it == ':' }.trim().take(40)
        return if (a.isEmpty()) "[EP:${kind.tag}]" else "[EP:${kind.tag}:$a]"
    }

    /** The location link in the message, if the patient shares the location. */
    fun mapsLink(text: String): String? = MAPS.find(text)?.value

    /** The message without the tag, for showing it. */
    fun readable(text: String): String = TAG.replace(text, "").trim()

    /** True when the demo of the patient's app sent it. */
    fun isDemo(text: String) = text.startsWith("[DEMO]")

    /** Phone numbers are compared by their last 10 digits (0532..., +90532..., 90532... are the same number). */
    fun sameNumber(a: String, b: String): Boolean {
        val da = a.filter { it.isDigit() }.takeLast(10)
        val db = b.filter { it.isDigit() }.takeLast(10)
        return da.length >= 7 && da == db
    }
}

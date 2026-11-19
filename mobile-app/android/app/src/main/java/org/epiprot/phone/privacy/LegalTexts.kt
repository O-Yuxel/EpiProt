package org.epiprot.phone.privacy

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

/** One consent's texts: what it means, what happens with yes / with no. */
class ConsentText(val title: String, val badge: String, val what: String, val yes: List<String>, val no: List<String>,
                  val needsSms: String?)

class PermissionText(val title: String, val why: String, val no: String)

/**
 * The privacy notice, the limits page and the consent texts (assets/legal/texts_<lang>.json; Turkish for a Turkish
 * phone, English otherwise). Kept as data so they can be reviewed by a lawyer without touching code.
 */
class LegalTexts(private val j: JSONObject) {
    private fun list(a: JSONArray) = List(a.length()) { a.getString(it) }

    val draftNote: String = j.getString("draft_note")
    val welcome = list(j.getJSONArray("welcome"))
    val noticeSummary = list(j.getJSONArray("notice_summary"))
    val noticeFull = list(j.getJSONArray("notice_full"))
    val limits = list(j.getJSONArray("limits"))
    val whereLater: String = j.getString("where_later")
    val permissionsIntro: String = j.getJSONObject("permissions").getString("intro")
    /** "112", "911", or "" (local number unknown). */
    val emergencyNumber: String = j.optString("emergency_number")
    /** US only: the parental-consent (COPPA) screen for a patient under 13. */
    val coppa: List<String> = j.optJSONArray("coppa")?.let(::list) ?: emptyList()
    val regionName: String = j.optString("region_name")
    /** Plain-language page for a child patient (shown when a parent sets up EpiProt). */
    val childSummary: List<String> = j.optJSONArray("child_summary")?.let(::list) ?: emptyList()

    fun role(r: Role): Pair<String, String> = j.getJSONObject("roles").getJSONObject(r.key).let { it.getString("title") to it.getString("text") }

    fun consent(c: Consent): ConsentText = j.getJSONObject("consents").getJSONObject(c.key).let {
        ConsentText(it.getString("title"), it.getString("badge"), it.getString("what"), list(it.getJSONArray("yes")),
            list(it.getJSONArray("no")), it.optString("needs_sms").ifEmpty { it.optString("needs_health") }.ifEmpty { null })
    }

    fun permission(key: String): PermissionText = j.getJSONObject("permissions").getJSONObject(key).let {
        PermissionText(it.getString("title"), it.getString("why"), it.getString("no"))
    }

    companion object {
        /** Text file for a region and phone language, with fallbacks (the region's English text, then Turkey's). */
        fun fileFor(region: Region?, language: String, exists: (String) -> Boolean): String {
            val r = when (region) { Region.TR, null -> "tr"; Region.EU, Region.OTHER -> "eu"; Region.US -> "us" }
            val lang = if (language == "tr") "tr" else "en"
            return listOf("texts_${r}_$lang.json", "texts_${r}_en.json", "texts_tr_$lang.json", "texts_tr_en.json")
                .first(exists)
        }

        fun load(context: Context, region: Region?, locale: Locale = Locale.getDefault()): LegalTexts {
            val files = context.assets.list("legal")!!.toSet()
            val f = fileFor(region, locale.language) { it in files }
            return LegalTexts(JSONObject(context.assets.open("legal/$f").bufferedReader().readText()))
        }
    }
}

package org.epiprot.phone.ui

import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.DateRange
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import org.epiprot.phone.PhoneMonitor
import org.epiprot.phone.R
import org.epiprot.phone.privacy.Consent
import org.epiprot.phone.privacy.LegalTexts
import org.epiprot.phone.privacy.Role
import org.epiprot.phone.ui.EpiColors as C

/** One tappable row of a menu card: icon, title, short status, arrow. */
@Composable
internal fun MenuRow(icon: ImageVector, title: String, sub: String?, tint: Color = C.TealDark, bubble: Color = C.TealSoft,
                     trailing: (@Composable () -> Unit)? = null, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        IconBubble(icon, tint, bubble, 40.dp)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            if (sub != null) Text(sub, style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
        }
        trailing?.invoke()
        Icon(Icons.Rounded.KeyboardArrowRight, null, tint = C.Grey)
    }
}

@Composable
internal fun MenuCard(content: @Composable () -> Unit) {
    EpiCard { Column(verticalArrangement = Arrangement.spacedBy(2.dp)) { content() } }
}

@Composable
private fun statusPill(on: Boolean, required: Boolean = false) {
    if (on) Pill(stringResource(R.string.consent_on), C.Mint, C.MintSoft)
    else Pill(stringResource(if (required) R.string.consent_needed else R.string.consent_off),
        if (required) C.Coral else C.InkSoft, if (required) C.CoralSoft else C.GreySoft)
    Spacer(Modifier.width(6.dp))
}

/** Settings → Privacy & consents. */
@Composable
fun PrivacyCenter(m: PhoneMonitor, open: (String) -> Unit) {
    val ctx = LocalContext.current
    val c by m.consents.collectAsStateWithLifecycle()
    val t = remember(c.region) { LegalTexts.load(ctx, c.region) }
    var confirmRedo by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }

    Text(stringResource(R.string.privacy_sub), color = C.InkSoft, modifier = Modifier.padding(start = 4.dp))

    // who decides
    EpiCard {
        CardHeader(Icons.Rounded.Person, stringResource(R.string.privacy_who))
        val role = c.role
        Text(if (role == null) "–" else "${c.consenter} · ${t.role(role).first}", color = C.Ink)
        Text(stringResource(R.string.privacy_region, t.regionName.ifBlank { "–" }), color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        if (role == Role.PARENT) Text(stringResource(R.string.privacy_child_note), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
        if (role == Role.PARENT) TextButton(onClick = { open("child") }) { Text(stringResource(R.string.privacy_child_page), color = C.TealDark) }
        TextButton(onClick = { confirmRedo = true }) { Text(stringResource(R.string.privacy_redo), color = C.TealDark) }
    }

    // the consents
    Text(stringResource(R.string.privacy_consents), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(start = 4.dp))
    MenuCard {
        Consent.entries.forEachIndexed { i, cns ->
            if (i > 0) HorizontalDivider(color = C.Line)
            val on = c.has(cns)
            MenuRow(if (on) Icons.Rounded.CheckCircle else Icons.Rounded.Lock, t.consent(cns).title, t.consent(cns).badge,
                tint = if (on) C.Mint else C.InkSoft, bubble = if (on) C.MintSoft else C.GreySoft,
                trailing = { statusPill(on, cns.required) }) { open("consent:${cns.key}") }
        }
    }

    // documents and data
    Text(stringResource(R.string.privacy_docs), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(start = 4.dp))
    MenuCard {
        MenuRow(Icons.Rounded.Info, stringResource(R.string.privacy_notice), stringResource(R.string.privacy_notice_sub)) { open("notice") }
        HorizontalDivider(color = C.Line)
        MenuRow(Icons.Rounded.Warning, stringResource(R.string.privacy_limits), stringResource(R.string.privacy_limits_sub),
            tint = C.Amber, bubble = C.AmberSoft) { open("limits") }
        HorizontalDivider(color = C.Line)
        MenuRow(Icons.Rounded.DateRange, stringResource(R.string.privacy_history), stringResource(R.string.privacy_history_sub)) { open("history") }
    }
    MenuCard {
        MenuRow(Icons.Rounded.Share, stringResource(R.string.privacy_export), stringResource(R.string.privacy_export_sub)) {
            val name = m.exportData()
            Toast.makeText(ctx, if (name != null) ctx.getString(R.string.privacy_export_done, name) else ctx.getString(R.string.privacy_export_failed),
                Toast.LENGTH_LONG).show()
        }
        HorizontalDivider(color = C.Line)
        MenuRow(Icons.Rounded.Delete, stringResource(R.string.privacy_delete), stringResource(R.string.privacy_delete_sub),
            tint = C.Coral, bubble = C.CoralSoft) { confirmDelete = true }
    }
    Text(t.draftNote, style = MaterialTheme.typography.bodySmall, color = C.Grey, modifier = Modifier.padding(start = 4.dp))

    if (confirmRedo) AlertDialog(
        onDismissRequest = { confirmRedo = false },
        title = { Text(stringResource(R.string.privacy_redo)) },
        text = { Text(stringResource(R.string.privacy_redo_text)) },
        confirmButton = { TextButton(onClick = { confirmRedo = false; m.consentStore.restartSetup(); m.consentsChanged() }) {
            Text(stringResource(R.string.privacy_redo_go), color = C.TealDark) } },
        dismissButton = { TextButton(onClick = { confirmRedo = false }) { Text(stringResource(R.string.cancel)) } },
    )
    if (confirmDelete) DeleteDialog(m) { confirmDelete = false }
}

@Composable
private fun DeleteDialog(m: PhoneMonitor, close: () -> Unit) {
    var sure by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = close,
        icon = { Icon(Icons.Rounded.Delete, null, tint = C.Coral) },
        title = { Text(stringResource(R.string.privacy_delete)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(stringResource(R.string.privacy_delete_text))
                Row(Modifier.clickable { sure = !sure }, verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(sure, { sure = it }, colors = CheckboxDefaults.colors(checkedColor = C.Coral))
                    Text(stringResource(R.string.privacy_delete_sure))
                }
            }
        },
        confirmButton = { TextButton(enabled = sure && !m.alarmBusy, onClick = { close(); m.deleteAllData() }) {
            Text(stringResource(R.string.privacy_delete_go), color = if (sure) C.Coral else C.Grey, fontWeight = FontWeight.SemiBold) } },
        dismissButton = { TextButton(onClick = close) { Text(stringResource(R.string.cancel)) } },
    )
}

/** One consent: full explanation and the button to give / withdraw it (with the consequences confirmed first). */
@Composable
fun ConsentDetail(m: PhoneMonitor, consent: Consent) {
    val ctx = LocalContext.current
    val c by m.consents.collectAsStateWithLifecycle()
    val t = remember(c.region) { LegalTexts.load(ctx, c.region) }
    val text = t.consent(consent)
    val on = c.has(consent)
    var confirm by remember { mutableStateOf<Boolean?>(null) }     // true = give, false = withdraw
    var busy by remember { mutableStateOf(false) }

    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(stringResource(R.string.consent_current), color = C.InkSoft, modifier = Modifier.padding(end = 8.dp))
        statusPill(on, consent.required)
    }
    if (consent == Consent.LOCATION && !c.smsAllowed) EpiCard(container = C.GreySoft) { Text(text.needsSms ?: "", color = C.InkSoft) }
    ConsentContent(text, consent, c.role)
    if (on) SoftButton(stringResource(R.string.consent_withdraw), C.Coral) { if (m.alarmBusy) busy = true else confirm = false }
    else PrimaryButton(stringResource(R.string.consent_give)) { if (m.alarmBusy) busy = true else confirm = true }

    confirm?.let { give ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(stringResource(if (give) R.string.consent_give_q else R.string.consent_withdraw_q)) },
            text = { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(stringResource(R.string.consent_then))
                (if (give) text.yes else text.no).forEach { Text("• $it") }
            } },
            confirmButton = { TextButton(onClick = {
                confirm = null
                m.consentStore.set(consent, give)
                // withdrawing SMS also makes the location consent meaningless; keep it recorded but it has no effect
                m.consentsChanged()
                Toast.makeText(ctx, ctx.getString(if (give) R.string.consent_given else R.string.consent_withdrawn), Toast.LENGTH_SHORT).show()
            }) { Text(stringResource(if (give) R.string.consent_agree else R.string.consent_withdraw), color = if (give) C.TealDark else C.Coral) } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }
    if (busy) AlertDialog(
        onDismissRequest = { busy = false },
        title = { Text(stringResource(R.string.consent_busy_title)) },
        text = { Text(stringResource(R.string.consent_busy_text)) },
        confirmButton = { TextButton(onClick = { busy = false }) { Text("OK") } },
    )
}

@Composable
fun ChildInfoPage(m: PhoneMonitor) {
    val ctx = LocalContext.current
    val c by m.consents.collectAsStateWithLifecycle()
    val t = remember(c.region) { LegalTexts.load(ctx, c.region) }
    EpiCard(container = C.MintSoft) { ChildBullets(t.childSummary) }
}

@Composable
fun NoticePage(m: PhoneMonitor) {
    val ctx = LocalContext.current
    val c by m.consents.collectAsStateWithLifecycle()
    val t = remember(c.region) { LegalTexts.load(ctx, c.region) }
    EpiCard { Bullets(t.noticeSummary, Icons.Rounded.Lock, C.TealDark) }
    EpiCard { NoticeText(t.noticeFull) }
    Text(t.draftNote, style = MaterialTheme.typography.bodySmall, color = C.Grey)
}

@Composable
fun LimitsPage(m: PhoneMonitor) {
    val ctx = LocalContext.current
    val c by m.consents.collectAsStateWithLifecycle()
    val t = remember(c.region) { LegalTexts.load(ctx, c.region) }
    EpiCard(container = C.AmberSoft) { Bullets(t.limits, Icons.Rounded.Warning, C.Amber) }
}

@Composable
fun HistoryPage(m: PhoneMonitor) {
    val ctx = LocalContext.current
    val c by m.consents.collectAsStateWithLifecycle()
    val t = remember(c.region) { LegalTexts.load(ctx, c.region) }
    val items = remember(c) { m.consentStore.history() }
    if (items.isEmpty()) Text(stringResource(R.string.privacy_history_empty), color = C.InkSoft)
    EpiCard {
        items.forEachIndexed { i, r ->
            if (i > 0) HorizontalDivider(color = C.Line)
            val cns = Consent.entries.firstOrNull { it.key == r.item }
            val label = when {
                cns != null -> t.consent(cns).title
                r.item.startsWith("ack:notice") -> ctx.getString(R.string.hist_notice)
                r.item.startsWith("ack:limits") -> ctx.getString(R.string.hist_limits)
                r.item.startsWith("who:") -> ctx.getString(R.string.hist_who)
                r.item.startsWith("region:") -> ctx.getString(R.string.hist_region) + " (" + r.item.substringAfter(':').uppercase() + ")"
                r.item == "ack:parental" -> ctx.getString(R.string.hist_parental)
                r.item == "child_under13" -> ctx.getString(R.string.hist_under13)
                r.item == "birth_year" -> ctx.getString(R.string.hist_birth_year)
                r.item.startsWith("caregiver_agreed:") -> ctx.getString(R.string.hist_caregiver, r.item.substringAfter(':'))
                r.item == "setup_completed" -> ctx.getString(R.string.hist_setup_done)
                r.item == "setup_restarted" -> ctx.getString(R.string.hist_setup_redo)
                else -> r.item
            }
            val state = when {
                cns != null || r.item.startsWith("caregiver_agreed:") ->
                    ctx.getString(if (r.granted) R.string.hist_granted else R.string.hist_declined)
                else -> ""
            }
            Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(if (r.granted) Icons.Rounded.CheckCircle else Icons.Rounded.Close, null,
                    tint = if (r.granted) C.Mint else C.InkSoft, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(label + if (state.isNotEmpty()) " · $state" else "", style = MaterialTheme.typography.bodyMedium)
                    Text("${dateTime(r.timeMs)} · ${r.by.ifBlank { "–" }} · v${r.version}", style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
                }
            }
        }
    }
}


package org.epiprot.phone.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import org.epiprot.phone.PhoneMonitor
import org.epiprot.phone.R
import org.epiprot.phone.privacy.Ack
import org.epiprot.phone.privacy.Consent
import org.epiprot.phone.privacy.ConsentText
import org.epiprot.phone.privacy.LegalTexts
import org.epiprot.phone.privacy.Region
import org.epiprot.phone.privacy.Role
import org.epiprot.phone.ui.EpiColors as C

private enum class Step { REGION, WELCOME, WHO, COPPA, CHILD, NOTICE, LIMITS, HEALTH, SMS, LOCATION, SIGNALS, RESEARCH, PERMISSIONS, DONE }

/**
 * First-start setup, shown before anything is processed and again whenever the texts change:
 * who decides -> privacy notice (information only) -> limits (understood) -> one screen per consent
 * (agree / don't agree, consequences of both) -> permissions explained before Android asks -> summary.
 * Leaving the app or pressing back is never a decision; answers already given are kept and the setup continues.
 */
@Composable
fun Onboarding(m: PhoneMonitor, activity: MainActivity) {
    val ctx = LocalContext.current
    val c by m.consents.collectAsStateWithLifecycle()
    val t = remember(c.region) { LegalTexts.load(ctx, c.region) }
    var step by rememberSaveable { mutableIntStateOf(0) }
    // the COPPA step exists only for a US patient under 13
    val steps = Step.entries.filter {
        (it != Step.COPPA || (c.region == Region.US && c.childUnder13)) && (it != Step.CHILD || c.role == Role.PARENT)
    }
    step = step.coerceAtMost(steps.lastIndex)
    val cur = steps[step]
    fun next() { step = (step + 1).coerceAtMost(steps.lastIndex) }
    fun back() { step = (step - 1).coerceAtLeast(0) }
    BackHandler(enabled = step > 0) { back() }

    Column(Modifier.fillMaxSize().background(C.Background)) {
        // header: back + progress
        Row(Modifier.fillMaxWidth().padding(start = 8.dp, end = 20.dp, top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            if (step > 0) IconButton(onClick = { back() }) { Icon(Icons.Rounded.ArrowBack, stringResource(R.string.back), tint = C.Ink) }
            else Spacer(Modifier.width(48.dp))
            LinearProgressIndicator(progress = { (step + 1f) / steps.size }, modifier = Modifier.weight(1f).height(6.dp)
                .clip(RoundedCornerShape(50)), color = C.Teal, trackColor = C.Line)
            Spacer(Modifier.width(12.dp))
            Text("${step + 1}/${steps.size}", color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
        }
        val scroll = rememberScrollState()
        androidx.compose.runtime.LaunchedEffect(step) { scroll.scrollTo(0) }
        Column(Modifier.weight(1f).verticalScroll(scroll).padding(horizontal = 20.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            when (cur) {
                Step.REGION -> RegionStep(m, c.region) { next() }
                Step.WELCOME -> Welcome(t) { next() }
                Step.WHO -> Who(m, t, c.role, c.consenter, c.region, c.childUnder13) { next() }
                Step.COPPA -> Coppa(m, t) { next() }
                Step.CHILD -> ChildPage(t, c.consenter) { next() }
                Step.NOTICE -> Notice(t) { m.consentStore.ack(Ack.NOTICE); m.consentsChanged(); next() }
                Step.LIMITS -> Limits(t) { m.consentStore.ack(Ack.LIMITS); m.consentsChanged(); next() }
                Step.HEALTH -> ConsentStep(m, t, Consent.HEALTH_DATA, c.role) { next() }
                Step.SMS -> ConsentStep(m, t, Consent.CAREGIVER_SMS, c.role) { next() }
                Step.LOCATION -> if (c.smsAllowed) ConsentStep(m, t, Consent.LOCATION, c.role) { next() }
                    else NotApplicable(t.consent(Consent.LOCATION)) { m.consentStore.set(Consent.LOCATION, false); m.consentsChanged(); next() }
                Step.SIGNALS -> if (c.has(Consent.HEALTH_DATA)) ConsentStep(m, t, Consent.SIGNALS, c.role) { next() }
                    else NotApplicable(t.consent(Consent.SIGNALS)) { m.consentStore.set(Consent.SIGNALS, false); m.consentsChanged(); next() }
                Step.RESEARCH -> ConsentStep(m, t, Consent.RESEARCH, c.role) { next() }
                Step.PERMISSIONS -> Permissions(t, activity, c.smsAllowed, c.locationAllowed) { next() }
                Step.DONE -> Done(t, c.granted) { m.consentStore.finishSetup(); m.consentsChanged() }
            }
            Text(t.draftNote, style = MaterialTheme.typography.bodySmall, color = C.Grey)
        }
    }
}

// ------------------------------------------------------------------ steps

@Composable
private fun RegionStep(m: PhoneMonitor, current: Region?, onNext: () -> Unit) {
    val ctx = LocalContext.current
    val guess = remember {
        val tm = ctx.getSystemService(android.telephony.TelephonyManager::class.java)
        Region.guess(tm?.simCountryIso?.ifBlank { null } ?: tm?.networkCountryIso?.ifBlank { null }
            ?: java.util.Locale.getDefault().country)
    }
    var sel by remember { mutableStateOf(current ?: guess) }
    Text(stringResource(R.string.ob_region_title), style = MaterialTheme.typography.headlineMedium)
    Text(stringResource(R.string.ob_region_text), color = C.InkSoft)
    listOf(
        Region.TR to R.string.region_tr, Region.EU to R.string.region_eu,
        Region.US to R.string.region_us, Region.OTHER to R.string.region_other,
    ).forEach { (r, label) ->
        val on = sel == r
        Column(Modifier.fillMaxWidth().clip(MaterialTheme.shapes.large).background(if (on) C.TealSoft else Color.White)
            .border(2.dp, if (on) C.Teal else Color.Transparent, MaterialTheme.shapes.large)
            .clickable { sel = r }.padding(18.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(22.dp).clip(CircleShape).border(2.dp, if (on) C.Teal else C.Grey, CircleShape).padding(4.dp)) {
                    if (on) Box(Modifier.fillMaxSize().clip(CircleShape).background(C.Teal))
                }
                Spacer(Modifier.width(12.dp))
                Text(stringResource(label), style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                if (r == guess) Pill(stringResource(R.string.region_guess), C.TealDark, Color.White)
            }
            if (on) Text(stringResource(when (r) {
                Region.TR -> R.string.region_tr_note
                Region.EU -> R.string.region_eu_note
                Region.US -> R.string.region_us_note
                Region.OTHER -> R.string.region_other_note
            }), color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        }
    }
    PrimaryButton(stringResource(R.string.ob_continue)) { m.consentStore.setRegion(sel); m.consentsChanged(); onNext() }
}

@Composable
private fun Coppa(m: PhoneMonitor, t: LegalTexts, onNext: () -> Unit) {
    var sig by remember { mutableStateOf("") }
    var certify by remember { mutableStateOf(false) }
    Pill(stringResource(R.string.ob_coppa_badge), C.CoralDark, C.CoralSoft)
    Text(stringResource(R.string.ob_coppa_title), style = MaterialTheme.typography.titleLarge)
    EpiCard { Bullets(t.coppa, Icons.Rounded.Info, C.TealDark) }
    OutlinedTextField(sig, { sig = it }, label = { Text(stringResource(R.string.ob_coppa_sign)) },
        singleLine = true, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth())
    Row(Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).clickable { certify = !certify }.padding(4.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Checkbox(certify, { certify = it }, colors = CheckboxDefaults.colors(checkedColor = C.Teal))
        Text(stringResource(R.string.ob_coppa_certify), style = MaterialTheme.typography.bodyMedium)
    }
    Button(onClick = { m.consentStore.parentalConsent(sig); m.consentsChanged(); onNext() }, enabled = certify && sig.trim().length >= 3,
        modifier = Modifier.fillMaxWidth().height(54.dp), shape = RoundedCornerShape(18.dp),
        colors = ButtonDefaults.buttonColors(containerColor = C.Teal)) { Text(stringResource(R.string.ob_coppa_go), style = MaterialTheme.typography.labelLarge) }
    Text(stringResource(R.string.ob_coppa_no), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun ChildPage(t: LegalTexts, parent: String, onNext: () -> Unit) {
    Pill(stringResource(R.string.ob_child_badge), C.TealDark, C.TealSoft)
    Text(stringResource(R.string.ob_child_title), style = MaterialTheme.typography.headlineMedium)
    Text(stringResource(R.string.ob_child_text, parent.ifBlank { "–" }), color = C.InkSoft)
    EpiCard(container = C.MintSoft) { ChildBullets(t.childSummary) }
    PrimaryButton(stringResource(R.string.ob_child_done)) { onNext() }
}

/** Big, friendly bullets for children. */
@Composable
internal fun ChildBullets(items: List<String>) {
    val icons = listOf(Icons.Rounded.Info, Icons.Rounded.CheckCircle, Icons.Rounded.Lock, Icons.Rounded.Check, Icons.Rounded.Info, Icons.Rounded.Check)
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        items.forEachIndexed { i, s ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconBubble(icons[i % icons.size], C.Mint, Color.White, 40.dp)
                Spacer(Modifier.width(14.dp))
                Text(s, style = MaterialTheme.typography.bodyLarge, color = C.Ink)
            }
        }
    }
}

@Composable
private fun Welcome(t: LegalTexts, onNext: () -> Unit) {
    Box(Modifier.size(72.dp).clip(CircleShape).background(androidx.compose.ui.graphics.Brush.linearGradient(listOf(C.Teal, C.Mint))),
        contentAlignment = Alignment.Center) { Text("E", color = Color.White, fontSize = 32.sp, fontWeight = FontWeight.Bold) }
    Text(stringResource(R.string.ob_welcome_title), style = MaterialTheme.typography.headlineMedium)
    EpiCard { Bullets(t.welcome, Icons.Rounded.Info, C.TealDark) }
    PrimaryButton(stringResource(R.string.ob_begin)) { onNext() }
}

@Composable
private fun Who(m: PhoneMonitor, t: LegalTexts, role0: Role?, name0: String, region: Region?, under13_0: Boolean,
                onNext: () -> Unit) {
    var role by remember { mutableStateOf(role0) }
    var under13 by remember { mutableStateOf<Boolean?>(if (role0 == Role.PARENT && region == Region.US) under13_0 else null) }
    var birth by remember { mutableStateOf(m.consents.value.birthYear?.toString() ?: "") }
    val year = java.util.Calendar.getInstance().get(java.util.Calendar.YEAR)
    var name by remember { mutableStateOf(name0) }
    var patient by remember { mutableStateOf(m.settings.patientName) }
    Text(stringResource(R.string.ob_who_title), style = MaterialTheme.typography.titleLarge)
    Text(stringResource(R.string.ob_who_text), color = C.InkSoft)
    Role.entries.forEach { r ->
        val (title, text) = t.role(r)
        val sel = role == r
        Column(Modifier.fillMaxWidth().clip(MaterialTheme.shapes.large).background(if (sel) C.TealSoft else Color.White)
            .border(2.dp, if (sel) C.Teal else Color.Transparent, MaterialTheme.shapes.large)
            .clickable { role = r }.padding(18.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(22.dp).clip(CircleShape).border(2.dp, if (sel) C.Teal else C.Grey, CircleShape).padding(4.dp)) {
                    if (sel) Box(Modifier.fillMaxSize().clip(CircleShape).background(C.Teal))
                }
                Spacer(Modifier.width(12.dp))
                Text(title, style = MaterialTheme.typography.titleMedium)
            }
            if (sel) Text(text, color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        }
    }
    OutlinedTextField(name, { name = it }, label = { Text(stringResource(
        if (role?.forSomeoneElse == true) R.string.ob_your_name_rep else R.string.ob_your_name)) },
        singleLine = true, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth())
    if (role?.forSomeoneElse == true)
        OutlinedTextField(patient, { patient = it }, label = { Text(stringResource(R.string.patient_name)) },
            singleLine = true, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth())
    val askAge = region == Region.US && role == Role.PARENT
    val birthOk = role != Role.PARENT || birth.toIntOrNull()?.let { it in (year - 18)..year } == true
    if (role == Role.PARENT) {
        OutlinedTextField(birth, { if (it.length <= 4 && it.all(Char::isDigit)) birth = it },
            label = { Text(stringResource(R.string.ob_birth_year)) }, singleLine = true, shape = RoundedCornerShape(16.dp),
            keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Number),
            supportingText = { Text(stringResource(R.string.ob_birth_year_note)) }, isError = birth.length == 4 && !birthOk,
            modifier = Modifier.fillMaxWidth())
    }
    if (askAge) {
        Text(stringResource(R.string.ob_under13_q), style = MaterialTheme.typography.titleMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            listOf(true to R.string.yes, false to R.string.no).forEach { (v, label) ->
                val on = under13 == v
                OutlinedButton(onClick = { under13 = v }, modifier = Modifier.weight(1f).height(50.dp), shape = RoundedCornerShape(16.dp),
                    colors = ButtonDefaults.outlinedButtonColors(containerColor = if (on) C.TealSoft else Color.Transparent,
                        contentColor = if (on) C.TealDark else C.Ink)) { Text(stringResource(label)) }
            }
        }
    }
    val ok = role != null && name.isNotBlank() && (role == Role.SELF || patient.isNotBlank()) && (!askAge || under13 != null) && birthOk
    Button(onClick = {
        val r = role ?: return@Button
        m.consentStore.setWho(r, name)
        m.consentStore.setChildUnder13(askAge && under13 == true)
        m.consentStore.setBirthYear(if (r == Role.PARENT) birth.toIntOrNull() else null)
        m.settings.patientName = if (r == Role.SELF) name else patient
        m.consentsChanged(); onNext()
    }, enabled = ok, modifier = Modifier.fillMaxWidth().height(54.dp), shape = RoundedCornerShape(18.dp),
        colors = ButtonDefaults.buttonColors(containerColor = C.Teal)) { Text(stringResource(R.string.ob_continue), style = MaterialTheme.typography.labelLarge) }
}

@Composable
private fun Notice(t: LegalTexts, onNext: () -> Unit) {
    var full by rememberSaveable { mutableStateOf(false) }
    Text(stringResource(R.string.ob_notice_title), style = MaterialTheme.typography.titleLarge)
    Pill(stringResource(R.string.ob_notice_not_consent), C.TealDark, C.TealSoft)
    EpiCard { Bullets(t.noticeSummary, Icons.Rounded.Lock, C.TealDark) }
    if (full) EpiCard { NoticeText(t.noticeFull) }
    TextButton(onClick = { full = !full }) {
        Text(stringResource(if (full) R.string.ob_notice_hide else R.string.ob_notice_read_full), color = C.TealDark)
    }
    PrimaryButton(stringResource(R.string.ob_notice_read)) { onNext() }
}

@Composable
private fun Limits(t: LegalTexts, onNext: () -> Unit) {
    var understood by rememberSaveable { mutableStateOf(false) }
    Text(stringResource(R.string.ob_limits_title), style = MaterialTheme.typography.titleLarge)
    EpiCard(container = C.AmberSoft) { Bullets(t.limits, Icons.Rounded.Warning, C.Amber) }
    Row(Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).clickable { understood = !understood }.padding(4.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Checkbox(understood, { understood = it }, colors = CheckboxDefaults.colors(checkedColor = C.Teal))
        Text(stringResource(R.string.ob_limits_ok), style = MaterialTheme.typography.bodyLarge)
    }
    Button(onClick = onNext, enabled = understood, modifier = Modifier.fillMaxWidth().height(54.dp), shape = RoundedCornerShape(18.dp),
        colors = ButtonDefaults.buttonColors(containerColor = C.Teal)) { Text(stringResource(R.string.ob_continue), style = MaterialTheme.typography.labelLarge) }
}

@Composable
private fun ConsentStep(m: PhoneMonitor, t: LegalTexts, consent: Consent, role: Role?, onNext: () -> Unit) {
    val text = t.consent(consent)
    var warnRequired by remember { mutableStateOf(false) }
    ConsentContent(text, consent, role)
    ConsentButtons(
        onAgree = { m.consentStore.set(consent, true); m.consentsChanged(); onNext() },
        onDecline = {
            if (consent.required) warnRequired = true
            else { m.consentStore.set(consent, false); m.consentsChanged(); onNext() }
        },
    )
    if (warnRequired) AlertDialog(
        onDismissRequest = { warnRequired = false },
        icon = { Icon(Icons.Rounded.Warning, null, tint = C.Amber) },
        title = { Text(stringResource(R.string.ob_required_title)) },
        text = { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) { text.no.forEach { Text("• $it") } } },
        confirmButton = { TextButton(onClick = { warnRequired = false }) { Text(stringResource(R.string.ob_required_back)) } },
        dismissButton = {
            TextButton(onClick = { warnRequired = false; m.consentStore.set(consent, false); m.consentsChanged(); onNext() }) {
                Text(stringResource(R.string.ob_required_continue), color = C.Coral)
            }
        },
    )
}

@Composable
private fun NotApplicable(text: ConsentText, onNext: () -> Unit) {
    Text(text.title, style = MaterialTheme.typography.titleLarge)
    EpiCard(container = C.GreySoft) {
        CardHeader(Icons.Rounded.Info, stringResource(R.string.ob_not_applicable), tint = C.InkSoft, bubble = Color.White)
        Text(text.needsSms ?: "", color = C.InkSoft)
    }
    PrimaryButton(stringResource(R.string.ob_continue)) { onNext() }
}

@Composable
private fun Permissions(t: LegalTexts, activity: MainActivity, sms: Boolean, location: Boolean, onNext: () -> Unit) {
    Text(stringResource(R.string.ob_perms_title), style = MaterialTheme.typography.titleLarge)
    Text(t.permissionsIntro, color = C.InkSoft)
    val keys = buildList {
        add("notifications"); add("bluetooth")
        if (sms) add("sms")
        if (location) add("location")
    }
    keys.forEach { k ->
        val p = t.permission(k)
        EpiCard {
            Text(p.title, style = MaterialTheme.typography.titleMedium)
            Text(p.why, color = C.Ink)
            Text(stringResource(R.string.ob_if_refused) + " " + p.no, color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
        }
    }
    if (!sms) Text(stringResource(R.string.ob_perms_sms_skipped), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
    PrimaryButton(stringResource(R.string.ob_perms_allow)) { activity.requestPermissionsFor(keys) { onNext() } }
    SoftButton(stringResource(R.string.ob_perms_later)) { onNext() }
}

@Composable
private fun Done(t: LegalTexts, granted: Set<Consent>, onFinish: () -> Unit) {
    Text(stringResource(R.string.ob_done_title), style = MaterialTheme.typography.headlineMedium)
    EpiCard {
        Consent.entries.forEach { cns ->
            val on = cns in granted
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconBubble(if (on) Icons.Rounded.Check else Icons.Rounded.Close, if (on) C.Mint else C.InkSoft,
                    if (on) C.MintSoft else C.GreySoft, 32.dp)
                Spacer(Modifier.width(12.dp))
                Text(t.consent(cns).title, modifier = Modifier.weight(1f))
                Text(stringResource(if (on) R.string.consent_on else R.string.consent_off),
                    color = if (on) C.Mint else C.InkSoft, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold)
            }
        }
    }
    if (Consent.HEALTH_DATA !in granted) EpiCard(container = C.AmberSoft) {
        CardHeader(Icons.Rounded.Warning, stringResource(R.string.ob_done_no_monitoring), tint = C.Amber, bubble = Color.White)
    }
    if (Consent.HEALTH_DATA in granted && Consent.CAREGIVER_SMS !in granted) EpiCard(container = C.AmberSoft) {
        CardHeader(Icons.Rounded.Warning, stringResource(R.string.ob_done_no_sms), tint = C.Amber, bubble = Color.White)
    }
    EpiCard(container = C.TealSoft) {
        CardHeader(Icons.Rounded.Info, stringResource(R.string.ob_where_title), bubble = Color.White)
        Text(t.whereLater, color = C.Ink)
    }
    PrimaryButton(stringResource(R.string.ob_finish), Icons.Rounded.CheckCircle) { onFinish() }
}

// ------------------------------------------------------------------ shared pieces (also used by the privacy centre)

@Composable
internal fun ConsentContent(text: ConsentText, consent: Consent, role: Role?) {
    Pill(text.badge, if (consent.required) C.CoralDark else C.TealDark, if (consent.required) C.CoralSoft else C.TealSoft)
    Text(text.title, style = MaterialTheme.typography.titleLarge)
    if (role?.forSomeoneElse == true)
        Text(stringResource(R.string.consent_on_behalf), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
    EpiCard {
        Text(stringResource(R.string.consent_what), style = MaterialTheme.typography.titleMedium)
        Text(text.what, color = C.Ink)
    }
    EpiCard(container = C.MintSoft) {
        Text(stringResource(R.string.consent_if_yes), style = MaterialTheme.typography.titleMedium, color = C.Mint)
        Bullets(text.yes, Icons.Rounded.Check, C.Mint)
    }
    EpiCard(container = C.AmberSoft) {
        Text(stringResource(R.string.consent_if_no), style = MaterialTheme.typography.titleMedium, color = C.Amber)
        Bullets(text.no, Icons.Rounded.Close, C.Amber)
    }
    Text(stringResource(R.string.consent_change_later), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
}

/** "I agree" and "I don't agree" with the same size; nothing is pre-selected. */
@Composable
internal fun ConsentButtons(onAgree: () -> Unit, onDecline: () -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        OutlinedButton(onClick = onDecline, modifier = Modifier.weight(1f).height(54.dp), shape = RoundedCornerShape(18.dp),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = C.Ink)) {
            Text(stringResource(R.string.consent_decline), style = MaterialTheme.typography.labelLarge)
        }
        Button(onClick = onAgree, modifier = Modifier.weight(1f).height(54.dp), shape = RoundedCornerShape(18.dp),
            colors = ButtonDefaults.buttonColors(containerColor = C.Teal)) {
            Text(stringResource(R.string.consent_agree), style = MaterialTheme.typography.labelLarge)
        }
    }
}

@Composable
internal fun Bullets(items: List<String>, icon: androidx.compose.ui.graphics.vector.ImageVector, tint: Color) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items.forEach {
            Row {
                Icon(icon, null, tint = tint, modifier = Modifier.size(20.dp).padding(top = 2.dp))
                Spacer(Modifier.width(10.dp))
                Text(it, color = C.Ink, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

/** The full notice: "# " lines are headings, "- " lines bullets. */
@Composable
internal fun NoticeText(lines: List<String>) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        lines.forEach { l ->
            when {
                l.startsWith("# ") -> Text(l.drop(2), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
                l.startsWith("- ") -> Row { Text("•  ", color = C.TealDark); Text(l.drop(2), style = MaterialTheme.typography.bodyMedium) }
                else -> Text(l, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

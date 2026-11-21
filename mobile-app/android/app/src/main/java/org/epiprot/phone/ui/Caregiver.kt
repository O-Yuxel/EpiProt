package org.epiprot.phone.ui

import android.Manifest
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Call
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Face
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.LocationOn
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import org.epiprot.phone.R
import org.epiprot.phone.caregiver.CaregiverMode
import org.epiprot.phone.caregiver.CaregiverSms
import org.epiprot.phone.caregiver.Received
import org.epiprot.phone.ui.EpiColors as C

/** First start: who uses this phone? */
@Composable
internal fun RoleChoice(onChoose: (String) -> Unit) {
    Column(Modifier.fillMaxSize().background(C.Background).verticalScroll(rememberScrollState()).padding(22.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Spacer(Modifier.height(24.dp))
        Text(stringResource(R.string.role_title), style = MaterialTheme.typography.headlineSmall, color = C.Ink, fontWeight = FontWeight.Bold)
        Text(stringResource(R.string.role_text), color = C.InkSoft)
        RoleCard(Icons.Rounded.Face, stringResource(R.string.role_patient), stringResource(R.string.role_patient_text)) { onChoose("patient") }
        RoleCard(Icons.Rounded.Favorite, stringResource(R.string.role_caregiver), stringResource(R.string.role_caregiver_text)) { onChoose("caregiver") }
        Text(stringResource(R.string.role_later), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun RoleCard(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, text: String, onClick: () -> Unit) {
    EpiCard(Modifier.clickable(onClick = onClick)) {
        CardHeader(icon, title)
        Text(text, color = C.InkSoft)
    }
}

/** Caregiver mode: followed patients, what the phone needs to ring, a test, the last alarms. */
@Composable
internal fun CaregiverHome(activity: MainActivity, prefillNumber: String?, onSwitchToPatient: () -> Unit) {
    val c = LocalContext.current
    var version by remember { mutableIntStateOf(0) }
    @Suppress("UNUSED_EXPRESSION") version                     // re-read after changes
    val pv = activity.permVersion.intValue
    val patients = remember(version) { CaregiverMode.followed(c) }
    val log = remember(version, pv) { CaregiverMode.log(c) }
    var name by remember { mutableStateOf("") }
    var number by remember { mutableStateOf(prefillNumber ?: "") }
    var switchAsk by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().background(C.Background).verticalScroll(rememberScrollState())
        .padding(horizontal = 18.dp, vertical = 14.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        EpiCard(container = C.TealSoft) {
            CardHeader(Icons.Rounded.Favorite, stringResource(R.string.cg_title), bubble = Color.White)
            Text(stringResource(R.string.cg_text), color = C.Ink)
        }

        // what the phone needs so the alarm really rings
        val nm = c.getSystemService(NotificationManager::class.java)
        val smsOk = ContextCompat.checkSelfPermission(c, Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED
        val notifOk = Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(c, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        val dndOk = nm.isNotificationPolicyAccessGranted
        val fullOk = Build.VERSION.SDK_INT < 34 || nm.canUseFullScreenIntent()
        @Suppress("UNUSED_EXPRESSION") pv
        EpiCard {
            CardHeader(Icons.Rounded.CheckCircle, stringResource(R.string.cg_ready_title),
                tint = if (smsOk && notifOk && dndOk && fullOk) C.Mint else C.Amber,
                bubble = if (smsOk && notifOk && dndOk && fullOk) C.MintSoft else C.AmberSoft)
            Need(stringResource(R.string.cg_need_sms), smsOk) {
                activity.requestPerms(listOf(Manifest.permission.RECEIVE_SMS))
            }
            val replyOk = ContextCompat.checkSelfPermission(c, Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED
            Need(stringResource(R.string.cg_need_reply), replyOk) {
                activity.requestPerms(listOf(Manifest.permission.SEND_SMS))
            }
            if (Build.VERSION.SDK_INT >= 33) Need(stringResource(R.string.cg_need_notif), notifOk) {
                activity.requestPerms(listOf(Manifest.permission.POST_NOTIFICATIONS))
            }
            Need(stringResource(R.string.cg_need_dnd), dndOk) {
                activity.startActivity(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
            }
            if (Build.VERSION.SDK_INT >= 34) Need(stringResource(R.string.cg_need_full), fullOk) {
                activity.startActivity(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:${c.packageName}")))
            }
            SoftButton(stringResource(R.string.cg_test)) {
                CaregiverMode.ring(c, Received(System.currentTimeMillis(), c.getString(R.string.cg_test_patient), "",
                    CaregiverSms.Kind.SEIZURE, c.getString(R.string.cg_test_text)))
            }
            Text(stringResource(R.string.cg_test_note), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
        }

        // the caregiver's own name, sent with "I am going"
        var myName by remember { mutableStateOf(org.epiprot.phone.data.Settings(c).caregiverName) }
        EpiCard {
            CardHeader(Icons.Rounded.Person, stringResource(R.string.cg_my_name_title))
            OutlinedTextField(myName, { myName = it.take(30); org.epiprot.phone.data.Settings(c).caregiverName = myName },
                label = { Text(stringResource(R.string.cg_my_name)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Text(stringResource(R.string.cg_my_name_note), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
        }

        // followed patients
        EpiCard {
            CardHeader(Icons.Rounded.Person, stringResource(R.string.cg_patients))
            if (patients.isEmpty()) Text(stringResource(R.string.cg_no_patients), color = C.Amber)
            patients.forEach { (n, num) ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(n, color = C.Ink, fontWeight = FontWeight.SemiBold)
                        Text(num, color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
                    }
                    TextButton({ CaregiverMode.unfollow(c, num); version++ }) { Text(stringResource(R.string.cg_remove), color = C.Coral) }
                }
            }
            OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.cg_patient_name)) },
                singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(number, { number = it }, label = { Text(stringResource(R.string.cg_patient_number)) },
                singleLine = true, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = KeyboardType.Phone))
            Text(stringResource(R.string.cg_number_note), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
            PrimaryButton(stringResource(R.string.cg_add)) {
                if (name.isNotBlank() && number.count { it.isDigit() } >= 7) {
                    CaregiverMode.follow(c, name, number); name = ""; number = ""; version++
                }
            }
        }

        // last alarms
        EpiCard {
            CardHeader(Icons.Rounded.Notifications, stringResource(R.string.cg_last))
            if (log.isEmpty()) Text(stringResource(R.string.cg_last_none), color = C.InkSoft)
            log.take(10).forEach { r ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.foundation.layout.Box(Modifier.size(10.dp).clip(CircleShape)
                        .background(if (r.kind.rings) C.Coral else C.Mint))
                    Spacer(Modifier.size(10.dp))
                    Text(stringResource(CaregiverMode.titleOf(r.kind), r.patient), Modifier.weight(1f), color = C.Ink)
                    Text(dateTime(r.timeMs), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
                }
            }
        }

        TextButton({ switchAsk = true }) { Text(stringResource(R.string.role_switch_to_patient), color = C.TealDark) }
        Spacer(Modifier.height(8.dp))
    }
    if (switchAsk) AlertDialog(onDismissRequest = { switchAsk = false },
        title = { Text(stringResource(R.string.hb_confirm_title)) },
        text = { Text(stringResource(R.string.role_switch_text)) },
        confirmButton = { TextButton({ switchAsk = false; onSwitchToPatient() }) { Text(stringResource(R.string.hb_yes)) } },
        dismissButton = { TextButton({ switchAsk = false }) { Text(stringResource(R.string.hb_cancel)) } })
}

@Composable
private fun Need(text: String, ok: Boolean, fix: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(if (ok) "✓" else "!", color = if (ok) C.Mint else C.Amber, fontWeight = FontWeight.Bold, fontSize = 18.sp,
            modifier = Modifier.padding(end = 10.dp))
        Text(text, Modifier.weight(1f), color = C.Ink)
        if (!ok) TextButton(fix) { Text(stringResource(R.string.cg_fix), color = C.TealDark) }
    }
}

/** The full-screen alarm on the caregiver's phone (also over the lock screen). */
class CaregiverAlarmActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { EpiProtTheme { AlarmScreen() } }
    }

    @Composable
    private fun AlarmScreen() {
        var ringing by remember { mutableStateOf(org.epiprot.phone.data.Settings(this).caregiverRinging) }
        val r = remember { CaregiverMode.log(this).firstOrNull() }
        if (r == null) { finish(); return }
        val emergency = r.kind == CaregiverSms.Kind.EMERGENCY
        Column(Modifier.fillMaxSize().background(if (ringing) C.Coral else C.Background).verticalScroll(rememberScrollState())
            .padding(22.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Spacer(Modifier.height(20.dp))
            Text(stringResource(CaregiverMode.titleOf(r.kind), r.patient), color = if (ringing) Color.White else C.Ink,
                fontSize = 28.sp, fontWeight = FontWeight.Bold)
            Text(dateTime(r.timeMs), color = if (ringing) Color.White else C.InkSoft)
            EpiCard { Text(CaregiverSms.readable(r.text), color = C.Ink) }
            if (ringing) PrimaryButton(stringResource(R.string.cg_going), color = C.CoralDark) {
                CaregiverMode.acknowledge(this@CaregiverAlarmActivity, r); ringing = false
            }
            if (!ringing && r.kind.rings && r.number.isNotBlank()) Text(stringResource(R.string.cg_reply_sent),
                color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
            CaregiverSms.mapsLink(r.text)?.let { link ->
                PrimaryButton(stringResource(R.string.cg_open_map), Icons.Rounded.LocationOn) {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link)))
                }
            }
            if (r.number.isNotBlank()) PrimaryButton(stringResource(R.string.cg_call_patient), Icons.Rounded.Call) {
                startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${r.number}")))
            }
            if (emergency || r.kind == CaregiverSms.Kind.NO_ANSWER || r.kind == CaregiverSms.Kind.SHOWER) PrimaryButton(stringResource(R.string.cg_call_emergency),
                Icons.Rounded.Warning, color = C.CoralDark) {
                startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${getString(R.string.cg_emergency_number)}")))
            }
            Text(stringResource(R.string.cg_alarm_note), color = if (ringing) Color.White else C.InkSoft,
                style = MaterialTheme.typography.bodySmall)
            if (!ringing) SoftButton(stringResource(R.string.cg_close)) { finish() }
        }
    }
}

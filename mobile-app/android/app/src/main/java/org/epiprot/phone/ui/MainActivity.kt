package org.epiprot.phone.ui

import android.Manifest
import android.os.Build
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.BackHandler
import androidx.compose.material.icons.rounded.ArrowBack
import androidx.compose.material.icons.rounded.KeyboardArrowRight
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Call
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.DateRange
import androidx.compose.material.icons.rounded.Email
import androidx.compose.material.icons.rounded.Face
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.Home
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.KeyboardArrowUp
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Send
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.epiprot.phone.EpiProtPhoneApp
import org.epiprot.phone.PhoneMonitor
import org.epiprot.phone.R
import org.epiprot.phone.alarm.AlarmFlow
import org.epiprot.phone.data.EventRow
import org.epiprot.phone.data.MessageRow
import org.epiprot.phone.data.SensorAlertRow
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.service.MonitoringService
import java.text.DateFormat
import java.util.Date
import org.epiprot.phone.ui.EpiColors as C

class MainActivity : ComponentActivity() {
    /** Bumped whenever permissions may have changed, so the screen re-reads them. */
    val permVersion = mutableIntStateOf(0)
    private var fromButton = false

    private var afterRequest: (() -> Unit)? = null

    private val askPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        permVersion.intValue++
        afterRequest?.let { afterRequest = null; it() }
        if (!fromButton) return@registerForActivityResult
        fromButton = false
        // refused for good (no dialog shown any more) -> the only way is the app's system settings page
        val blocked = res.filterValues { !it }.keys.any { !shouldShowRequestPermissionRationale(it) }
        if (blocked) {
            Toast.makeText(this, getString(R.string.perms_open_settings), Toast.LENGTH_LONG).show()
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
        }
    }

    /** Permission groups shown in the app: label -> permissions. */
    val permissionGroups: List<Pair<Int, List<String>>> = buildList {
        add(R.string.perm_location to listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
        add(R.string.perm_sms to listOf(Manifest.permission.SEND_SMS))
        if (Build.VERSION.SDK_INT >= 33) add(R.string.perm_notifications to listOf(Manifest.permission.POST_NOTIFICATIONS))
        if (Build.VERSION.SDK_INT >= 31) add(R.string.perm_bluetooth to listOf(Manifest.permission.BLUETOOTH_CONNECT))
    }

    fun granted(perm: String) = ContextCompat.checkSelfPermission(this, perm) == PackageManager.PERMISSION_GRANTED

    fun requestPermissions(fromButton: Boolean = false) {
        val missing = permissionGroups.flatMap { it.second }.filterNot(::granted)
        if (missing.isEmpty()) {
            if (fromButton) Toast.makeText(this, getString(R.string.perms_all_granted), Toast.LENGTH_SHORT).show()
            return
        }
        this.fromButton = fromButton
        askPermissions.launch(missing.toTypedArray())
    }

    /** Setup: asks only for the permissions of the features the user agreed to (keys as in texts_*.json). */
    fun requestPermissionsFor(keys: List<String>, then: () -> Unit) {
        val perms = keys.flatMap { k ->
            when (k) {
                "notifications" -> if (Build.VERSION.SDK_INT >= 33) listOf(Manifest.permission.POST_NOTIFICATIONS) else emptyList()
                "bluetooth" -> if (Build.VERSION.SDK_INT >= 31) listOf(Manifest.permission.BLUETOOTH_CONNECT) else emptyList()
                "sms" -> listOf(Manifest.permission.SEND_SMS)
                "location" -> listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
                else -> emptyList()
            }
        }.filterNot(::granted)
        if (perms.isEmpty()) { then(); return }
        afterRequest = then
        askPermissions.launch(perms.toTypedArray())
    }

    // ------------------------------------------------------------- app lock
    /** History and Settings are unlocked until the app goes to the background. */
    val unlocked = mutableStateOf(false)

    val deviceSecure: Boolean get() = getSystemService(android.app.KeyguardManager::class.java).isDeviceSecure

    fun unlock() {
        val b = android.hardware.biometrics.BiometricPrompt.Builder(this)
            .setTitle(getString(R.string.lock_title)).setSubtitle(getString(R.string.lock_text))
        if (Build.VERSION.SDK_INT >= 30) b.setAllowedAuthenticators(
            android.hardware.biometrics.BiometricManager.Authenticators.BIOMETRIC_STRONG or
                android.hardware.biometrics.BiometricManager.Authenticators.DEVICE_CREDENTIAL)
        else @Suppress("DEPRECATION") b.setDeviceCredentialAllowed(true)
        b.build().authenticate(android.os.CancellationSignal(), mainExecutor,
            object : android.hardware.biometrics.BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: android.hardware.biometrics.BiometricPrompt.AuthenticationResult?) {
                    unlocked.value = true
                }
            })
    }

    override fun onStop() {
        super.onStop()
        unlocked.value = false
    }

    override fun onResume() {
        super.onResume()
        permVersion.intValue++
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val monitor = EpiProtPhoneApp.monitor(this)
        setContent { EpiProtTheme { App(monitor, this) } }
    }
}

// ============================================================== frame

@Composable
private fun App(m: PhoneMonitor, activity: MainActivity) {
    val consents by m.consents.collectAsStateWithLifecycle()
    if (consents.setupNeeded) { Onboarding(m, activity); return }
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var sub by rememberSaveable { mutableStateOf<String?>(null) }      // settings sub-page
    fun openSettings(route: String?) { tab = 2; sub = route }
    BackHandler(enabled = tab == 2 && sub != null) { sub = parentOf(sub) }
    Scaffold(
        containerColor = C.Background,
        bottomBar = {
            NavigationBar(containerColor = Color.White, tonalElevation = 0.dp) {
                listOf(
                    Triple(R.string.tab_home, Icons.Rounded.Home, 0),
                    Triple(R.string.tab_events, Icons.Rounded.DateRange, 1),
                    Triple(R.string.tab_settings, Icons.Rounded.Settings, 2),
                ).forEach { (label, icon, i) ->
                    NavigationBarItem(
                        selected = tab == i, onClick = { tab = i; if (i == 2) sub = null },
                        icon = { Icon(icon, contentDescription = null) },
                        label = { Text(stringResource(label)) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = C.TealDark, selectedTextColor = C.TealDark,
                            indicatorColor = C.TealSoft, unselectedIconColor = C.Grey, unselectedTextColor = C.InkSoft,
                        ),
                    )
                }
            }
        },
    ) { pad ->
        val scroll = rememberScrollState()
        LaunchedEffect(tab, sub) { scroll.scrollTo(0) }       // every page starts at the top
        Column(
            Modifier.fillMaxSize().padding(pad).verticalScroll(scroll)
                .padding(horizontal = 18.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            val locked = tab != 0 && m.settings.appLock && activity.deviceSecure && !activity.unlocked.value
            if (locked) LockedScreen(activity)
            else when (tab) {
                0 -> Home(m, activity) { openSettings(it) }
                1 -> Events(m)
                else -> {
                    val route = sub
                    if (route == null) SettingsMenu(m, activity) { sub = it }
                    else {
                        SubPageHeader(subTitle(route)) { sub = parentOf(route) }
                        when {
                            route == "patient" -> PatientCaregiversPage(m) { sub = it }
                            route == "pin" -> PinPage(m)
                            route == "messages" -> MessagesPage(m) { sub = it }
                            route == "doctor" -> DoctorPage(m)
                            route == "permissions" -> PermissionsPage(activity)
                            route == "privacy" -> PrivacyCenter(m) { sub = it }
                            route.startsWith("consent:") -> org.epiprot.phone.privacy.Consent.entries
                                .firstOrNull { it.key == route.substringAfter(':') }?.let { ConsentDetail(m, it) }
                            route == "notice" -> NoticePage(m)
                            route == "limits" -> LimitsPage(m)
                            route == "history" -> HistoryPage(m)
                            route == "child" -> ChildInfoPage(m)
                        }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

internal fun time(ms: Long?): String = ms?.let { DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(it)) } ?: "–"
internal fun dateTime(ms: Long?): String =
    ms?.let { DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(it)) } ?: "–"

// ============================================================== building blocks

@Composable
internal fun EpiCard(
    modifier: Modifier = Modifier,
    container: Color = C.Card,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = container),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) { Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp), content = content) }
}

@Composable
internal fun IconBubble(icon: ImageVector, tint: Color, background: Color, size: Dp = 44.dp) {
    Box(Modifier.size(size).clip(CircleShape).background(background), contentAlignment = Alignment.Center) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(size * 0.55f))
    }
}

@Composable
internal fun Pill(text: String, color: Color, background: Color) {
    Text(
        text, color = color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(background).padding(horizontal = 10.dp, vertical = 4.dp),
    )
}

@Composable
internal fun SectionTitle(text: String, sub: String? = null) {
    Column(Modifier.padding(top = 6.dp, start = 4.dp)) {
        Text(text, style = MaterialTheme.typography.titleLarge, color = C.Ink)
        if (sub != null) Text(sub, style = MaterialTheme.typography.bodyMedium, color = C.InkSoft)
    }
}

@Composable
internal fun CardHeader(icon: ImageVector, title: String, tint: Color = C.TealDark, bubble: Color = C.TealSoft, trailing: @Composable () -> Unit = {}) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        IconBubble(icon, tint, bubble, 38.dp)
        Spacer(Modifier.width(12.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
        trailing()
    }
}

@Composable
internal fun PrimaryButton(text: String, icon: ImageVector? = null, color: Color = C.Teal, onClick: () -> Unit) {
    Button(
        onClick = onClick, modifier = Modifier.fillMaxWidth().height(54.dp), shape = RoundedCornerShape(18.dp),
        colors = ButtonDefaults.buttonColors(containerColor = color),
    ) {
        if (icon != null) { Icon(icon, null); Spacer(Modifier.width(8.dp)) }
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable
internal fun SoftButton(text: String, color: Color = C.TealDark, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick, modifier = Modifier.fillMaxWidth().height(50.dp), shape = RoundedCornerShape(18.dp),
        border = androidx.compose.foundation.BorderStroke(1.5.dp, color.copy(alpha = 0.35f)),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = color),
    ) { Text(text, style = MaterialTheme.typography.labelLarge) }
}

// ============================================================== home

@Composable
private fun Home(m: PhoneMonitor, activity: MainActivity, openSettings: (String?) -> Unit) {
    val consents by m.consents.collectAsStateWithLifecycle()
    val running by m.running.collectAsStateWithLifecycle()
    val st by m.status.collectAsStateWithLifecycle()
    val watch by m.watch.collectAsStateWithLifecycle()
    val demo by m.demo.collectAsStateWithLifecycle()
    val version by m.logVersion.collectAsStateWithLifecycle()
    var now by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(1_000) } }

    // greeting
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp, start = 4.dp)) {
        Column(Modifier.weight(1f)) {
            val name = m.settings.patientName.trim()
            Text(if (name.isEmpty()) stringResource(R.string.greeting) else stringResource(R.string.greeting_named, name),
                style = MaterialTheme.typography.headlineMedium, color = C.Ink)
            Text(DateFormat.getDateInstance(DateFormat.FULL).format(Date(now)), color = C.InkSoft)
        }
        Box(Modifier.size(46.dp).clip(CircleShape).background(Brush.linearGradient(listOf(C.Teal, C.Mint))),
            contentAlignment = Alignment.Center) {
            Text("E", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp)
        }
    }

    if (st.flowState != AlarmFlow.State.Idle) AlarmCard(m, st.flowState, now, st.demo)
    else if (!consents.canMonitor) EpiCard(container = C.AmberSoft) {
        CardHeader(Icons.Rounded.Lock, stringResource(R.string.home_no_consent_title), tint = C.Amber, bubble = Color.White)
        Text(stringResource(R.string.home_no_consent_text), color = C.Ink)
        PrimaryButton(stringResource(R.string.home_review_consent)) { openSettings("consent:health_data") }
    }
    else StatusHero(running, st.windows > 0, activity)
    if (consents.patientNowAdult(java.util.Calendar.getInstance().get(java.util.Calendar.YEAR))) EpiCard(container = C.AmberSoft) {
        CardHeader(Icons.Rounded.Person, stringResource(R.string.home_adult_title, m.settings.patientName.ifBlank { "–" }), tint = C.Amber, bubble = Color.White)
        Text(stringResource(R.string.home_adult_text), color = C.Ink)
        TextButton(onClick = { openSettings("privacy") }) { Text(stringResource(R.string.privacy_title), color = C.TealDark) }
    }
    if (consents.canMonitor && !consents.smsAllowed) EpiCard(container = C.AmberSoft) {
        CardHeader(Icons.Rounded.Warning, stringResource(R.string.home_no_sms_title), tint = C.Amber, bubble = Color.White)
        Text(stringResource(R.string.home_no_sms_text), color = C.Ink)
        TextButton(onClick = { openSettings("consent:caregiver_sms") }) { Text(stringResource(R.string.home_review_consent), color = C.TealDark) }
    }

    // devices
    val watchOk = now - watch.lastDataMs < 10_000
    Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        DeviceCard(
            Modifier.weight(1f), Icons.Rounded.Favorite, stringResource(R.string.watch), watchOk,
            big = if (watchOk && watch.heartRate.isFinite()) "${watch.heartRate.toInt()}" else null,
            unit = stringResource(R.string.bpm),
            status = if (watchOk) stringResource(R.string.connected) else stringResource(R.string.not_connected),
            extra = watch.batteryPct?.takeIf { watchOk }?.let { stringResource(R.string.battery, it) },
        )
        DeviceCard(
            Modifier.weight(1f), Icons.Rounded.Face, stringResource(R.string.headband), false,
            big = null, unit = "", status = stringResource(R.string.coming_soon),
            extra = stringResource(R.string.headband_proto),
        )
    }

    // detection mode
    if (running || st.windows > 0) {
        val q = st.quality
        val brainOk = q["brain"] == HealthMonitor.Quality.OK
        val (text, good) = when {
            st.windows == 0L -> stringResource(R.string.detection_waiting) to true
            !brainOk -> stringResource(R.string.detection_limited) to false
            st.noHeartRate -> stringResource(R.string.detection_no_hr) to true
            st.fallback -> stringResource(R.string.detection_backup) to true
            else -> stringResource(R.string.detection_full) to true
        }
        EpiCard {
            CardHeader(if (good) Icons.Rounded.CheckCircle else Icons.Rounded.Warning, stringResource(R.string.detection),
                tint = if (good) C.Mint else C.Amber, bubble = if (good) C.MintSoft else C.AmberSoft)
            Text(text, color = C.InkSoft)
        }
    }

    // sensor problems
    if (st.openWarnings.isNotEmpty()) EpiCard(container = C.AmberSoft) {
        CardHeader(Icons.Rounded.Warning, stringResource(R.string.open_problems), tint = C.Amber, bubble = Color.White)
        st.openWarnings.forEach { Text("• ${it.code.replace('_', ' ').lowercase()} · ${time(it.warnedMs)}", color = C.Ink) }
    }

    // setup checklist
    val numbers = m.settings.caregivers
    val needCaregiver = consents.smsAllowed && numbers.isEmpty()
    val unconfirmed = if (consents.smsAllowed) numbers.count { !consents.caregiverConfirmed(it) } else 0
    val needPin = m.settings.pinHash == null
    val testMode = consents.smsAllowed && !m.settings.realSms
    if (needCaregiver || unconfirmed > 0 || needPin || testMode) EpiCard {
        CardHeader(Icons.Rounded.Info, stringResource(R.string.setup_title))
        if (needCaregiver) CheckRow(stringResource(R.string.setup_caregiver)) { openSettings("patient") }
        if (unconfirmed > 0) CheckRow(stringResource(R.string.setup_unconfirmed, unconfirmed)) { openSettings("patient") }
        if (needPin) CheckRow(stringResource(R.string.setup_pin)) { openSettings("pin") }
        if (testMode) CheckRow(stringResource(R.string.setup_sms)) { openSettings("messages") }
    }

    DemoCard(m, demo)

    // recent messages
    val messages by produceState(emptyList<MessageRow>(), version) { value = withContext(Dispatchers.IO) { m.log.messages(3) } }
    if (messages.isNotEmpty()) EpiCard {
        CardHeader(Icons.Rounded.Send, stringResource(R.string.recent_messages))
        messages.forEach { MessageItem(it) }
    }
}

@Composable
private fun CheckRow(text: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(20.dp).clip(CircleShape).border(2.dp, C.Grey, CircleShape))
        Spacer(Modifier.width(12.dp))
        Text(text, color = C.Ink, modifier = Modifier.weight(1f))
        Icon(Icons.Rounded.KeyboardArrowRight, null, tint = C.Grey)
    }
}

@Composable
private fun StatusHero(running: Boolean, started: Boolean, activity: MainActivity) {
    val pulse = rememberInfiniteTransition(label = "pulse")
    val s by pulse.animateFloat(1f, 1.08f, infiniteRepeatable(tween(1400), RepeatMode.Reverse), label = "s")
    val bg by animateColorAsState(if (running) C.Teal else Color.White, label = "bg")
    val fg = if (running) Color.White else C.Ink
    Card(
        Modifier.fillMaxWidth(), shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = bg), elevation = CardDefaults.cardElevation(0.dp),
    ) {
        Box(Modifier.fillMaxWidth().background(
            if (running) Brush.linearGradient(listOf(C.Teal, C.TealDark)) else Brush.linearGradient(listOf(Color.White, Color.White)))) {
            Column(Modifier.padding(22.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(64.dp).scale(if (running) s else 1f).clip(CircleShape)
                        .background(if (running) Color.White.copy(alpha = 0.18f) else C.GreySoft),
                        contentAlignment = Alignment.Center) {
                        Icon(if (running) Icons.Rounded.CheckCircle else Icons.Rounded.Lock, null,
                            tint = if (running) Color.White else C.Grey, modifier = Modifier.size(36.dp))
                    }
                    Spacer(Modifier.width(16.dp))
                    Column(Modifier.weight(1f)) {
                        Text(stringResource(if (running) R.string.status_protected else R.string.monitoring_off),
                            style = MaterialTheme.typography.titleLarge, color = fg)
                        Text(stringResource(if (running) R.string.status_protected_text else R.string.status_off_text),
                            color = fg.copy(alpha = 0.8f), style = MaterialTheme.typography.bodyMedium)
                    }
                }
                if (running) Button(
                    onClick = { MonitoringService.stop(activity) }, modifier = Modifier.fillMaxWidth().height(50.dp),
                    shape = RoundedCornerShape(18.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Color.White.copy(alpha = 0.18f), contentColor = Color.White),
                ) { Text(stringResource(R.string.stop_monitoring), style = MaterialTheme.typography.labelLarge) }
                else PrimaryButton(stringResource(R.string.start_monitoring), Icons.Rounded.PlayArrow) { MonitoringService.start(activity) }
            }
        }
    }
}

@Composable
private fun DeviceCard(
    modifier: Modifier, icon: ImageVector, name: String, ok: Boolean,
    big: String?, unit: String, status: String, extra: String?,
) {
    Card(modifier.fillMaxHeight(), shape = MaterialTheme.shapes.large, colors = CardDefaults.cardColors(containerColor = Color.White),
        elevation = CardDefaults.cardElevation(0.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconBubble(icon, if (ok) C.Coral else C.Grey, if (ok) C.CoralSoft else C.GreySoft, 36.dp)
                Spacer(Modifier.weight(1f))
                Box(Modifier.size(10.dp).clip(CircleShape).background(if (ok) C.Mint else C.Grey))
            }
            Text(name, style = MaterialTheme.typography.titleMedium)
            if (big != null) Row(verticalAlignment = Alignment.Bottom) {
                Text(big, fontSize = 30.sp, fontWeight = FontWeight.Bold, color = C.Ink)
                Spacer(Modifier.width(4.dp))
                Text(unit, color = C.InkSoft, modifier = Modifier.padding(bottom = 5.dp))
            }
            Pill(status, if (ok) C.Mint else C.InkSoft, if (ok) C.MintSoft else C.GreySoft)
            if (extra != null) Text(extra, style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
        }
    }
}

@Composable
private fun DemoCard(m: PhoneMonitor, demo: org.epiprot.phone.DemoProgress?) {
    EpiCard(container = C.TealSoft) {
        CardHeader(Icons.Rounded.PlayArrow, stringResource(R.string.demo_title), bubble = Color.White)
        Text(stringResource(R.string.demo_text), color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        if (demo == null) PrimaryButton(stringResource(R.string.demo_start), Icons.Rounded.PlayArrow) { m.startDemo() }
        else {
            fun mmss(s: Double) = "%d:%02d".format((s / 60).toInt(), (s % 60).toInt())
            val frac = demo.window.toFloat() / demo.windows.coerceAtLeast(1)
            val onsetFrac = (demo.onsetS / (demo.windows * 5.0)).toFloat().coerceIn(0f, 1f)
            Box(Modifier.fillMaxWidth().height(14.dp)) {
                LinearProgressIndicator(progress = { frac }, modifier = Modifier.fillMaxWidth().height(10.dp)
                    .align(Alignment.Center).clip(RoundedCornerShape(50)), color = C.Teal, trackColor = Color.White)
                Box(Modifier.fillMaxWidth(onsetFrac).align(Alignment.CenterStart)) {
                    Box(Modifier.size(width = 3.dp, height = 14.dp).background(C.Coral).align(Alignment.CenterEnd))
                }
            }
            Text(stringResource(R.string.demo_progress2, mmss(demo.window * 5.0), mmss(demo.windows * 5.0), mmss(demo.onsetS)),
                color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
            SoftButton(stringResource(R.string.demo_stop)) { m.stopDemo() }
        }
    }
}

@Composable
private fun MessageItem(r: MessageRow) {
    val (status, color, bg) = when (r.status) {
        "sent" -> Triple(stringResource(R.string.sms_sent), C.Mint, C.MintSoft)
        "test" -> Triple(stringResource(R.string.sms_test), C.InkSoft, C.GreySoft)
        "no_number" -> Triple(stringResource(R.string.sms_no_number), C.Amber, C.AmberSoft)
        "no_consent" -> Triple(stringResource(R.string.sms_no_consent), C.InkSoft, C.GreySoft)
        "not_confirmed" -> Triple(stringResource(R.string.sms_not_confirmed), C.Amber, C.AmberSoft)
        else -> Triple(stringResource(R.string.sms_failed), C.Coral, C.CoralSoft)
    }
    Column(Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).background(C.Background).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("${time(r.timeMs)} · ${r.to}", style = MaterialTheme.typography.bodySmall, color = C.InkSoft, modifier = Modifier.weight(1f))
            Pill(status, color, bg)
        }
        Text(r.text, style = MaterialTheme.typography.bodyMedium, color = C.Ink)
    }
}

@Composable
private fun AlarmCard(m: PhoneMonitor, s: AlarmFlow.State, now: Long, demo: Boolean) {
    val pulse = rememberInfiniteTransition(label = "alarm")
    val a by pulse.animateFloat(0.25f, 0.45f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "a")
    Card(Modifier.fillMaxWidth(), shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = C.Coral), elevation = CardDefaults.cardElevation(0.dp)) {
        Box(Modifier.fillMaxWidth().background(Brush.linearGradient(listOf(C.Coral, C.CoralDark)))) {
            Column(Modifier.padding(22.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(64.dp).clip(CircleShape).background(Color.White.copy(alpha = a)), contentAlignment = Alignment.Center) {
                        if (s is AlarmFlow.State.Alarm) {
                            val left = ((s.alarmMs + 30_000 - now) / 1000).coerceIn(0, 30).toInt()
                            CircularProgressIndicator(progress = { left / 30f }, modifier = Modifier.size(56.dp),
                                color = Color.White, trackColor = Color.White.copy(alpha = 0.25f), strokeWidth = 4.dp)
                            Text("$left", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp)
                        } else Icon(Icons.Rounded.Notifications, null, tint = Color.White, modifier = Modifier.size(34.dp))
                    }
                    Spacer(Modifier.width(16.dp))
                    Column(Modifier.weight(1f)) {
                        if (demo) Pill(stringResource(R.string.demo_badge), C.CoralDark, Color.White)
                        Text(stringResource(R.string.alarm_title), color = Color.White, style = MaterialTheme.typography.titleLarge)
                    }
                }
                Text(when (s) {
                    is AlarmFlow.State.Alarm -> stringResource(R.string.alarm_pin, ((s.alarmMs + 30_000 - now) / 1000).coerceAtLeast(0).toInt())
                    is AlarmFlow.State.Active -> stringResource(if (s.emergencySent) R.string.alarm_emergency else R.string.alarm_active)
                    is AlarmFlow.State.Recovery -> stringResource(R.string.alarm_recovery, s.checkIns)
                    AlarmFlow.State.Idle -> ""
                }, color = Color.White, style = MaterialTheme.typography.bodyLarge)
                if (s !is AlarmFlow.State.Alarm) {
                    Text(stringResource(R.string.caregiver_here), color = Color.White.copy(alpha = 0.85f))
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button(onClick = { m.resolveByCaregiver(true) }, modifier = Modifier.weight(1f).height(50.dp),
                            shape = RoundedCornerShape(16.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = C.CoralDark)) {
                            Text(stringResource(R.string.was_seizure), fontWeight = FontWeight.SemiBold)
                        }
                        Button(onClick = { m.resolveByCaregiver(false) }, modifier = Modifier.weight(1f).height(50.dp),
                            shape = RoundedCornerShape(16.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = Color.White.copy(alpha = 0.2f), contentColor = Color.White)) {
                            Text(stringResource(R.string.no_seizure), fontWeight = FontWeight.SemiBold)
                        }
                    }
                }
            }
        }
    }
}

// ============================================================== events

@Composable
private fun Events(m: PhoneMonitor) {
    val version by m.logVersion.collectAsStateWithLifecycle()
    val events by produceState(emptyList<EventRow>(), version) { value = withContext(Dispatchers.IO) { m.log.events() } }
    val alerts by produceState(emptyList<SensorAlertRow>(), version) { value = withContext(Dispatchers.IO) { m.log.sensorAlerts() } }
    val messages by produceState(emptyList<MessageRow>(), version) { value = withContext(Dispatchers.IO) { m.log.messages() } }

    var reportOpen by rememberSaveable { mutableStateOf(false) }
    if (reportOpen) {
        androidx.activity.compose.BackHandler { reportOpen = false }
        ReportPage(m) { reportOpen = false }
        return
    }
    SectionTitle(stringResource(R.string.events_title), stringResource(R.string.events_sub))
    EpiCard(container = C.TealSoft) {
        CardHeader(Icons.Rounded.Send, stringResource(R.string.rep_card_title), bubble = Color.White)
        Text(stringResource(R.string.rep_card_text), color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        PrimaryButton(stringResource(R.string.rep_card_button), Icons.Rounded.Send) { reportOpen = true }
    }
    if (events.isEmpty()) EpiCard {
        Column(Modifier.fillMaxWidth().padding(vertical = 18.dp), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            IconBubble(Icons.Rounded.CheckCircle, C.Mint, C.MintSoft, 64.dp)
            Text(stringResource(R.string.no_events), style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
        }
    }
    events.forEach { EventCard(it) }

    if (alerts.isNotEmpty()) {
        SectionTitle(stringResource(R.string.sensor_alerts))
        EpiCard {
            alerts.forEach {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconBubble(Icons.Rounded.Warning, if (it.fixedMs != null) C.Mint else C.Amber,
                        if (it.fixedMs != null) C.MintSoft else C.AmberSoft, 34.dp)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text("${it.device}: ${it.code.replace('_', ' ').lowercase()}", style = MaterialTheme.typography.bodyLarge)
                        Text(time(it.warnedMs) + (it.fixedMs?.let { f -> " → " + time(f) } ?: ""),
                            style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
                    }
                    if (it.demo) Pill(stringResource(R.string.demo_badge), C.TealDark, C.TealSoft)
                }
            }
        }
    }
    if (messages.isNotEmpty()) {
        SectionTitle(stringResource(R.string.messages))
        EpiCard { messages.forEach { MessageItem(it) } }
    }
}

@Composable
private fun EventCard(e: EventRow) {
    var open by remember { mutableStateOf(false) }
    // same classification as the doctor report
    val (label, icon, color, bg) = when (org.epiprot.phone.report.ReportData.kindOf(e)) {
        org.epiprot.phone.report.ReportKind.FALSE_ALARM -> Quad(stringResource(R.string.kind_false_alarm), Icons.Rounded.CheckCircle, C.Teal, C.TealSoft)
        org.epiprot.phone.report.ReportKind.SEIZURE -> Quad(stringResource(R.string.kind_seizure), Icons.Rounded.Notifications, C.Coral, C.CoralSoft)
        org.epiprot.phone.report.ReportKind.UNCONFIRMED -> Quad(stringResource(R.string.kind_unconfirmed), Icons.Rounded.Warning, C.Amber, C.AmberSoft)
    }
    EpiCard(Modifier.clickable { open = !open }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconBubble(icon, color, bg, 44.dp)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(label, style = MaterialTheme.typography.titleMedium)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(dateTime(e.alarmMs), style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
                    if (e.demo) { Spacer(Modifier.width(8.dp)); Pill(stringResource(R.string.demo_badge), C.TealDark, C.TealSoft) }
                }
            }
            Icon(if (open) Icons.Rounded.KeyboardArrowUp else Icons.Rounded.KeyboardArrowDown, null, tint = C.Grey)
        }
        AnimatedVisibility(open) {
            Column(Modifier.padding(start = 20.dp, top = 4.dp)) {
                e.steps.forEachIndexed { i, st ->
                    Row {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Box(Modifier.size(10.dp).clip(CircleShape).background(color))
                            if (i < e.steps.lastIndex) Box(Modifier.width(2.dp).height(36.dp).background(C.Line))
                        }
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.padding(bottom = 8.dp)) {
                            Text("${time(st.timeMs)} · ${st.step}", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                            Text(st.detail, style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
                        }
                    }
                }
            }
        }
        if (!open && e.steps.isNotEmpty())
            Text(stringResource(R.string.show_steps, e.steps.size), style = MaterialTheme.typography.bodySmall, color = C.TealDark)
    }
}

private data class Quad<A, B, C2, D>(val a: A, val b: B, val c: C2, val d: D)

@Composable
private fun LockedScreen(activity: MainActivity) {
    LaunchedEffect(Unit) { activity.unlock() }
    EpiCard {
        Column(Modifier.fillMaxWidth().padding(vertical = 24.dp), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            IconBubble(Icons.Rounded.Lock, C.TealDark, C.TealSoft, 72.dp)
            Text(stringResource(R.string.lock_title), style = MaterialTheme.typography.titleLarge)
            Text(stringResource(R.string.lock_why), color = C.InkSoft, textAlign = TextAlign.Center)
            PrimaryButton(stringResource(R.string.lock_unlock)) { activity.unlock() }
        }
    }
}

// ============================================================== settings (short menu + sub-pages)

private fun parentOf(route: String?): String? = when {
    route == null -> null
    route.startsWith("consent:") || route in setOf("notice", "limits", "history", "child") -> "privacy"
    else -> null
}

@Composable
private fun subTitle(route: String): String = when {
    route == "patient" -> stringResource(R.string.set_patient)
    route == "pin" -> stringResource(R.string.section_watch_pin)
    route == "messages" -> stringResource(R.string.set_messages)
    route == "doctor" -> stringResource(R.string.section_doctor)
    route == "permissions" -> stringResource(R.string.set_permissions)
    route == "privacy" -> stringResource(R.string.privacy_title)
    route == "notice" -> stringResource(R.string.privacy_notice)
    route == "limits" -> stringResource(R.string.privacy_limits)
    route == "history" -> stringResource(R.string.privacy_history)
    route == "child" -> stringResource(R.string.privacy_child_page)
    else -> stringResource(R.string.privacy_consents)
}

@Composable
private fun SubPageHeader(title: String, back: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        androidx.compose.material3.IconButton(onClick = back) {
            Icon(Icons.Rounded.ArrowBack, stringResource(R.string.back), tint = C.Ink)
        }
        Text(title, style = MaterialTheme.typography.titleLarge)
    }
}

@Composable
private fun SettingsMenu(m: PhoneMonitor, activity: MainActivity, open: (String) -> Unit) {
    val c by m.consents.collectAsStateWithLifecycle()
    val s = m.settings
    SectionTitle(stringResource(R.string.tab_settings))
    MenuCard {
        val numbers = s.caregivers
        val waiting = numbers.count { !c.caregiverConfirmed(it) }
        MenuRow(Icons.Rounded.Person, stringResource(R.string.set_patient),
            listOfNotNull(s.patientName.ifBlank { null }, stringResource(R.string.set_caregivers_n, numbers.size),
                if (waiting > 0) stringResource(R.string.set_waiting_n, waiting) else null).joinToString(" · ")) { open("patient") }
        HorizontalDivider(color = C.Line)
        MenuRow(Icons.Rounded.Lock, stringResource(R.string.section_watch_pin),
            stringResource(if (s.pinHash != null) R.string.pin_is_set_short else R.string.pin_not_set_short)) { open("pin") }
        HorizontalDivider(color = C.Line)
        MenuRow(Icons.Rounded.Send, stringResource(R.string.set_messages), stringResource(when {
            !c.smsAllowed -> R.string.set_sms_no_consent
            s.realSms -> R.string.set_sms_real
            else -> R.string.set_sms_test
        })) { open("messages") }
        HorizontalDivider(color = C.Line)
        MenuRow(Icons.Rounded.Email, stringResource(R.string.section_doctor), s.doctorEmail.ifBlank { stringResource(R.string.set_not_set) }) { open("doctor") }
    }
    MenuCard {
        val on = org.epiprot.phone.privacy.Consent.entries.count { c.has(it) }
        MenuRow(Icons.Rounded.Lock, stringResource(R.string.privacy_title),
            stringResource(R.string.set_privacy_sub, on, org.epiprot.phone.privacy.Consent.entries.size),
            tint = C.Mint, bubble = C.MintSoft) { open("privacy") }
        HorizontalDivider(color = C.Line)
        MenuRow(Icons.Rounded.CheckCircle, stringResource(R.string.set_permissions), stringResource(R.string.set_permissions_sub)) { open("permissions") }
        HorizontalDivider(color = C.Line)
        var lock by remember { mutableStateOf(s.appLock) }
        Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            IconBubble(Icons.Rounded.Lock, C.TealDark, C.TealSoft, 40.dp)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.lock_setting), style = MaterialTheme.typography.titleMedium)
                Text(stringResource(if (activity.deviceSecure) R.string.lock_setting_sub else R.string.lock_no_screen_lock),
                    style = MaterialTheme.typography.bodySmall, color = if (activity.deviceSecure) C.InkSoft else C.Amber)
            }
            Switch(lock && activity.deviceSecure, { lock = it; s.appLock = it }, enabled = activity.deviceSecure,
                colors = SwitchDefaults.colors(checkedTrackColor = C.Teal))
        }
    }
}

@Composable
private fun PatientCaregiversPage(m: PhoneMonitor, open: (String) -> Unit) {
    val c by m.consents.collectAsStateWithLifecycle()
    val s = m.settings
    var name by remember { mutableStateOf(s.patientName) }
    val numbers = remember { List(3) { i -> mutableStateOf(s.caregivers.getOrElse(i) { "" }) } }
    val agreed = remember { List(3) { i -> mutableStateOf(s.caregivers.getOrNull(i)?.let(c::caregiverConfirmed) ?: false) } }
    var note by remember { mutableStateOf("") }
    val savedText = stringResource(R.string.saved)

    EpiCard {
        CardHeader(Icons.Rounded.Person, stringResource(R.string.section_patient))
        Field(name, { name = it }, stringResource(R.string.patient_name))
    }
    if (!c.smsAllowed) EpiCard(container = C.AmberSoft) {
        CardHeader(Icons.Rounded.Warning, stringResource(R.string.set_sms_consent_off), tint = C.Amber, bubble = Color.White)
        Text(stringResource(R.string.set_sms_consent_off_text), color = C.Ink)
        TextButton(onClick = { open("consent:caregiver_sms") }) { Text(stringResource(R.string.home_review_consent), color = C.TealDark) }
    }
    EpiCard {
        CardHeader(Icons.Rounded.Call, stringResource(R.string.section_caregivers))
        Text(stringResource(R.string.caregivers_note), color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        numbers.forEachIndexed { i, st ->
            Field(st.value, { st.value = it; agreed[i].value = false }, stringResource(R.string.caregiver_n, i + 1), KeyboardType.Phone)
            if (st.value.isNotBlank()) Row(Modifier.fillMaxWidth().clickable { agreed[i].value = !agreed[i].value },
                verticalAlignment = Alignment.CenterVertically) {
                androidx.compose.material3.Checkbox(agreed[i].value, { agreed[i].value = it },
                    colors = androidx.compose.material3.CheckboxDefaults.colors(checkedColor = C.Teal))
                Text(stringResource(R.string.caregiver_agreed), style = MaterialTheme.typography.bodyMedium, color = C.Ink)
            }
        }
        Text(stringResource(R.string.caregiver_agreed_note), style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
    }
    PrimaryButton(stringResource(R.string.save)) {
        s.patientName = name
        s.caregivers = numbers.map { it.value }
        val newly = numbers.filterIndexed { i, st -> st.value.isNotBlank() && agreed[i].value && !c.caregiverConfirmed(st.value) }.map { it.value }
        numbers.forEachIndexed { i, st -> if (st.value.isNotBlank()) m.consentStore.setCaregiverConfirmed(st.value, agreed[i].value) }
        m.consentsChanged()
        m.sendCaregiverIntro(newly)
        m.consentsChanged()
        note = savedText
    }
    if (note.isNotEmpty()) SavedNote(note)
}

@Composable
private fun PinPage(m: PhoneMonitor) {
    var pin by remember { mutableStateOf("") }
    var pinNote by remember { mutableStateOf("") }
    var pinSet by remember { mutableStateOf(m.settings.pinHash != null) }
    EpiCard {
        CardHeader(Icons.Rounded.Lock, stringResource(R.string.section_watch_pin), trailing = {
            Pill(stringResource(if (pinSet) R.string.pin_is_set_short else R.string.pin_not_set_short),
                if (pinSet) C.Mint else C.Amber, if (pinSet) C.MintSoft else C.AmberSoft)
        })
        Text(stringResource(R.string.pin_note), color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        OutlinedTextField(pin, { if (it.length <= 4 && it.all(Char::isDigit)) pin = it }, label = { Text(stringResource(R.string.pin)) },
            visualTransformation = PasswordVisualTransformation(), shape = RoundedCornerShape(16.dp),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth())
        val okText = stringResource(R.string.pin_ok); val badText = stringResource(R.string.pin_bad)
        PrimaryButton(stringResource(R.string.pin_set)) {
            if (pin.length == 4) { m.setPin(pin); pin = ""; pinSet = true; pinNote = okText } else pinNote = badText
        }
        if (pinNote.isNotEmpty()) Text(pinNote, color = if (pinSet) C.Mint else C.Coral)
    }
}

@Composable
private fun MessagesPage(m: PhoneMonitor, open: (String) -> Unit) {
    val c by m.consents.collectAsStateWithLifecycle()
    var realSms by remember { mutableStateOf(m.settings.realSms) }
    EpiCard {
        CardHeader(Icons.Rounded.Send, stringResource(R.string.set_messages))
        if (!c.smsAllowed) {
            Text(stringResource(R.string.set_sms_consent_off_text), color = C.Ink)
            TextButton(onClick = { open("consent:caregiver_sms") }) { Text(stringResource(R.string.home_review_consent), color = C.TealDark) }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.real_sms), style = MaterialTheme.typography.titleMedium)
                Text(stringResource(R.string.real_sms_note), style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
            }
            Spacer(Modifier.width(10.dp))
            Switch(realSms && c.smsAllowed, { realSms = it; m.settings.realSms = it }, enabled = c.smsAllowed,
                colors = SwitchDefaults.colors(checkedTrackColor = C.Teal))
        }
        Text(stringResource(R.string.set_location_line, stringResource(if (c.locationAllowed) R.string.consent_on else R.string.consent_off)),
            color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun DoctorPage(m: PhoneMonitor) {
    var doctor by remember { mutableStateOf(m.settings.doctorEmail) }
    var note by remember { mutableStateOf("") }
    val savedText = stringResource(R.string.saved)
    EpiCard {
        CardHeader(Icons.Rounded.Email, stringResource(R.string.section_doctor))
        Text(stringResource(R.string.doctor_note), color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        Field(doctor, { doctor = it }, stringResource(R.string.doctor_email), KeyboardType.Email)
    }
    PrimaryButton(stringResource(R.string.save)) { m.settings.doctorEmail = doctor; note = savedText }
    if (note.isNotEmpty()) SavedNote(note)
}

@Composable
private fun PermissionsPage(activity: MainActivity) {
    EpiCard {
        Text(stringResource(R.string.set_permissions_text), color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        val pv by activity.permVersion
        activity.permissionGroups.forEach { (label, perms) ->
            val ok = pv >= 0 && perms.any(activity::granted)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(if (ok) Icons.Rounded.CheckCircle else Icons.Rounded.Warning, null, tint = if (ok) C.Mint else C.Amber,
                    modifier = Modifier.size(22.dp))
                Spacer(Modifier.width(10.dp))
                Text(stringResource(label), color = C.Ink, modifier = Modifier.weight(1f))
                Text(stringResource(if (ok) R.string.perm_on else R.string.perm_off), color = if (ok) C.Mint else C.Amber,
                    style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold)
            }
        }
        SoftButton(stringResource(R.string.permissions)) { activity.requestPermissions(fromButton = true) }
    }
}

@Composable
private fun SavedNote(note: String) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 4.dp)) {
        Icon(Icons.Rounded.CheckCircle, null, tint = C.Mint); Spacer(Modifier.width(6.dp)); Text(note, color = C.Mint)
    }
}

@Composable
private fun Field(value: String, onChange: (String) -> Unit, label: String, type: KeyboardType = KeyboardType.Text) {
    OutlinedTextField(value, onChange, label = { Text(label) }, singleLine = true, shape = RoundedCornerShape(16.dp),
        keyboardOptions = KeyboardOptions(keyboardType = type), modifier = Modifier.fillMaxWidth())
}


package org.epiprot.phone.ui

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
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
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.service.MonitoringService
import java.text.DateFormat
import java.util.Date

private val Red = Color(0xFFB3261E)
private val Amber = Color(0xFFB25E09)
private val Green = Color(0xFF2E7D32)

class MainActivity : ComponentActivity() {
    private val askPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {}

    fun requestPermissions() {
        val wanted = buildList {
            add(Manifest.permission.ACCESS_FINE_LOCATION); add(Manifest.permission.ACCESS_COARSE_LOCATION)
            add(Manifest.permission.SEND_SMS)
            if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
            if (Build.VERSION.SDK_INT >= 31) add(Manifest.permission.BLUETOOTH_CONNECT)
        }
        askPermissions.launch(wanted.toTypedArray())
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val monitor = EpiProtPhoneApp.monitor(this)
        if (savedInstanceState == null) requestPermissions()
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF0B5F7A))) {
                App(monitor, this)
            }
        }
    }
}

@Composable
private fun App(m: PhoneMonitor, activity: MainActivity) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    Scaffold(bottomBar = {
        NavigationBar {
            listOf(R.string.tab_home, R.string.tab_events, R.string.tab_settings).forEachIndexed { i, label ->
                NavigationBarItem(selected = tab == i, onClick = { tab = i }, icon = {},
                    label = { Text(stringResource(label), fontSize = 15.sp) })
            }
        }
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            when (tab) {
                0 -> Home(m, activity)
                1 -> Events(m)
                else -> SettingsScreen(m, activity)
            }
        }
    }
}

private fun time(ms: Long?): String = ms?.let { DateFormat.getTimeInstance(DateFormat.MEDIUM).format(Date(it)) } ?: "–"

@Composable
private fun Home(m: PhoneMonitor, activity: MainActivity) {
    val running by m.running.collectAsStateWithLifecycle()
    val st by m.status.collectAsStateWithLifecycle()
    val watch by m.watch.collectAsStateWithLifecycle()
    val demo by m.demo.collectAsStateWithLifecycle()
    val version by m.logVersion.collectAsStateWithLifecycle()
    var now by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(1_000) } }

    if (st.flowState != AlarmFlow.State.Idle) AlarmCard(m, st.flowState, now, st.demo)

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(if (running) R.string.monitoring_on else R.string.monitoring_off),
                    fontWeight = FontWeight.Bold, fontSize = 20.sp, modifier = Modifier.weight(1f),
                    color = if (running) Green else Color.Unspecified)
                if (running) OutlinedButton(onClick = { MonitoringService.stop(activity) }) { Text(stringResource(R.string.stop_monitoring)) }
                else Button(onClick = { MonitoringService.start(activity) }) { Text(stringResource(R.string.start_monitoring)) }
            }
            val watchOk = now - watch.lastDataMs < 10_000
            StatusLine(stringResource(R.string.watch), if (watchOk) buildString {
                append(stringResource(R.string.receiving))
                if (watch.heartRate.isFinite()) append(" · ").append(stringResource(R.string.heart_rate_value, watch.heartRate.toInt()))
                watch.batteryPct?.let { append(" · $it%") }
            } else stringResource(R.string.not_connected), watchOk)
            StatusLine(stringResource(R.string.headband), stringResource(R.string.headband_none), false)
            val q = st.quality
            val mode = when {
                st.windows == 0L -> stringResource(R.string.detection_waiting)
                q["brain"] != HealthMonitor.Quality.OK -> stringResource(R.string.detection_limited)
                st.fallback -> stringResource(R.string.detection_backup)
                else -> stringResource(R.string.detection_full)
            }
            StatusLine(stringResource(R.string.detection), mode, st.windows > 0 && q["brain"] == HealthMonitor.Quality.OK)
            if (m.settings.caregivers.isEmpty() || m.settings.pinHash == null)
                Text(stringResource(R.string.setup_missing), color = Amber)
            if (!m.settings.realSms) Text(stringResource(R.string.test_mode_note), fontSize = 13.sp, color = Color.Gray)
        }
    }

    if (st.openWarnings.isNotEmpty()) Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(stringResource(R.string.open_problems), fontWeight = FontWeight.Bold)
            st.openWarnings.forEach { Text("• ${it.code} (${it.impact}) ${time(it.warnedMs)}") }
        }
    }

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.demo_title), fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text(stringResource(R.string.demo_text), fontSize = 14.sp)
            val d = demo
            if (d == null) Button(onClick = { m.startDemo() }) { Text(stringResource(R.string.demo_start)) }
            else {
                fun mmss(s: Double) = "%d:%02d".format((s / 60).toInt(), (s % 60).toInt())
                Text(stringResource(R.string.demo_progress, mmss(d.window * 5.0), mmss(d.windows * 5.0), mmss(d.onsetS),
                    "%.4f".format(d.score)), fontSize = 14.sp)
                OutlinedButton(onClick = { m.stopDemo() }) { Text(stringResource(R.string.demo_stop)) }
            }
        }
    }

    val messages by produceState(emptyList<org.epiprot.phone.data.MessageRow>(), version) {
        value = withContext(Dispatchers.IO) { m.log.messages(5) }
    }
    if (messages.isNotEmpty()) Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(stringResource(R.string.messages), fontWeight = FontWeight.Bold)
            messages.forEach { MessageItem(it) }
        }
    }
}

@Composable
private fun StatusLine(label: String, value: String, ok: Boolean) {
    Row {
        Text("$label: ", fontWeight = FontWeight.SemiBold)
        Text(value, color = if (ok) Green else Color.DarkGray)
    }
}

@Composable
private fun MessageItem(r: org.epiprot.phone.data.MessageRow) {
    val status = when (r.status) {
        "sent" -> stringResource(R.string.sms_sent)
        "test" -> stringResource(R.string.sms_test)
        "no_number" -> stringResource(R.string.sms_no_number)
        else -> stringResource(R.string.sms_failed)
    }
    Column {
        Text("${time(r.timeMs)} → ${r.to} · $status", fontSize = 12.sp, color = Color.Gray)
        Text(r.text, fontSize = 14.sp)
    }
}

@Composable
private fun AlarmCard(m: PhoneMonitor, s: AlarmFlow.State, now: Long, demo: Boolean) {
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Red, contentColor = Color.White)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.alarm_title) + if (demo) " · " + stringResource(R.string.demo_badge) else "",
                fontWeight = FontWeight.Bold, fontSize = 24.sp)
            Text(when (s) {
                is AlarmFlow.State.Alarm -> stringResource(R.string.alarm_pin, ((s.alarmMs + 30_000 - now) / 1000).coerceAtLeast(0).toInt())
                is AlarmFlow.State.Active -> stringResource(if (s.emergencySent) R.string.alarm_emergency else R.string.alarm_active)
                is AlarmFlow.State.Recovery -> stringResource(R.string.alarm_recovery, s.checkIns)
                AlarmFlow.State.Idle -> ""
            }, fontSize = 17.sp)
            if (s !is AlarmFlow.State.Alarm) {
                Text(stringResource(R.string.caregiver_here))
                Row {
                    Button(onClick = { m.resolveByCaregiver(true) },
                        colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = Red)) {
                        Text(stringResource(R.string.was_seizure))
                    }
                    Spacer(Modifier.width(8.dp))
                    Button(onClick = { m.resolveByCaregiver(false) },
                        colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = Red)) {
                        Text(stringResource(R.string.no_seizure))
                    }
                }
            }
        }
    }
}

@Composable
private fun Events(m: PhoneMonitor) {
    val version by m.logVersion.collectAsStateWithLifecycle()
    val events by produceState(emptyList<EventRow>(), version) { value = withContext(Dispatchers.IO) { m.log.events() } }
    val alerts by produceState(emptyList<org.epiprot.phone.data.SensorAlertRow>(), version) {
        value = withContext(Dispatchers.IO) { m.log.sensorAlerts() }
    }
    val messages by produceState(emptyList<org.epiprot.phone.data.MessageRow>(), version) {
        value = withContext(Dispatchers.IO) { m.log.messages() }
    }
    if (events.isEmpty()) Text(stringResource(R.string.no_events))
    events.forEach { e ->
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text((if (e.demo) "[DEMO] " else "") + stringResource(when (e.kind) {
                    "false_alarm" -> R.string.kind_false_alarm
                    "seizure" -> R.string.kind_seizure
                    else -> R.string.kind_unconfirmed
                }) + " · " + time(e.alarmMs), fontWeight = FontWeight.Bold)
                e.steps.forEach { Text("${time(it.timeMs)}  ${it.step} – ${it.detail}", fontSize = 13.sp) }
            }
        }
    }
    if (alerts.isNotEmpty()) {
        HorizontalDivider()
        Text(stringResource(R.string.sensor_alerts), fontWeight = FontWeight.Bold)
        alerts.forEach { Text((if (it.demo) "[DEMO] " else "") + "${time(it.warnedMs)}  ${it.device}: ${it.code} (${it.impact})" +
            (it.fixedMs?.let { f -> " → ${time(f)}" } ?: ""), fontSize = 13.sp) }
    }
    if (messages.isNotEmpty()) {
        HorizontalDivider()
        Text(stringResource(R.string.messages), fontWeight = FontWeight.Bold)
        messages.forEach { MessageItem(it) }
    }
}

@Composable
private fun SettingsScreen(m: PhoneMonitor, activity: MainActivity) {
    val s = m.settings
    var name by remember { mutableStateOf(s.patientName) }
    val numbers = remember { List(3) { i -> mutableStateOf(s.caregivers.getOrElse(i) { "" }) } }
    var doctor by remember { mutableStateOf(s.doctorEmail) }
    var realSms by remember { mutableStateOf(s.realSms) }
    var pin by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    var pinSet by remember { mutableStateOf(s.pinHash != null) }

    OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.patient_name)) }, modifier = Modifier.fillMaxWidth())
    numbers.forEachIndexed { i, st ->
        OutlinedTextField(st.value, { st.value = it }, label = { Text(stringResource(R.string.caregiver_n, i + 1)) },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone), modifier = Modifier.fillMaxWidth())
    }
    OutlinedTextField(doctor, { doctor = it }, label = { Text(stringResource(R.string.doctor_email)) },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), modifier = Modifier.fillMaxWidth())
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(stringResource(R.string.real_sms), modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
        Switch(realSms, { realSms = it })
    }
    Text(stringResource(R.string.real_sms_note), fontSize = 13.sp, color = Color.Gray)
    val savedText = stringResource(R.string.saved)
    Button(onClick = {
        s.patientName = name; s.caregivers = numbers.map { it.value }; s.doctorEmail = doctor; s.realSms = realSms
        note = savedText
    }) { Text(stringResource(R.string.save)) }

    HorizontalDivider()
    Text(stringResource(if (pinSet) R.string.pin_is_set else R.string.pin_not_set))
    OutlinedTextField(pin, { if (it.length <= 4 && it.all(Char::isDigit)) pin = it }, label = { Text(stringResource(R.string.pin)) },
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth())
    val okText = stringResource(R.string.pin_ok); val badText = stringResource(R.string.pin_bad)
    Button(onClick = {
        if (pin.length == 4) { m.setPin(pin); pin = ""; pinSet = true; note = okText } else note = badText
    }) { Text(stringResource(R.string.pin_set)) }
    if (note.isNotEmpty()) Text(note, color = Green)

    HorizontalDivider()
    OutlinedButton(onClick = { activity.requestPermissions() }) { Text(stringResource(R.string.permissions)) }
    Text(stringResource(R.string.privacy_note), fontSize = 13.sp, color = Color.Gray)
}

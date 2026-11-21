package org.epiprot.watch.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ChipDefaults
import androidx.wear.compose.material.ListHeader
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.TimeText
import androidx.wear.compose.material.ToggleChip
import androidx.wear.compose.material.ToggleChipDefaults
import kotlinx.coroutines.delay
import org.epiprot.watch.R
import org.epiprot.watch.WatchController
import org.epiprot.watch.core.Impact
import org.epiprot.watch.core.InfoKind
import org.epiprot.watch.core.PinVerifier
import org.epiprot.watch.core.Screen
import org.epiprot.watch.core.WarningCode

private val Red = Color(0xFFB3261E)
private val Amber = Color(0xFF8A5A00)
private val Orange = Color(0xFFB65A12)
private val Teal = Color(0xFF0F6F8F)
private val Green = Color(0xFF2E7D32)

@Composable
fun EpiProtWatchApp(controller: WatchController, sensorPermission: Boolean, onRequestPermission: () -> Unit) {
    val screen by controller.screen.collectAsStateWithLifecycle()
    val sos by controller.sos.collectAsStateWithLifecycle()
    MaterialTheme {
        // the help call is shown over the home screen, never over an alarm or a check-in
        if (sos != null && screen is Screen.Home) { SosScreen(controller, sos!!); return@MaterialTheme }
        val coming by controller.coming.collectAsStateWithLifecycle()
        if (coming != null && screen is Screen.Home) {
            MessageScreen(Green, comingTitle(coming!!), stringResource(R.string.coming_text),
                button = stringResource(R.string.ok), onButton = controller::dismissComing)
            return@MaterialTheme
        }
        val shower by controller.shower.collectAsStateWithLifecycle()
        if (shower != null && screen is Screen.Home) { ShowerScreen(controller, shower!!); return@MaterialTheme }
        when (val s = screen) {
            is Screen.Home -> HomeScreen(controller, sensorPermission, onRequestPermission)
            is Screen.Alarm -> AlarmScreen(s, controller::enterPin)
            is Screen.AlarmActive -> MessageScreen(Red, stringResource(R.string.alarm_active_title),
                coming?.let { comingTitle(it) } ?: stringResource(R.string.alarm_active_text), button = stringResource(R.string.home_button),
                onButton = controller::goHome)
            is Screen.CheckIn -> PinScreen(
                background = Amber,
                title = stringResource(R.string.checkin_title),
                subtitle = stringResource(R.string.checkin_text),
                wrongAttempts = s.wrongAttempts,
                onPin = controller::enterPin,
            )
            is Screen.Warning -> MessageScreen(Orange, warningText(s.code, s.detail), impactText(s.impact),
                button = stringResource(R.string.ok), onButton = controller::dismiss)
            is Screen.NightSummary -> MessageScreen(Teal,
                pluralTitle(s.items.size),
                s.items.map { (c, d) -> warningText(c, d) }.joinToString("\n\n"),
                button = stringResource(R.string.ok), onButton = controller::dismiss)
            is Screen.Info -> MessageScreen(
                if (s.kind == InfoKind.FALSE_ALARM_SENT || s.kind == InfoKind.ALARM_ENDED) Teal else Green,
                infoText(s.kind), null, button = stringResource(R.string.ok), onButton = controller::dismiss,
            )
        }
    }
}

// ------------------------------------------------------------------ call for help

@Composable
private fun SosScreen(controller: WatchController, sos: WatchController.Sos) {
    when (sos) {
        WatchController.Sos.COUNTDOWN -> {
            var left by remember { mutableStateOf(5) }
            androidx.compose.runtime.LaunchedEffect(controller.sosAtMs) {
                while (true) {
                    left = ((controller.sosAtMs - System.currentTimeMillis() + 999) / 1000).toInt().coerceAtLeast(0)
                    kotlinx.coroutines.delay(200)
                }
            }
            MessageScreen(Red, stringResource(R.string.sos_countdown_title, left), stringResource(R.string.sos_countdown_text),
                button = stringResource(R.string.sos_cancel), onButton = controller::sosCancel)
        }
        WatchController.Sos.SENT -> MessageScreen(Green, stringResource(R.string.sos_sent_title), stringResource(R.string.sos_sent_text),
            button = stringResource(R.string.ok), onButton = controller::sosClose)
        WatchController.Sos.QUEUED -> MessageScreen(Orange, stringResource(R.string.sos_queued_title), stringResource(R.string.sos_queued_text),
            button = stringResource(R.string.ok), onButton = controller::sosClose)
    }
}

@Composable
private fun comingTitle(name: String) =
    if (name.isBlank()) stringResource(R.string.coming_unknown) else stringResource(R.string.coming_title, name)

// ------------------------------------------------------------------ shower mode

@Composable
private fun ShowerScreen(controller: WatchController, state: WatchController.Shower) {
    when (state) {
        WatchController.Shower.CHOOSE -> {
            val listState = rememberScalingLazyListState()
            Scaffold(timeText = { TimeText() }) {
                ScalingLazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
                    item { ListHeader { Text(stringResource(R.string.shower_choose), fontWeight = FontWeight.Bold) } }
                    for (min in listOf(10, 15, 20, 30)) item {
                        Chip(onClick = { controller.showerStart(min) }, label = { Text(stringResource(R.string.shower_minutes, min)) },
                            colors = ChipDefaults.primaryChipColors(), modifier = Modifier.fillMaxWidth())
                    }
                    item { Small(stringResource(R.string.shower_choose_note)) }
                    item { DemoChip(stringResource(R.string.sos_cancel), controller::showerCancelChoose) }
                }
            }
        }
        WatchController.Shower.RUNNING -> {
            var left by remember { mutableStateOf("") }
            androidx.compose.runtime.LaunchedEffect(controller.showerEndsMs) {
                while (true) {
                    val s = ((controller.showerEndsMs - System.currentTimeMillis()) / 1000).coerceAtLeast(0)
                    left = "%d:%02d".format(s / 60, s % 60)
                    kotlinx.coroutines.delay(500)
                }
            }
            MessageScreen(Teal, stringResource(R.string.shower_running, left), stringResource(R.string.shower_running_text),
                button = stringResource(R.string.shower_out), onButton = controller::showerEnd)
        }
        WatchController.Shower.ASKING -> MessageScreen(Amber, stringResource(R.string.shower_ask_title),
            stringResource(R.string.shower_ask_text), button = stringResource(R.string.shower_out), onButton = controller::showerEnd)
        WatchController.Shower.NO_ANSWER -> MessageScreen(Red, stringResource(R.string.shower_alerted_title),
            stringResource(R.string.shower_alerted_text), button = stringResource(R.string.shower_ok_now), onButton = controller::showerEnd)
    }
}

// ------------------------------------------------------------------ home

@Composable
private fun HomeScreen(controller: WatchController, sensorPermission: Boolean, onRequestPermission: () -> Unit) {
    val phone by controller.phoneConnected.collectAsStateWithLifecycle()
    val hr by controller.heartRate.collectAsStateWithLifecycle()
    val simulated by controller.simulated.collectAsStateWithLifecycle()
    val demoPin by controller.demoPin.collectAsStateWithLifecycle()
    val warnings by controller.warnings.collectAsStateWithLifecycle()
    val details by controller.warningDetails.collectAsStateWithLifecycle()
    val night by controller.night.collectAsStateWithLifecycle()
    val activeAlarm by controller.activeAlarm.collectAsStateWithLifecycle()
    val allowed by controller.monitoringAllowed.collectAsStateWithLifecycle()
    var shaking by remember { mutableStateOf(false) }
    val listState = rememberScalingLazyListState()

    Scaffold(timeText = { TimeText() }) {
        ScalingLazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
            item { ListHeader { Text("EpiProt", fontWeight = FontWeight.Bold) } }
            if (activeAlarm != null) item {
                Chip(
                    onClick = controller::reopenAlarm,
                    label = { Text(stringResource(R.string.alarm_active_title), fontWeight = FontWeight.Bold) },
                    secondaryLabel = { Text(stringResource(R.string.home_alarm_running), maxLines = 2) },
                    colors = ChipDefaults.chipColors(backgroundColor = Red),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                Chip(
                    onClick = controller::sosStart,
                    label = { Text(stringResource(R.string.sos_button), fontWeight = FontWeight.Bold) },
                    secondaryLabel = { Text(stringResource(R.string.sos_button_sub), maxLines = 2, fontSize = 11.sp) },
                    colors = ChipDefaults.chipColors(backgroundColor = Red),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                Chip(
                    onClick = controller::showerChoose,
                    label = { Text(stringResource(R.string.shower_button)) },
                    secondaryLabel = { Text(stringResource(R.string.shower_button_sub), maxLines = 2, fontSize = 11.sp) },
                    colors = ChipDefaults.secondaryChipColors(),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                Text(
                    stringResource(if (phone) R.string.home_phone_ok else R.string.home_phone_missing),
                    color = if (phone) Color(0xFF81C995) else Color(0xFFF2B8B5), fontSize = 13.sp,
                )
            }
            if (!allowed) item {
                Chip(
                    onClick = {},
                    label = { Text(stringResource(R.string.home_no_consent), fontWeight = FontWeight.Bold) },
                    secondaryLabel = { Text(stringResource(R.string.home_no_consent_text), maxLines = 3) },
                    colors = ChipDefaults.chipColors(backgroundColor = Amber),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            if (allowed) item {
                val value = if (hr.isNaN()) stringResource(R.string.home_hr_none) else "${hr.toInt()} bpm"
                Text(stringResource(R.string.home_hr, value), fontSize = 13.sp)
            }
            if (simulated) item { Small(stringResource(R.string.home_simulated)) }
            if (!sensorPermission) item {
                Chip(
                    onClick = onRequestPermission,
                    label = { Text(stringResource(R.string.permission_button)) },
                    secondaryLabel = { Text(stringResource(R.string.permission_needed), maxLines = 3) },
                    colors = ChipDefaults.primaryChipColors(),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            if (warnings.isNotEmpty()) {
                item { ListHeader { Text(stringResource(R.string.home_active_warnings)) } }
                for ((code, _) in warnings) item {
                    Chip(
                        onClick = { controller.openWarning(code) },
                        label = { Text(warningText(code, details[code] ?: ""), maxLines = 3, fontSize = 12.sp) },
                        colors = ChipDefaults.chipColors(backgroundColor = Orange),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
            item {
                ToggleChip(
                    checked = night,
                    onCheckedChange = { controller.toggleNight() },
                    label = { Text(stringResource(R.string.night_mode)) },
                    secondaryLabel = { Text(stringResource(R.string.night_mode_text), maxLines = 2, fontSize = 11.sp) },
                    toggleControl = {
                        androidx.wear.compose.material.Icon(
                            imageVector = ToggleChipDefaults.switchIcon(checked = night),
                            contentDescription = null,
                        )
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            if (demoPin) item { Small(stringResource(R.string.home_demo_pin)) }

            item { ListHeader { Text(stringResource(R.string.home_demo)) } }
            item { DemoChip(stringResource(R.string.demo_alarm), controller::demoAlarm) }
            item { DemoChip(stringResource(R.string.demo_checkin), controller::demoCheckIn) }
            item { DemoChip(stringResource(R.string.demo_alarm_end), controller::demoAlarmEnd) }
            item { DemoChip(stringResource(R.string.demo_warning), controller::demoWarning) }
            item { DemoChip(stringResource(R.string.demo_fixed), controller::demoFixed) }
            item { DemoChip(stringResource(R.string.demo_pad), controller::demoPad) }
            if (simulated) item {
                ToggleChip(
                    checked = shaking,
                    onCheckedChange = { shaking = it; controller.demoShaking(it) },
                    label = { Text(stringResource(R.string.demo_seizure_motion)) },
                    toggleControl = {
                        androidx.wear.compose.material.Icon(
                            imageVector = ToggleChipDefaults.switchIcon(checked = shaking),
                            contentDescription = null,
                        )
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

@Composable
private fun DemoChip(label: String, onClick: () -> Unit) = Chip(
    onClick = onClick,
    label = { Text(label) },
    colors = ChipDefaults.secondaryChipColors(),
    modifier = Modifier.fillMaxWidth(),
)

@Composable
private fun Small(text: String) =
    Text(text, fontSize = 11.sp, textAlign = TextAlign.Center, color = Color(0xFFBDC1C6),
        modifier = Modifier.padding(horizontal = 8.dp))

// ------------------------------------------------------------------ alarm + PIN

@Composable
private fun AlarmScreen(s: Screen.Alarm, onPin: (String) -> Unit) {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(s.deadlineMs) {
        while (true) {
            now = System.currentTimeMillis()
            delay(250)
        }
    }
    val secondsLeft = ((s.deadlineMs - now + 999) / 1000).coerceAtLeast(0).toInt()
    PinScreen(
        background = Red,
        title = stringResource(R.string.alarm_title),
        subtitle = stringResource(R.string.alarm_text, secondsLeft),
        wrongAttempts = s.wrongAttempts,
        onPin = onPin,
    )
}

/**
 * Title, PIN dots and a 3x4 keypad sized for a round ~1.2-1.4" screen. The PIN is submitted
 * automatically after 4 digits. A single tap never cancels anything.
 */
@Composable
private fun PinScreen(background: Color, title: String, subtitle: String, wrongAttempts: Int, onPin: (String) -> Unit) {
    var digits by remember { mutableStateOf("") }
    Column(
        modifier = Modifier.fillMaxSize().background(background).padding(top = 14.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(title, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = Color.White)
        Text(
            if (wrongAttempts > 0 && digits.isEmpty()) stringResource(R.string.pin_wrong) else subtitle,
            fontSize = 10.sp, color = Color.White, textAlign = TextAlign.Center, maxLines = 2, lineHeight = 12.sp,
            modifier = Modifier.padding(horizontal = 40.dp),
        )
        Text(
            (1..PinVerifier.PIN_LENGTH).joinToString(" ") { if (it <= digits.length) "●" else "○" },
            fontSize = 14.sp, color = Color.White, modifier = Modifier.padding(vertical = 2.dp),
        )
        val rows = listOf(listOf("1", "2", "3"), listOf("4", "5", "6"), listOf("7", "8", "9"), listOf("", "0", "⌫"))
        for (row in rows) {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                for (key in row) {
                    Key(key) {
                        when (key) {
                            "⌫" -> digits = digits.dropLast(1)
                            "" -> Unit
                            else -> {
                                digits += key
                                if (digits.length == PinVerifier.PIN_LENGTH) {
                                    onPin(digits)
                                    digits = ""
                                }
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(3.dp))
        }
    }
}

@Composable
private fun Key(label: String, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .width(42.dp).height(27.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(if (label.isEmpty()) Color.Transparent else Color(0x33FFFFFF))
            .clickable(enabled = label.isNotEmpty(), onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, fontSize = 15.sp, color = Color.White, fontWeight = FontWeight.Medium)
    }
}

// ------------------------------------------------------------------ message screens

@Composable
private fun MessageScreen(background: Color, title: String, text: String?, button: String?, onButton: () -> Unit = {}) {
    Column(
        modifier = Modifier.fillMaxSize().background(background).padding(horizontal = 22.dp, vertical = 26.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(title, fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Color.White, textAlign = TextAlign.Center)
        if (text != null) {
            Spacer(Modifier.height(6.dp))
            Text(text, fontSize = 11.sp, color = Color.White, textAlign = TextAlign.Center)
        }
        if (button != null) {
            Spacer(Modifier.height(10.dp))
            Box(
                modifier = Modifier.size(width = 80.dp, height = 34.dp).clip(RoundedCornerShape(17.dp))
                    .background(Color(0x40FFFFFF)).clickable(onClick = onButton),
                contentAlignment = Alignment.Center,
            ) { Text(button, color = Color.White, fontWeight = FontWeight.Bold) }
        }
    }
}

@Composable
private fun pluralTitle(n: Int) = stringResource(R.string.night_summary_title, n)

@Composable
private fun padNames(detail: String): String {
    val names = mapOf(
        "L-top" to stringResource(R.string.pad_l_top),
        "L-bottom" to stringResource(R.string.pad_l_bottom),
        "R-top" to stringResource(R.string.pad_r_top),
        "R-bottom" to stringResource(R.string.pad_r_bottom),
        "bias" to stringResource(R.string.pad_bias),
    )
    return detail.split(",").filter { it.isNotBlank() }.joinToString("; ") { names[it] ?: it }
}

@Composable
private fun warningText(code: WarningCode, detail: String = ""): String = when (code) {
    WarningCode.PAD_CONTACT_LOST -> stringResource(R.string.warn_pad_contact_lost, padNames(detail))
    WarningCode.PAD_REPLACE -> stringResource(R.string.warn_pad_replace, padNames(detail))
    WarningCode.HEADBAND_BATTERY_LOW -> stringResource(R.string.warn_headband_battery_low, detail)
    WarningCode.HEADBAND_BATTERY_CRITICAL -> stringResource(R.string.warn_headband_battery_critical, detail)
    WarningCode.HEADBAND_CHARGING -> stringResource(R.string.warn_headband_charging)
    WarningCode.HEADBAND_UPDATING -> stringResource(R.string.warn_headband_updating)
    WarningCode.PHONE_BATTERY_LOW -> stringResource(R.string.warn_phone_battery_low, detail)
    WarningCode.PHONE_BATTERY_CRITICAL -> stringResource(R.string.warn_phone_battery_critical, detail)
    WarningCode.WATCH_BATTERY_LOW -> stringResource(R.string.warn_watch_battery_low, detail)
    WarningCode.HEADBAND_OFF -> stringResource(when (detail) {
        "disconnected" -> R.string.warn_headband_disconnected
        "unpaired" -> R.string.warn_headband_unpaired
        else -> R.string.warn_headband_off
    })
    else -> simpleWarningText(code)
}

@Composable
private fun simpleWarningText(code: WarningCode) = stringResource(
    when (code) {
        WarningCode.HEADBAND_MISSING -> R.string.warn_headband_missing
        WarningCode.BRAIN_WEAK -> R.string.warn_brain_weak
        WarningCode.HEAD_MOV_MISSING -> R.string.warn_head_mov_missing
        WarningCode.WATCH_MISSING -> R.string.warn_watch_missing
        WarningCode.HEART_MISSING -> R.string.warn_heart_missing
        WarningCode.BODY_MOV_MISSING -> R.string.warn_body_mov_missing
        WarningCode.PHONE_DISCONNECTED -> R.string.warn_phone_disconnected
        else -> R.string.warn_headband_missing
    }
)

@Composable
private fun impactText(impact: Impact) = stringResource(
    when (impact) {
        Impact.LIMITED -> R.string.impact_limited
        Impact.WEAKER -> R.string.impact_weaker
        Impact.BACKUP_MODEL -> R.string.impact_backup
        Impact.NO_ALARMS -> R.string.impact_no_alarms
        Impact.NONE -> R.string.impact_none
    }
)

@Composable
private fun infoText(kind: InfoKind) = stringResource(
    when (kind) {
        InfoKind.FALSE_ALARM_SENT -> R.string.info_false_alarm
        InfoKind.RECOVERY_OK -> R.string.info_recovery_ok
        InfoKind.SENSOR_FIXED -> R.string.info_sensor_fixed
        InfoKind.ALARM_ENDED -> R.string.info_alarm_ended
    }
)

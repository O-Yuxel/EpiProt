package org.epiprot.phone.ui

import android.app.TimePickerDialog
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Face
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import org.epiprot.phone.PhoneMonitor
import org.epiprot.phone.R
import org.epiprot.phone.headband.Channels
import org.epiprot.phone.headband.HeadbandState
import org.epiprot.phone.headband.PadStatus
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.ui.EpiColors as C

/** The headband is "connected" when a packet arrived in the last 10 s. */
internal fun headbandConnected(s: HeadbandState?, now: Long) = s != null && now - s.lastPacketMs < 10_000

@Composable
internal fun padName(name: String) = stringResource(when (name) {
    "L-top" -> R.string.pad_l_top
    "L-bottom" -> R.string.pad_l_bottom
    "R-top" -> R.string.pad_r_top
    "R-bottom" -> R.string.pad_r_bottom
    else -> R.string.pad_bias
})

private fun padColor(c: PadStatus.Contact) = when (c) {
    PadStatus.Contact.OK -> C.Mint
    PadStatus.Contact.DRYING -> C.Amber
    PadStatus.Contact.NONE -> C.Coral
    PadStatus.Contact.UNKNOWN -> C.Grey
}

/** Live state of the headband: connection, battery, every pad's contact, signals, channels in use. */
@Composable
internal fun HeadbandPage(m: PhoneMonitor, activity: MainActivity) {
    val st by m.status.collectAsStateWithLifecycle()
    val demo by m.demo.collectAsStateWithLifecycle()
    val link by m.headbandLink.collectAsStateWithLifecycle()
    var now by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(1_000) } }
    val hb = st.headband
    val ok = headbandConnected(hb, now)

    EpiCard {
        CardHeader(Icons.Rounded.Face, stringResource(R.string.headband), tint = if (ok) C.TealDark else C.Grey,
            bubble = if (ok) C.TealSoft else C.GreySoft, trailing = {
                when {
                    hb?.chargerAttached == true -> Pill(stringResource(R.string.hb_charging), C.Amber, C.AmberSoft)
                    ok -> Pill(stringResource(R.string.connected), C.Mint, C.MintSoft)
                    else -> Pill(stringResource(R.string.not_connected), C.InkSoft, C.GreySoft)
                }
            })
        if (hb == null) Text(stringResource(R.string.hb_never), color = C.InkSoft)
        else {
            InfoRow(stringResource(R.string.hb_battery_label), if (hb.batteryPct >= 0) "${hb.batteryPct} %" else "–")
            InfoRow(stringResource(R.string.hb_last_data), time(hb.lastPacketMs))
            if (st.demo) Text(stringResource(R.string.hb_is_virtual), color = C.TealDark, style = MaterialTheme.typography.bodySmall)
            else {
                InfoRow(stringResource(R.string.hb_catch_up), "${hb.catchUp}")
                InfoRow(stringResource(R.string.hb_missing), "${hb.missing}")
            }
        }
        if (!st.demo) {
            InfoRow(stringResource(R.string.hb_link), stringResource(when (link) {
                org.epiprot.phone.headband.HeadbandLink.State.IDLE -> R.string.hb_link_idle
                org.epiprot.phone.headband.HeadbandLink.State.SCANNING -> R.string.hb_link_scanning
                org.epiprot.phone.headband.HeadbandLink.State.CONNECTING -> R.string.hb_link_connecting
                org.epiprot.phone.headband.HeadbandLink.State.CONNECTED -> R.string.hb_link_connected
                org.epiprot.phone.headband.HeadbandLink.State.RECONNECTING -> R.string.hb_link_reconnecting
            }))
            var noPerm by remember { mutableStateOf(false) }
            if (link == org.epiprot.phone.headband.HeadbandLink.State.IDLE) {
                PrimaryButton(stringResource(R.string.hb_connect)) {
                    noPerm = !m.connectHeadband()
                    if (noPerm) activity.requestPermissions(fromButton = true)
                }
                if (noPerm) Text(stringResource(R.string.hb_need_permission), color = C.Amber, style = MaterialTheme.typography.bodySmall)
            } else {
                if (link == org.epiprot.phone.headband.HeadbandLink.State.CONNECTED)
                    SoftButton(stringResource(R.string.hb_check_now)) { m.requestContactCheck() }
                SoftButton(stringResource(R.string.hb_disconnect)) { m.disconnectHeadband() }
            }
        }
    }

    val pads = PadStatus.of(hb)
    EpiCard {
        CardHeader(Icons.Rounded.CheckCircle, stringResource(R.string.hb_pads))
        HeadDiagram(pads, Modifier.fillMaxWidth().height(170.dp))
        Text(stringResource(R.string.hb_back_view), style = MaterialTheme.typography.bodySmall, color = C.InkSoft,
            modifier = Modifier.align(Alignment.CenterHorizontally))
        pads.forEach { p ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(12.dp).clip(CircleShape).background(padColor(p.contact)))
                Spacer(Modifier.width(10.dp))
                Text(padName(p.name), Modifier.weight(1f), color = C.Ink)
                Text(when (p.contact) {
                    PadStatus.Contact.OK -> stringResource(R.string.pad_state_ok, p.kohm ?: 0)
                    PadStatus.Contact.DRYING -> stringResource(R.string.pad_state_drying, p.kohm ?: 0)
                    PadStatus.Contact.NONE -> stringResource(R.string.pad_state_none)
                    PadStatus.Contact.UNKNOWN -> stringResource(R.string.pad_state_unknown)
                }, color = padColor(p.contact), style = MaterialTheme.typography.bodySmall)
            }
        }
        Text(stringResource(R.string.hb_last_check, if (hb != null && hb.lastContactCheckMs > 0) time(hb.lastContactCheckMs) else "–"),
            style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
    }

    EpiCard {
        CardHeader(Icons.Rounded.Refresh, stringResource(R.string.hb_signals))
        SignalRow(stringResource(R.string.hb_brain), if (ok) st.quality["brain"] else null)
        SignalRow(stringResource(R.string.hb_head_mov), if (ok) st.quality["head_mov"] else null)
        val ch = st.channels
        InfoRow(stringResource(R.string.hb_channels), when {
            !ok || ch == null -> "–"
            !ch.backup -> stringResource(R.string.hb_channels_standard)
            else -> stringResource(R.string.hb_channels_backup, ch.first + 1, ch.second + 1)
        })
    }

    EpiCard(container = C.TealSoft) {
        CardHeader(Icons.Rounded.PlayArrow, stringResource(R.string.hb_virtual_title), bubble = Color.White)
        Text(stringResource(R.string.hb_virtual_text), color = C.InkSoft, style = MaterialTheme.typography.bodyMedium)
        val d = demo
        if (d == null) PrimaryButton(stringResource(R.string.hb_virtual_start), Icons.Rounded.PlayArrow) { m.startHeadbandDemo() }
        else {
            LinearProgressIndicator(progress = { d.window.toFloat() / d.windows.coerceAtLeast(1) },
                modifier = Modifier.fillMaxWidth().height(8.dp).clip(CircleShape), color = C.Teal, trackColor = Color.White)
            SoftButton(stringResource(R.string.demo_stop)) { m.stopDemo() }
        }
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row {
        Text(label, Modifier.weight(1f), color = C.InkSoft)
        Text(value, color = C.Ink)
    }
}

@Composable
private fun SignalRow(label: String, q: HealthMonitor.Quality?) {
    val (text, color) = when (q) {
        HealthMonitor.Quality.OK -> stringResource(R.string.sig_ok) to C.Mint
        HealthMonitor.Quality.POOR -> stringResource(R.string.sig_poor) to C.Amber
        HealthMonitor.Quality.MISSING -> stringResource(R.string.sig_missing) to C.Coral
        null -> "–" to C.Grey
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f), color = C.InkSoft)
        Pill(text, color, color.copy(alpha = 0.12f))
    }
}

/** The head seen from behind: band, ears, the four pads behind the ears and the bias electrode at the nape. */
@Composable
private fun HeadDiagram(pads: List<PadStatus.Pad>, modifier: Modifier) {
    Canvas(modifier) {
        val w = size.width; val h = size.height
        val cx = w / 2; val r = h * 0.42f; val cy = h * 0.45f
        drawRect(C.GreySoft, Offset(cx - r * 0.35f, cy + r * 0.8f), Size(r * 0.7f, h - (cy + r * 0.8f)))   // neck
        drawOval(C.GreySoft, Offset(cx - r * 1.12f, cy - r * 0.15f), Size(r * 0.3f, r * 0.55f))            // left ear
        drawOval(C.GreySoft, Offset(cx + r * 0.82f, cy - r * 0.15f), Size(r * 0.3f, r * 0.55f))            // right ear
        drawCircle(C.GreySoft, r, Offset(cx, cy))
        drawCircle(C.Line, r, Offset(cx, cy), style = Stroke(2f))
        drawLine(C.Teal.copy(alpha = 0.5f), Offset(cx - r * 0.98f, cy + r * 0.05f), Offset(cx + r * 0.98f, cy + r * 0.05f), 10f)  // band
        val pos = mapOf(
            "L-top" to Offset(cx - r * 0.83f, cy + r * 0.12f), "L-bottom" to Offset(cx - r * 0.75f, cy + r * 0.45f),
            "R-top" to Offset(cx + r * 0.83f, cy + r * 0.12f), "R-bottom" to Offset(cx + r * 0.75f, cy + r * 0.45f),
            "bias" to Offset(cx, cy + r * 1.05f),
        )
        for (p in pads) {
            val o = pos[p.name] ?: continue
            drawCircle(Color.White, h * 0.06f, o)
            drawCircle(padColor(p.contact), h * 0.045f, o)
        }
    }
}

/** Night mode of the watch: on / off and the time range; changes go to the watch at once. */
@Composable
internal fun NightPage(m: PhoneMonitor) {
    val s = m.settings
    val ctx = LocalContext.current
    var enabled by remember { mutableStateOf(s.nightEnabled) }
    var start by remember { mutableStateOf(s.nightStartMin) }
    var end by remember { mutableStateOf(s.nightEndMin) }
    fun save() = m.setNightMode(enabled, start, end)
    fun pick(current: Int, set: (Int) -> Unit) = TimePickerDialog(ctx, { _, hh, mm -> set(hh * 60 + mm); save() },
        current / 60, current % 60, true).show()

    EpiCard {
        CardHeader(Icons.Rounded.Notifications, stringResource(R.string.night_title), trailing = {
            Switch(enabled, { enabled = it; save() }, colors = SwitchDefaults.colors(checkedTrackColor = C.Teal))
        })
        Text(stringResource(R.string.night_text), color = C.InkSoft)
        HorizontalDivider(color = C.Line)
        TimeRow(stringResource(R.string.night_from), start, enabled) { pick(start) { start = it } }
        TimeRow(stringResource(R.string.night_to), end, enabled) { pick(end) { end = it } }
    }
    EpiCard(container = C.TealSoft) {
        CardHeader(Icons.Rounded.Info, stringResource(R.string.night_rules_title), bubble = Color.White)
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("• " + stringResource(R.string.night_rule_alarm), color = C.Ink)
            Text("• " + stringResource(R.string.night_rule_urgent), color = C.Ink)
            Text("• " + stringResource(R.string.night_rule_quiet), color = C.Ink)
            Text("• " + stringResource(R.string.night_rule_summary), color = C.Ink)
        }
    }
}

internal fun hhmm(min: Int) = "%02d:%02d".format(min / 60, min % 60)

@Composable
private fun TimeRow(label: String, min: Int, enabled: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick).padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f), color = if (enabled) C.Ink else C.Grey)
        Text(hhmm(min), style = MaterialTheme.typography.titleLarge, color = if (enabled) C.TealDark else C.Grey)
    }
}

/** Channel choice in words, for the home card. */
internal fun Channels.Choice?.isBackup() = this?.backup == true

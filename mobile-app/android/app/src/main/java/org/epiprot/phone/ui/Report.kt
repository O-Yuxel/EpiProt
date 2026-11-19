package org.epiprot.phone.ui

import android.content.Intent
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.Column
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Send
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.epiprot.phone.PhoneMonitor
import org.epiprot.phone.R
import java.text.DateFormat
import java.util.Date
import org.epiprot.phone.ui.EpiColors as C

/**
 * Doctor report: the patient chooses the period, sees exactly what will be shared, confirms (each report is its own
 * decision, recorded in the consent history) and sends the PDF with any app they like (WhatsApp, e-mail ...).
 */
@Composable
fun ReportPage(m: PhoneMonitor, back: () -> Unit) {
    val ctx = LocalContext.current
    val now = remember { System.currentTimeMillis() }
    val last = remember { m.settings.lastReportMs }      // fixed while the page is open
    val periods = buildList {
        if (last > 0) add(R.string.rep_since_last to last)
        add(R.string.rep_last30 to now - 30L * 86_400_000)
        add(R.string.rep_last90 to now - 90L * 86_400_000)
        add(R.string.rep_all to 0L)
    }
    var sel by rememberSaveable { mutableIntStateOf(0) }
    var demo by rememberSaveable { mutableStateOf(false) }
    var graphs by rememberSaveable { mutableStateOf(true) }
    var confirm by remember { mutableStateOf(false) }
    val from = periods[sel.coerceAtMost(periods.lastIndex)].second
    val data by produceState<org.epiprot.phone.report.ReportData?>(null, from, demo) {
        value = withContext(Dispatchers.IO) { m.reportData(from, now, demo) }
    }
    val withSignals by produceState(0, data) {
        value = withContext(Dispatchers.IO) { data?.let { d -> m.signalsFor(d.events.map { it.eventId }).size } ?: 0 }
    }

    Row(verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = back) { Icon(Icons.Rounded.ArrowBack, stringResource(R.string.back), tint = C.Ink) }
        Text(stringResource(R.string.rep_card_title), style = MaterialTheme.typography.titleLarge)
    }

    EpiCard {
        Text(stringResource(R.string.rep_choose_period), style = MaterialTheme.typography.titleMedium)
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            periods.forEachIndexed { i, (label, _) ->
                FilterChip(selected = sel == i, onClick = { sel = i }, label = { Text(stringResource(label)) },
                    colors = FilterChipDefaults.filterChipColors(selectedContainerColor = C.TealSoft, selectedLabelColor = C.TealDark))
            }
        }
        Row(Modifier.fillMaxWidth().clickable { demo = !demo }, verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.rep_include_demo), modifier = Modifier.weight(1f))
            Switch(demo, { demo = it }, colors = SwitchDefaults.colors(checkedTrackColor = C.Teal))
        }
    }

    val d = data
    EpiCard {
        Text(stringResource(R.string.rep_preview), style = MaterialTheme.typography.titleMedium)
        if (d == null) Text("…", color = C.InkSoft)
        else {
            val df = DateFormat.getDateInstance(DateFormat.MEDIUM)
            Text(df.format(Date(if (d.fromMs == 0L) (d.events.firstOrNull()?.alarmMs ?: now) else d.fromMs)) + " – " + df.format(Date(d.toMs)),
                color = C.InkSoft)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Pill(stringResource(R.string.rep_n_seizures, d.seizures), C.Coral, C.CoralSoft)
                Pill(stringResource(R.string.rep_n_unconfirmed, d.unconfirmed), C.Amber, C.AmberSoft)
                Pill(stringResource(R.string.rep_n_false, d.falseAlarms), C.TealDark, C.TealSoft)
            }
            if (d.events.isEmpty()) Text(stringResource(R.string.rep_empty_period), color = C.InkSoft)
            Row(Modifier.fillMaxWidth().clickable(enabled = withSignals > 0) { graphs = !graphs }, verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(stringResource(R.string.rep_include_graphs))
                    Text(if (withSignals > 0) stringResource(R.string.rep_graphs_n, withSignals)
                         else stringResource(if (m.consents.value.signalsAllowed) R.string.rep_graphs_none else R.string.rep_graphs_no_consent),
                        style = MaterialTheme.typography.bodySmall, color = C.InkSoft)
                }
                Switch(graphs && withSignals > 0, { graphs = it }, enabled = withSignals > 0, colors = SwitchDefaults.colors(checkedTrackColor = C.Teal))
            }
        }
    }

    EpiCard(container = C.MintSoft) {
        Text(stringResource(R.string.rep_shared_title), style = MaterialTheme.typography.titleMedium, color = C.Mint)
        Bullets(listOfNotNull(stringResource(R.string.rep_shared_1), stringResource(R.string.rep_shared_2), stringResource(R.string.rep_shared_3),
            if (graphs && withSignals > 0) stringResource(R.string.rep_shared_4) else null), Icons.Rounded.Check, C.Mint)
    }
    EpiCard(container = C.GreySoft) {
        Text(stringResource(R.string.rep_not_shared_title), style = MaterialTheme.typography.titleMedium, color = C.InkSoft)
        Bullets(listOf(stringResource(R.string.rep_not_shared_1)), Icons.Rounded.Close, C.InkSoft)
    }
    Row {
        Icon(Icons.Rounded.Info, null, tint = C.Amber)
        Spacer(Modifier.width(8.dp))
        Text(stringResource(R.string.rep_channel_note), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)
    }

    SoftButton(stringResource(R.string.rep_preview_pdf)) {
        val r = d ?: return@SoftButton
        val f = m.createReport(r, graphs)
        val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".reports", f)
        try {
            ctx.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/pdf")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: Exception) {
            Toast.makeText(ctx, ctx.getString(R.string.rep_no_viewer), Toast.LENGTH_LONG).show()
        }
    }
    PrimaryButton(stringResource(R.string.rep_share), Icons.Rounded.Send) { if (d != null) confirm = true }

    if (confirm && d != null) AlertDialog(
        onDismissRequest = { confirm = false },
        icon = { Icon(Icons.Rounded.Warning, null, tint = C.Amber) },
        title = { Text(stringResource(R.string.rep_confirm_title)) },
        text = { Text(stringResource(R.string.rep_confirm_text, d.events.size)) },
        confirmButton = { TextButton(onClick = {
            confirm = false
            val f = m.createReport(d, graphs)
            val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".reports", f)
            val send = Intent(Intent.ACTION_SEND).setType("application/pdf")
                .putExtra(Intent.EXTRA_STREAM, uri)
                .putExtra(Intent.EXTRA_SUBJECT, ctx.getString(R.string.rep_subject, m.settings.patientName.ifBlank { "" }))
                .putExtra(Intent.EXTRA_TEXT, ctx.getString(R.string.rep_message))
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            m.settings.doctorEmail.takeIf { it.isNotBlank() }?.let { send.putExtra(Intent.EXTRA_EMAIL, arrayOf(it)) }
            ctx.startActivity(Intent.createChooser(send, ctx.getString(R.string.rep_share)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            m.reportShared(d)
        }) { Text(stringResource(R.string.rep_confirm_go), color = C.TealDark) } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text(stringResource(R.string.cancel)) } },
    )
}

package org.epiprot.phone.ui

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.epiprot.phone.R
import java.util.Calendar
import org.epiprot.phone.ui.EpiColors as C

/**
 * Seizure diary: add a seizure by hand (headband not worn, charging, or the device did not raise an alarm).
 * The answers become one event with source "manual" (EventLog.addManualEvent) and show in the doctor report.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ManualSeizureDialog(onDismiss: () -> Unit, onSave: (timeMs: Long, type: String, worn: String, note: String) -> Unit) {
    val ctx = LocalContext.current
    var timeMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var type by remember { mutableStateOf<String?>(null) }
    var worn by remember { mutableStateOf<String?>(null) }
    var note by remember { mutableStateOf("") }

    fun pickDateThenTime() {
        val cal = Calendar.getInstance().apply { timeInMillis = timeMs }
        DatePickerDialog(ctx, { _, y, mo, d ->
            cal.set(y, mo, d)
            TimePickerDialog(ctx, { _, h, mi ->
                cal.set(Calendar.HOUR_OF_DAY, h); cal.set(Calendar.MINUTE, mi)
                timeMs = minOf(cal.timeInMillis, System.currentTimeMillis())       // never in the future
            }, cal.get(Calendar.HOUR_OF_DAY), cal.get(Calendar.MINUTE), true).show()
        }, cal.get(Calendar.YEAR), cal.get(Calendar.MONTH), cal.get(Calendar.DAY_OF_MONTH)).apply {
            datePicker.maxDate = System.currentTimeMillis()
        }.show()
    }

    AlertDialog(onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.manual_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(stringResource(R.string.manual_when), fontWeight = FontWeight.SemiBold)
                TextButton({ pickDateThenTime() }) { Text(dateTime(timeMs), color = C.TealDark) }

                Text(stringResource(R.string.manual_type), fontWeight = FontWeight.SemiBold)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("tonic_clonic" to R.string.manual_type_tc, "other" to R.string.manual_type_other,
                        "unsure" to R.string.manual_type_unsure).forEach { (k, label) ->
                        FilterChip(selected = type == k, onClick = { type = k }, label = { Text(stringResource(label)) })
                    }
                }
                Text(stringResource(R.string.manual_type_help), color = C.InkSoft, style = MaterialTheme.typography.bodySmall)

                Text(stringResource(R.string.manual_worn_label), fontWeight = FontWeight.SemiBold)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("yes" to R.string.manual_worn_yes, "no" to R.string.manual_worn_no,
                        "unknown" to R.string.manual_worn_unknown).forEach { (k, label) ->
                        FilterChip(selected = worn == k, onClick = { worn = k }, label = { Text(stringResource(label)) })
                    }
                }
                OutlinedTextField(note, { note = it.take(300) }, label = { Text(stringResource(R.string.manual_note)) },
                    modifier = Modifier.fillMaxWidth(), minLines = 2)
                if (type == "tonic_clonic" && worn == "yes")
                    Text(stringResource(R.string.manual_missed_note), color = C.Coral, style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            TextButton({ onSave(timeMs, type ?: "unsure", worn ?: "unknown", note) }, enabled = type != null && worn != null) {
                Text(stringResource(R.string.manual_save))
            }
        },
        dismissButton = { TextButton(onDismiss) { Text(stringResource(R.string.hb_cancel)) } })
}

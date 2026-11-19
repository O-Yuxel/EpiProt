package org.epiprot.phone.comm

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.telephony.SmsManager
import android.util.Log
import androidx.core.content.ContextCompat
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withTimeoutOrNull
import org.epiprot.phone.EpiProtPhoneApp
import org.epiprot.phone.R
import org.epiprot.phone.alarm.CaregiverMessage
import org.epiprot.phone.data.EventLog
import org.epiprot.phone.data.Settings
import org.epiprot.phone.protocol.PhoneMessage
import org.epiprot.phone.protocol.WATCH_CAPABILITY
import java.text.DateFormat
import java.util.Date
import java.util.Locale

private const val TAG = "EpiProt"

/** Current position for the caregiver message (Google Maps link), or null within 10 s. */
class LocationProvider(private val context: Context) {
    @SuppressLint("MissingPermission")
    suspend fun mapsLink(): String? {
        val fine = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!fine && !coarse) return null
        val client = LocationServices.getFusedLocationProviderClient(context)
        val loc = try {
            withTimeoutOrNull(10_000) {
                client.getCurrentLocation(if (fine) Priority.PRIORITY_HIGH_ACCURACY else Priority.PRIORITY_BALANCED_POWER_ACCURACY,
                    CancellationTokenSource().token).await()
            } ?: client.lastLocation.await()
        } catch (e: Exception) {
            Log.w(TAG, "location failed", e); null
        } ?: return null
        return String.format(Locale.US, "https://maps.google.com/?q=%.5f,%.5f (±%d m)", loc.latitude, loc.longitude, loc.accuracy.toInt())
    }
}

/**
 * Messages to the caregivers: SMS from the patient's own phone (works without internet).
 * In test mode (default) they are only written to the log and shown in the app.
 */
class CaregiverMessenger(private val context: Context, private val settings: Settings, private val log: EventLog,
                         private val location: LocationProvider,
                         private val consents: () -> org.epiprot.phone.privacy.ConsentState) {

    /** One information SMS to a newly added caregiver: who added them, what they will receive, how to opt out. */
    fun sendIntro(to: String, nowMs: Long = System.currentTimeMillis()) {
        val consent = consents()
        if (!consent.smsAllowed || !consent.caregiverConfirmed(to)) return
        val name = settings.patientName.ifBlank { context.getString(R.string.patient_default) }
        val text = context.getString(R.string.sms_intro, name,
            context.getString(if (consent.locationAllowed) R.string.sms_intro_with_location else R.string.sms_intro_no_location))
        log.message(nowMs, 0, to, text, deliver(to, text))
    }

    private fun deliver(to: String, text: String): String = when {
        !settings.realSms -> "test"
        ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED -> "failed"
        else -> try {
            val sms = if (Build.VERSION.SDK_INT >= 31) context.getSystemService(SmsManager::class.java)
                      else @Suppress("DEPRECATION") SmsManager.getDefault()
            sms.sendMultipartTextMessage(to, null, sms.divideMessage(text), null, null)
            "sent"
        } catch (e: Exception) {
            Log.e(TAG, "SMS failed", e); "failed"
        }
    }

    suspend fun send(eventId: Long, kind: CaregiverMessage, demo: Boolean, nowMs: Long = System.currentTimeMillis()) {
        val name = settings.patientName.ifBlank { context.getString(R.string.patient_default) }
        val time = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(nowMs))
        val consent = consents()
        val needsLocation = kind != CaregiverMessage.FALSE_ALARM && kind != CaregiverMessage.HANDOVER
        val where = when {
            !needsLocation -> ""
            !consent.locationAllowed -> context.getString(R.string.location_not_shared)   // no location consent: not even read
            else -> location.mapsLink() ?: context.getString(R.string.location_unknown)
        }
        val res = when (kind) {
            CaregiverMessage.SEIZURE_ALERT -> R.string.sms_alert
            CaregiverMessage.FALSE_ALARM -> R.string.sms_false_alarm
            CaregiverMessage.EMERGENCY -> R.string.sms_emergency
            CaregiverMessage.NO_ANSWER -> R.string.sms_no_answer
            CaregiverMessage.HANDOVER -> R.string.sms_handover
        }
        val emergency = consent.region?.emergency ?: context.getString(R.string.emergency_local)
        val text = (if (demo) "[DEMO] " else "") + context.getString(res, name, time, where, emergency)
        val numbers = settings.caregivers
        if (numbers.isEmpty()) { log.message(nowMs, eventId, "-", text, "no_number"); return }
        // no SMS consent: nothing leaves the phone, the message is only kept in the log
        if (!consent.smsAllowed) { log.message(nowMs, eventId, "-", text, "no_consent"); return }
        for (n in numbers.filterNot(consent::caregiverConfirmed)) log.message(nowMs, eventId, n, text, "not_confirmed")
        for (to in consent.recipients(numbers)) log.message(nowMs, eventId, to, text, deliver(to, text))
    }
}

/** Sends messages to the EpiProt watch app over the Wear OS Data Layer. */
class WatchLink(private val context: Context) {
    suspend fun send(msg: PhoneMessage): Boolean = try {
        val (path, data) = PhoneMessage.encode(msg)
        val nodes = Wearable.getCapabilityClient(context)
            .getCapability(WATCH_CAPABILITY, CapabilityClient.FILTER_REACHABLE).await().nodes
        for (n in nodes) Wearable.getMessageClient(context).sendMessage(n.id, path, data).await()
        nodes.isNotEmpty()
    } catch (e: Exception) {
        Log.w(TAG, "watch message failed: $msg", e); false
    }
}

/** Receives sensor packets, PIN results and status from the watch app. */
class WatchListenerService : WearableListenerService() {
    override fun onMessageReceived(event: MessageEvent) {
        EpiProtPhoneApp.monitor(this).onWatchMessage(event.path, event.data)
    }
}

package org.epiprot.phone.comm

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
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
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
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
    suspend fun sendIntro(to: String, nowMs: Long = System.currentTimeMillis()) {
        val consent = consents()
        if (!consent.smsAllowed || !consent.caregiverConfirmed(to)) return
        val name = settings.patientName.ifBlank { context.getString(R.string.patient_default) }
        val text = context.getString(R.string.sms_intro, name,
            context.getString(if (consent.locationAllowed) R.string.sms_intro_with_location else R.string.sms_intro_no_location)) +
            "\n" + CaregiverTag.INTRO
        deliver(nowMs, 0, to, text)
    }

    /**
     * Sends one SMS and logs it: "sending" at once, then "sent" when the phone network accepted every part, or
     * "failed" after [TRIES] tries [RETRY_MS] apart (no signal, SIM problem). A final failure also shows a notification,
     * because the caregiver does not know about the seizure.
     */
    private suspend fun deliver(nowMs: Long, eventId: Long, to: String, text: String) {
        if (!settings.realSms) { log.message(nowMs, eventId, to, text, "test"); return }
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            log.message(nowMs, eventId, to, text, "failed"); PhoneAlertsBridge.smsFailed(context, to); return
        }
        val row = log.message(nowMs, eventId, to, text, "sending")
        for (attempt in 1..TRIES) {
            if (sendOnce(to, text)) { log.messageStatus(row, if (attempt == 1) "sent" else "sent_retry"); return }
            Log.w(TAG, "SMS to $to not sent, try $attempt of $TRIES")
            if (attempt < TRIES) delay(RETRY_MS)
        }
        log.messageStatus(row, "failed")
        PhoneAlertsBridge.smsFailed(context, to)
    }

    /** One try: true when the network accepted every part of the message within 60 s. */
    private suspend fun sendOnce(to: String, text: String): Boolean {
        val sms = if (Build.VERSION.SDK_INT >= 31) context.getSystemService(SmsManager::class.java)
                  else @Suppress("DEPRECATION") SmsManager.getDefault()
        val parts = sms.divideMessage(text)
        val action = "org.epiprot.phone.SMS_SENT." + System.nanoTime()
        val results = Channel<Int>(parts.size)
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) { results.trySend(resultCode) }
        }
        ContextCompat.registerReceiver(context, receiver, IntentFilter(action), ContextCompat.RECEIVER_NOT_EXPORTED)
        return try {
            val sent = ArrayList(parts.indices.map {
                PendingIntent.getBroadcast(context, it, Intent(action).setPackage(context.packageName), PendingIntent.FLAG_IMMUTABLE)
            })
            sms.sendMultipartTextMessage(to, null, parts, sent, null)
            withTimeoutOrNull(SENT_TIMEOUT_MS) {
                repeat(parts.size) { if (results.receive() != Activity.RESULT_OK) return@withTimeoutOrNull false }
                true
            } ?: false
        } catch (e: Exception) {
            Log.e(TAG, "SMS failed", e); false
        } finally {
            try { context.unregisterReceiver(receiver) } catch (_: Exception) { }
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
            CaregiverMessage.SOS -> R.string.sms_sos
        }
        val emergency = consent.region?.emergency ?: context.getString(R.string.emergency_local)
        // the tag lets EpiProt in caregiver mode ring on the caregiver's phone (any language, no internet)
        val text = (if (demo) "[DEMO] " else "") + context.getString(res, name, time, where, emergency) + "\n" + CaregiverTag.of(kind)
        val numbers = settings.caregivers
        if (numbers.isEmpty()) { log.message(nowMs, eventId, "-", text, "no_number"); return }
        // no SMS consent: nothing leaves the phone, the message is only kept in the log
        if (!consent.smsAllowed) { log.message(nowMs, eventId, "-", text, "no_consent"); return }
        for (n in numbers.filterNot(consent::caregiverConfirmed)) log.message(nowMs, eventId, n, text, "not_confirmed")
        for (to in consent.recipients(numbers)) deliver(nowMs, eventId, to, text)
    }

    companion object {
        const val TRIES = 3
        const val RETRY_MS = 20_000L
        const val SENT_TIMEOUT_MS = 60_000L
    }
}

/**
 * Machine-readable end of every caregiver SMS, read by EpiProt in caregiver mode on the caregiver's phone:
 * A seizure alarm, F false alarm, E emergency (> 5 min), N no answer after the seizure, H handover, I introduction,
 * S the patient pressed "Call for help" on the watch.
 * Same table in caregiver/CaregiverSms.kt (caregiver mode of this app).
 */
object CaregiverTag {
    const val INTRO = "[EP:I]"
    fun of(kind: CaregiverMessage) = when (kind) {
        CaregiverMessage.SEIZURE_ALERT -> "[EP:A]"
        CaregiverMessage.FALSE_ALARM -> "[EP:F]"
        CaregiverMessage.EMERGENCY -> "[EP:E]"
        CaregiverMessage.NO_ANSWER -> "[EP:N]"
        CaregiverMessage.HANDOVER -> "[EP:H]"
        CaregiverMessage.SOS -> "[EP:S]"
    }
}

/** Kept apart so the messenger has no direct dependency on the service package. */
private object PhoneAlertsBridge {
    fun smsFailed(c: Context, to: String) = org.epiprot.phone.service.PhoneAlerts.smsFailed(c, to)
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

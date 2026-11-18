package org.epiprot.watch.link

import android.content.Context
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.tasks.await
import org.epiprot.watch.EpiProtApp
import org.epiprot.watch.core.BackupBuffer
import org.epiprot.watch.protocol.PHONE_CAPABILITY
import org.epiprot.watch.protocol.Paths

/**
 * Connection to the EpiProt phone app over the Wear OS Data Layer (Bluetooth, or Wi-Fi when available).
 * If the phone is not reachable, sensor data and PIN results are kept (last ~10 minutes) and sent first
 * when the connection comes back.
 */
class PhoneLink(context: Context) {
    private val messages = Wearable.getMessageClient(context)
    private val capabilities = Wearable.getCapabilityClient(context)
    private val backup = BackupBuffer<Pair<String, ByteArray>>(capacity = 650)   // 600 s of sensor data + spare
    private val mutex = Mutex()

    @Volatile
    private var phoneNodeId: String? = null
    private val _connected = MutableStateFlow(false)
    val connected: StateFlow<Boolean> = _connected

    val backlog: Int get() = backup.size

    /** Looks up the phone running the EpiProt app (declares the "epiprot_phone" capability). */
    suspend fun refresh() {
        val node = try {
            val info = capabilities.getCapability(PHONE_CAPABILITY, CapabilityClient.FILTER_REACHABLE).await()
            info.nodes.firstOrNull { it.isNearby } ?: info.nodes.firstOrNull()
        } catch (e: Exception) {
            null
        }
        phoneNodeId = node?.id
        _connected.value = node != null
        if (node != null) send(null, null)   // flush the backlog
    }

    /**
     * Sends a message. With [keepIfOffline] the message is kept and sent later when the phone is not
     * reachable (sensor data, PIN results); status messages are simply dropped.
     */
    suspend fun send(path: String?, data: ByteArray?, keepIfOffline: Boolean = true) = mutex.withLock {
        val node = phoneNodeId
        if (node == null) {
            if (path != null && data != null && keepIfOffline) backup.add(path to data)
            return@withLock
        }
        try {
            while (true) {
                val item = backup.peek() ?: break
                messages.sendMessage(node, item.first, item.second).await()
                backup.removeFirst()
            }
            if (path != null && data != null) messages.sendMessage(node, path, data).await()
        } catch (e: Exception) {
            if (path != null && data != null && keepIfOffline) backup.add(path to data)
            phoneNodeId = null
            _connected.value = false
        }
    }
}

/** Receives the phone's messages (alarm, check-in, sensor warnings, settings) and hands them to the controller. */
class PhoneListenerService : WearableListenerService() {
    override fun onMessageReceived(event: MessageEvent) {
        if (!event.path.startsWith(Paths.PREFIX)) return
        EpiProtApp.controller(this).onPhoneMessage(event.path, event.data)
    }
}

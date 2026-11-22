package org.epiprot.phone.headband

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import android.util.Log
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

/**
 * Bluetooth LE connection to the headband (device-firmware/PROTOCOL.md): find it by its service,
 * connect, ask for 247-byte packets, read the device info, switch on the data notifications,
 * confirm received packets (ACK) and reconnect by itself when the link drops.
 *
 * Pairing ([pair]) bonds with the headband: Android shows its own dialog where the patient types the
 * 6-digit passkey from the user manual (LE Secure Connections, PROTOCOL.md). After that the bonded
 * band is reconnected by itself. [connectWithoutPasskey] skips bonding: only for the second-phone test
 * headband, which cannot bond reliably.
 */
@SuppressLint("MissingPermission")     // the caller checks BLUETOOTH_SCAN / BLUETOOTH_CONNECT
class HeadbandLink(private val ctx: Context, private val listener: Listener) {
    enum class State { IDLE, SCANNING, PAIRING, CONNECTING, CONNECTED, RECONNECTING }

    interface Listener {
        fun onInfo(info: HeadbandProtocol.DeviceInfo, address: String)
        fun onPacket(arrivalMs: Long, bytes: ByteArray)
        fun onState(state: State)
        /** Pairing finished: [ok] = bonded (passkey right), false = cancelled, wrong passkey or not found. */
        fun onPairResult(ok: Boolean, address: String?) {}
    }

    private val main = Handler(Looper.getMainLooper())
    private val adapter get() = ctx.getSystemService(BluetoothManager::class.java)?.adapter
    private var gatt: BluetoothGatt? = null
    private var device: BluetoothDevice? = null
    private var wanted = false
    private var pairing = false
    var state = State.IDLE
        private set

    fun connect(address: String?) {
        wanted = true
        val a = adapter ?: return set(State.IDLE)
        if (address != null) open(a.getRemoteDevice(address)) else scan()
        main.removeCallbacks(watchdog)
        main.postDelayed(watchdog, WATCHDOG_MS)
    }

    private var lastAttemptMs = 0L
    /** Last packet from the headband: a link that looks connected but brings nothing is restarted (see watchdog). */
    @Volatile private var lastPacketMs = 0L
    private var failedAttempts = 0

    /**
     * Keeps trying until the headband is back: after Bluetooth was switched off, or the headband was
     * out of range, a single reconnect attempt fails and Android does not call back again.
     */
    private val watchdog = object : Runnable {
        override fun run() {
            if (!wanted) return
            val d = device
            val now = System.currentTimeMillis()
            // connected but silent (the headband restarted without the link noticing): start over
            if (state == State.CONNECTED && lastPacketMs > 0 && now - lastPacketMs > SILENT_MS) {
                Log.w(TAG, "connected but no data for ${(now - lastPacketMs) / 1000} s: reconnecting")
                lastPacketMs = 0
                gatt?.let { try { it.disconnect(); it.close() } catch (e: Exception) { } }
                gatt = null
                set(State.RECONNECTING)
                lastAttemptMs = 0
            }
            if (state != State.CONNECTED && state != State.SCANNING && state != State.PAIRING && adapter?.isEnabled == true && now - lastAttemptMs > RETRY_MS) {
                gatt?.let { try { it.close() } catch (e: Exception) { } }
                gatt = null
                failedAttempts++
                // the remembered address can be out of date (a device that changes its Bluetooth address):
                // after two failed attempts, look for the headband service again
                if (d == null || failedAttempts > 2) { failedAttempts = 0; scan() }
                else { set(State.RECONNECTING); open(d) }
            }
            main.postDelayed(this, WATCHDOG_MS)
        }
    }

    /** First use: find the headband (its button held for 2 s) and bond with the passkey. */
    fun pair() {
        pairing = true
        connect(null)
    }

    /** Test headband only: connect without bonding. */
    fun connectWithoutPasskey() {
        pairing = false
        connect(null)
    }

    /**
     * Switch the headband off (command 0x08). The phone keeps looking for it in the background, so it
     * connects by itself as soon as the patient switches it on again (off the charger / button).
     */
    fun powerOff() {
        write(byteArrayOf(0x08))
        main.postDelayed({ gatt?.disconnect() }, 400)
    }

    /** Unpair: the headband forgets this phone (0x09), the phone forgets the headband. */
    fun unpair() {
        val d = device
        write(byteArrayOf(0x09))
        main.postDelayed({
            disconnect()
            d?.let { try { it.javaClass.getMethod("removeBond").invoke(it) } catch (e: Exception) { Log.w(TAG, "removeBond", e) } }
            device = null
        }, 400)
    }

    fun disconnect() {
        wanted = false
        pairing = false
        stopScan()
        main.removeCallbacksAndMessages(null)
        gatt?.disconnect(); gatt?.close(); gatt = null
        set(State.IDLE)
    }

    /** Tell the headband everything up to [seq] arrived, so it may free it (rule P4). */
    fun sendAck(seq: Long) = write(byteArrayOf(0x03) + u32(seq))

    /** Measure the pads' contact now (e.g. right after new pads). */
    fun requestContactCheck() = write(byteArrayOf(0x07))

    /** "Find my headband": its light flashes white for 5 s (IDENTIFY). */
    fun identify() = write(byteArrayOf(0x05))

    // ------------------------------------------------------------------ scanning

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            stopScan()
            val d = result.device
            if (pairing && d.bondState != BluetoothDevice.BOND_BONDED) bond(d) else open(d)
        }
        override fun onScanFailed(errorCode: Int) { Log.w(TAG, "scan failed $errorCode"); set(State.IDLE) }
    }

    private fun scan() {
        val scanner = adapter?.bluetoothLeScanner ?: return set(State.IDLE)
        set(State.SCANNING)
        scanner.startScan(listOf(ScanFilter.Builder().setServiceUuid(ParcelUuid(SERVICE)).build()),
            ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), scanCallback)
        main.postDelayed({
            if (state == State.SCANNING) {
                stopScan()
                if (pairing) { listener.onPairResult(false, null); disconnect() }     // no headband in pairing mode found
                else { set(if (wanted) State.RECONNECTING else State.IDLE); lastAttemptMs = System.currentTimeMillis() }
            }
        }, SCAN_TIMEOUT_MS)
    }

    private fun stopScan() {
        try { adapter?.bluetoothLeScanner?.stopScan(scanCallback) } catch (e: Exception) { }
    }

    // ------------------------------------------------------------------ pairing (bonding)

    private var bondReceiver: BroadcastReceiver? = null
    /** The connection whose services are being discovered (only once per connection). */
    @Volatile private var discovering: BluetoothGatt? = null

    private fun bond(d: BluetoothDevice) {
        device = d
        set(State.PAIRING)
        main.removeCallbacks(watchdog)                    // the patient is typing the passkey: no retries now
        val r = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) {
                @Suppress("DEPRECATION") val dev = i.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE)
                if (dev?.address != d.address) return
                when (i.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, BluetoothDevice.BOND_NONE)) {
                    BluetoothDevice.BOND_BONDED -> { endBond(); pairing = false; listener.onPairResult(true, d.address)
                        open(d); main.postDelayed(watchdog, WATCHDOG_MS) }
                    BluetoothDevice.BOND_NONE -> { endBond(); listener.onPairResult(false, null); disconnect() }
                }
            }
        }
        bondReceiver = r
        androidx.core.content.ContextCompat.registerReceiver(ctx, r, IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED),
            androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED)      // system broadcast: still delivered
        if (!d.createBond()) { endBond(); listener.onPairResult(false, null); disconnect() }
        else main.postDelayed(bondTimeout, BOND_TIMEOUT_MS)
    }

    /** The passkey box never appeared or nobody answered: give up instead of waiting forever ("try again"). */
    private val bondTimeout = Runnable {
        if (bondReceiver != null) { endBond(); listener.onPairResult(false, null); disconnect() }
    }

    private fun endBond() {
        main.removeCallbacks(bondTimeout)
        bondReceiver?.let { try { ctx.unregisterReceiver(it) } catch (e: Exception) { } }
        bondReceiver = null
    }

    // ------------------------------------------------------------------ connection

    private fun open(d: BluetoothDevice) {
        device = d
        lastAttemptMs = System.currentTimeMillis()
        if (state != State.RECONNECTING) set(State.CONNECTING)
        gatt = try { d.connectGatt(ctx, false, callback, BluetoothDevice.TRANSPORT_LE) } catch (e: Exception) { null }
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                failedAttempts = 0
                discovering = null
                g.requestMtu(MTU)
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                g.close()
                if (gatt == g) gatt = null
                if (wanted) {           // the headband keeps measuring and sends the stored data when back
                    set(State.RECONNECTING)
                    main.postDelayed({ device?.let { if (wanted && gatt == null) open(it) } }, RECONNECT_DELAY_MS)
                } else set(State.IDLE)
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            Log.i(TAG, "MTU $mtu")
            // some phones report the MTU twice: a second service discovery would cancel the first one's read
            if (discovering === g) return
            discovering = g
            g.discoverServices()
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            val info = g.getService(SERVICE)?.getCharacteristic(INFO)
            if (info == null) { Log.w(TAG, "not an EpiProt headband"); g.disconnect(); return }
            if (!g.readCharacteristic(info)) main.postDelayed({ if (gatt === g) g.readCharacteristic(info) }, 300)   // busy: once more
        }

        @Deprecated("API < 33")
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            @Suppress("DEPRECATION") onRead(g, c, c.value ?: ByteArray(0))
        }

        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray, status: Int) =
            onRead(g, c, value)

        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, status: Int) {
            g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_BALANCED)
            set(State.CONNECTED)
        }

        @Deprecated("API < 33")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION") if (c.uuid == DATA) { lastPacketMs = System.currentTimeMillis(); listener.onPacket(lastPacketMs, c.value ?: return) }
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) {
            if (c.uuid == DATA) { lastPacketMs = System.currentTimeMillis(); listener.onPacket(lastPacketMs, value) }
        }
    }

    private fun onRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) {
        if (c.uuid != INFO) return
        val info = try { HeadbandProtocol.DeviceInfo.decode(value) } catch (e: Exception) {
            Log.w(TAG, "headband refused: ${e.message}"); g.disconnect(); return      // unknown protocol version
        }
        listener.onInfo(info, g.device.address)
        val data = g.getService(SERVICE).getCharacteristic(DATA)
        g.setCharacteristicNotification(data, true)
        val cccd = data.getDescriptor(CCCD)
        if (Build.VERSION.SDK_INT >= 33) g.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
        else @Suppress("DEPRECATION") { cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE; g.writeDescriptor(cccd) }
    }

    private fun write(bytes: ByteArray) {
        val g = gatt ?: return
        if (state != State.CONNECTED) return
        val c = g.getService(SERVICE)?.getCharacteristic(CONTROL) ?: return
        if (Build.VERSION.SDK_INT >= 33) g.writeCharacteristic(c, bytes, BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE)
        else @Suppress("DEPRECATION") {
            c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE; c.value = bytes; g.writeCharacteristic(c)
        }
    }

    private fun set(s: State) { state = s; listener.onState(s) }

    private fun u32(v: Long) = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(v.toInt()).array()

    companion object {
        private const val TAG = "EpiProtHeadband"
        private const val BASE = "-279b-48d0-a8ab-c8630521d53c"
        val SERVICE: UUID = UUID.fromString("e0b10001$BASE")
        val DATA: UUID = UUID.fromString("e0b10002$BASE")
        val CONTROL: UUID = UUID.fromString("e0b10003$BASE")
        val INFO: UUID = UUID.fromString("e0b10004$BASE")
        val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        const val MTU = 247
        const val SCAN_TIMEOUT_MS = 30_000L
        const val RECONNECT_DELAY_MS = 2_000L
        const val BOND_TIMEOUT_MS = 90_000L
        const val SILENT_MS = 15_000L          // the headband sends a status packet every second at least
        const val WATCHDOG_MS = 5_000L
        const val RETRY_MS = 12_000L          // a connection attempt that has not finished by then is restarted
    }
}

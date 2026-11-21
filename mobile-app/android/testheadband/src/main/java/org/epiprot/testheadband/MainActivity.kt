package org.epiprot.testheadband

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattServer
import android.bluetooth.BluetoothGattServerCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.ArrayDeque
import java.util.UUID
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit

/**
 * Test headband on a second Android device (device-firmware/PROTOCOL.md): advertises the EpiProt
 * headband service over real Bluetooth LE and streams the virtual-headband demo (headband_demo.ehb, a
 * real SeizeIT2 seizure through the simulated headband) in real time.
 *
 * Like the designed headband it keeps "measuring" while no phone is subscribed, stores those packets
 * (up to ~8 MB) and sends them with the catch-up flag when the phone is back.
 * Test deviation: no bonding / encryption.
 */
@SuppressLint("MissingPermission")
class MainActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private var server: BluetoothGattServer? = null
    private lateinit var dataChar: BluetoothGattCharacteristic
    @Volatile private var phone: BluetoothDevice? = null
    @Volatile private var subscribed = false
    @Volatile private var mtu = 23
    @Volatile private var running = false
    private var streamThread: Thread? = null
    private val sent = Semaphore(0)

    // counters shown on screen
    @Volatile private var live = 0; @Volatile private var stored = 0; @Volatile private var catchUp = 0
    @Volatile private var dropped = 0; @Volatile private var acks = 0; @Volatile private var lastAck = -1L
    @Volatile private var streamS = 0.0; @Volatile private var advertising = "–"; @Volatile private var onsetIn = 0.0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(40, 60, 40, 40) }
        col.addView(TextView(this).apply { text = "EpiProt Test Headband"; textSize = 22f; setTypeface(null, Typeface.BOLD) })
        col.addView(TextView(this).apply {
            text = "Advertises the headband service and plays a real recorded seizure (SeizeIT2 sub-058) as headband packets. " +
                "On the EpiProt phone: Start monitoring, then Settings → Headband → Connect headband."
            textSize = 13f; setPadding(0, 10, 0, 20)
        })
        status = TextView(this).apply { textSize = 15f; typeface = Typeface.MONOSPACE }
        val start8 = Button(this).apply { text = "Start (seizure in ~2 min)"; setOnClickListener { begin(480.0) } }
        val start0 = Button(this).apply { text = "Start from the beginning (seizure in 10 min)"; setOnClickListener { begin(0.0) } }
        val stop = Button(this).apply { text = "Stop"; setOnClickListener { end() } }
        col.addView(start8); col.addView(start0); col.addView(stop); col.addView(status)
        setContentView(col)
        askPermissions()
        tick()
    }

    override fun onDestroy() { end(); super.onDestroy() }

    private fun askPermissions() {
        if (Build.VERSION.SDK_INT >= 31) {
            val need = listOf(Manifest.permission.BLUETOOTH_ADVERTISE, Manifest.permission.BLUETOOTH_CONNECT)
                .filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
            if (need.isNotEmpty()) requestPermissions(need.toTypedArray(), 1)
        }
    }

    private fun tick() {
        status.text = buildString {
            appendLine("advertising : $advertising")
            appendLine("phone       : ${phone?.address ?: "–"}")
            appendLine("MTU         : $mtu ${if (mtu < 211) "(EEG packets need 211+)" else "ok"}")
            appendLine("subscribed  : $subscribed")
            appendLine("stream time : %.0f s  (seizure %s)".format(streamS, if (onsetIn > 0) "in %.0f s".format(onsetIn) else "now / past"))
            appendLine("live sent   : $live")
            appendLine("stored now  : $stored")
            appendLine("catch-up    : $catchUp")
            appendLine("dropped     : $dropped")
            appendLine("ACKs        : $acks (last seq $lastAck)")
        }
        main.postDelayed({ tick() }, 500)
    }

    // ------------------------------------------------------------------ GATT server + advertising

    private fun begin(startS: Double) {
        if (running) return
        val bm = getSystemService(BluetoothManager::class.java)
        val s = bm.openGattServer(this, gattCallback) ?: run { advertising = "no GATT server"; return }
        server = s
        val svc = BluetoothGattService(SERVICE, BluetoothGattService.SERVICE_TYPE_PRIMARY)
        dataChar = BluetoothGattCharacteristic(DATA, BluetoothGattCharacteristic.PROPERTY_NOTIFY, BluetoothGattCharacteristic.PERMISSION_READ)
        dataChar.addDescriptor(BluetoothGattDescriptor(CCCD, BluetoothGattDescriptor.PERMISSION_READ or BluetoothGattDescriptor.PERMISSION_WRITE))
        svc.addCharacteristic(dataChar)
        svc.addCharacteristic(BluetoothGattCharacteristic(CONTROL,
            BluetoothGattCharacteristic.PROPERTY_WRITE or BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE,
            BluetoothGattCharacteristic.PERMISSION_WRITE))
        svc.addCharacteristic(BluetoothGattCharacteristic(INFO, BluetoothGattCharacteristic.PROPERTY_READ, BluetoothGattCharacteristic.PERMISSION_READ))
        s.addService(svc)
        bm.adapter.bluetoothLeAdvertiser?.startAdvertising(
            AdvertiseSettings.Builder().setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
                .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM).setConnectable(true).build(),
            AdvertiseData.Builder().addServiceUuid(ParcelUuid(SERVICE)).setIncludeDeviceName(false).build(),
            advertiseCallback) ?: run { advertising = "this device cannot advertise" }
        running = true
        streamThread = Thread { stream(startS) }.also { it.start() }
    }

    private fun end() {
        running = false
        streamThread?.interrupt()
        try { getSystemService(BluetoothManager::class.java).adapter.bluetoothLeAdvertiser?.stopAdvertising(advertiseCallback) } catch (e: Exception) { }
        server?.close(); server = null
        phone = null; subscribed = false
        advertising = "stopped"
    }

    private val advertiseCallback = object : AdvertiseCallback() {
        override fun onStartSuccess(settingsInEffect: AdvertiseSettings) { advertising = "on" }
        override fun onStartFailure(errorCode: Int) { advertising = "failed ($errorCode)" }
    }

    private var info: ByteArray = ByteArray(0)

    private val gattCallback = object : BluetoothGattServerCallback() {
        override fun onConnectionStateChange(device: BluetoothDevice, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) phone = device
            else if (device == phone) { phone = null; subscribed = false; mtu = 23 }
        }
        override fun onMtuChanged(device: BluetoothDevice, m: Int) { mtu = m }
        override fun onCharacteristicReadRequest(device: BluetoothDevice, requestId: Int, offset: Int, c: BluetoothGattCharacteristic) {
            val v = if (c.uuid == INFO) info else ByteArray(0)
            server?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, v.copyOfRange(minOf(offset, v.size), v.size))
        }
        override fun onCharacteristicWriteRequest(device: BluetoothDevice, requestId: Int, c: BluetoothGattCharacteristic,
                                                  preparedWrite: Boolean, responseNeeded: Boolean, offset: Int, value: ByteArray) {
            if (c.uuid == CONTROL && value.isNotEmpty() && value[0].toInt() == 0x03 && value.size >= 5) {
                acks++; lastAck = ByteBuffer.wrap(value, 1, 4).order(ByteOrder.LITTLE_ENDIAN).int.toLong() and 0xFFFFFFFFL
            }
            if (responseNeeded) server?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, null)
        }
        override fun onDescriptorWriteRequest(device: BluetoothDevice, requestId: Int, d: BluetoothGattDescriptor,
                                              preparedWrite: Boolean, responseNeeded: Boolean, offset: Int, value: ByteArray) {
            if (d.uuid == CCCD) subscribed = value.contentEquals(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
            if (responseNeeded) server?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, null)
        }
        override fun onNotificationSent(device: BluetoothDevice, status: Int) { sent.release() }
    }

    // ------------------------------------------------------------------ stream

    private fun stream(startS: Double) {
        val data = assets.open("headband_demo.ehb").readBytes()
        val bb = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        val n = bb.getInt(4)
        val meta = JSONObject(String(data, 8, n, Charsets.UTF_8))
        info = meta.getString("device_info").chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        val onset = meta.optDouble("onset_s", 600.0)
        val store = ArrayDeque<ByteArray>()
        var storeBytes = 0
        val t0 = System.nanoTime()
        var o = 8 + n
        try {
            while (running && o + 6 <= data.size) {
                val ms = bb.getInt(o).toLong() and 0xFFFFFFFFL
                val len = bb.getShort(o + 4).toInt() and 0xFFFF
                val pkt = data.copyOfRange(o + 6, o + 6 + len)
                o += 6 + len
                if (ms < startS * 1000) continue
                val due = (ms / 1000.0 - startS) * 1e9
                val wait = (due - (System.nanoTime() - t0)) / 1e6
                if (wait > 0) Thread.sleep(wait.toLong())
                if ((ms / 1000).toInt() != streamS.toInt()) android.util.Log.i("EpiProtTestHB", "stream_s=${ms / 1000} onset_s=$onset subscribed=$subscribed stored=${store.size}")
                streamS = ms / 1000.0
                onsetIn = onset - streamS
                val dev = phone
                if (dev != null && subscribed) {
                    var k = 0
                    while (k < CATCHUP_PER_LIVE && store.isNotEmpty()) {
                        val s = store.removeFirst(); storeBytes -= s.size
                        s[1] = (s[1].toInt() or 0x01).toByte()          // catch-up flag
                        if (notify(dev, s)) catchUp++
                        k++
                    }
                    if (notify(dev, pkt)) live++
                } else {
                    store.addLast(pkt); storeBytes += pkt.size
                    while (storeBytes > STORE_BYTES) { storeBytes -= store.removeFirst().size; dropped++ }
                }
                stored = store.size
            }
        } catch (e: InterruptedException) { }
    }

    /** One notification at a time: Android sends the next only after onNotificationSent. */
    private fun notify(dev: BluetoothDevice, value: ByteArray): Boolean {
        val s = server ?: return false
        sent.drainPermits()
        val ok = if (Build.VERSION.SDK_INT >= 33) s.notifyCharacteristicChanged(dev, dataChar, false, value) == BluetoothGatt.GATT_SUCCESS
        else @Suppress("DEPRECATION") { dataChar.value = value; s.notifyCharacteristicChanged(dev, dataChar, false) }
        if (ok) sent.tryAcquire(200, TimeUnit.MILLISECONDS)
        return ok
    }

    companion object {
        private const val BASE = "-279b-48d0-a8ab-c8630521d53c"
        val SERVICE: UUID = UUID.fromString("e0b10001$BASE")
        val DATA: UUID = UUID.fromString("e0b10002$BASE")
        val CONTROL: UUID = UUID.fromString("e0b10003$BASE")
        val INFO: UUID = UUID.fromString("e0b10004$BASE")
        val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        const val CATCHUP_PER_LIVE = 8
        const val STORE_BYTES = 8 * 1024 * 1024
    }
}

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
    private lateinit var band: HeadbandView
    private var sentLastS = 0; private var sentAtTick = 0
    private var server: BluetoothGattServer? = null
    private lateinit var dataChar: BluetoothGattCharacteristic
    @Volatile private var phone: BluetoothDevice? = null
    @Volatile private var subscribed = false
    @Volatile private var mtu = 23
    /** "On the charger": status packets say so and the band stops measuring (EEG off on the charger, PROTOCOL.md). */
    @Volatile private var onCharger = false
    private var seqOut = 0L
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
        actionBar?.hide()
        if (Build.VERSION.SDK_INT >= 30) window.decorView.post {      // full screen for recordings
            window.insetsController?.hide(android.view.WindowInsets.Type.systemBars())
            window.insetsController?.systemBarsBehavior = android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        // presentation view on top (X-ray render + live signals), test controls and counters below
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(android.graphics.Color.rgb(16, 20, 28)) }
        band = HeadbandView(this)
        col.addView(band, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(20, 0, 20, 0) }
        val start8 = Button(this).apply { text = "Start · 2 min"; setOnClickListener { begin(480.0) } }
        val start0 = Button(this).apply { text = "Start · 10 min"; setOnClickListener { begin(0.0) } }
        val stop = Button(this).apply { text = "Stop"; setOnClickListener { end() } }
        val details = Button(this).apply { text = "Details" }
        val charger = Button(this).apply { text = "Charger: off" }
        charger.setOnClickListener { onCharger = !onCharger; charger.text = if (onCharger) "Charger: on" else "Charger: off" }
        for (b in listOf(start8, start0, stop, charger, details)) b.isAllCaps = false
        for (b in listOf(start8, start0, stop, charger, details)) buttons.addView(b, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        col.addView(buttons)
        status = TextView(this).apply {
            textSize = 12f; typeface = Typeface.MONOSPACE; setTextColor(android.graphics.Color.LTGRAY)
            setPadding(30, 0, 30, 20); visibility = android.view.View.GONE
        }
        details.setOnClickListener { status.visibility = if (status.visibility == android.view.View.GONE) android.view.View.VISIBLE else android.view.View.GONE }
        col.addView(status)
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
        band.running = running
        band.sending = running && phone != null && subscribed
        band.onsetIn = onsetIn
        if (++sentAtTick % 2 == 0) { band.packetsPerS = live + catchUp - sentLastS; sentLastS = live + catchUp }
        main.postDelayed({ tick() }, 500)
    }

    // ------------------------------------------------------------------ GATT server + advertising

    private fun begin(startS: Double) {
        if (running) return
        band.off = null
        val bm = getSystemService(BluetoothManager::class.java)
        val s = bm?.adapter?.let { bm.openGattServer(this, gattCallback) }
        if (s == null) {              // no Bluetooth (e.g. emulator): still "measure" and store, so the view can be shown
            advertising = "no GATT server"
            running = true
            streamThread = Thread { stream(startS) }.also { it.start() }
            return
        }
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
        // like the real band switching off: drop the link, so the phone notices at once
        phone?.let { d -> try { server?.cancelConnection(d) } catch (e: Exception) { } }
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
            if (c.uuid == CONTROL && value.isNotEmpty()) when (value[0].toInt()) {
                0x05 -> band.identifyUntil = System.currentTimeMillis() + 5000          // IDENTIFY: blink 5 s
                0x08 -> main.postDelayed({ end(); band.off = if (tr) "kapatıldı (uygulamadan)" else "switched off from the app" }, 300)
                0x09 -> main.postDelayed({ end(); band.off = if (tr) "eşleştirme kaldırıldı, kapandı" else "unpaired, switched off" }, 300)
            }
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
                if (onCharger) {
                    if (pkt[0].toInt() != 0x03) continue                       // no EEG / movement on the charger
                    pkt[13] = (pkt[13].toInt() or 0x03).toByte()               // charging + charger attached
                }
                // own packet numbers, so packets the band does not make (EEG on the charger) leave no gap (PROTOCOL.md seq)
                ByteBuffer.wrap(pkt).order(ByteOrder.LITTLE_ENDIAN).putInt(2, (seqOut++).toInt())
                band.packet(pkt)
                band.charging = onCharger
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

    private val tr get() = java.util.Locale.getDefault().language == "tr"

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

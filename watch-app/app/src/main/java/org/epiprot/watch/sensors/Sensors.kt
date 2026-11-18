package org.epiprot.watch.sensors

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.SystemClock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.epiprot.watch.core.SensorBatcher
import kotlin.math.PI
import kotlin.math.sin
import kotlin.random.Random

interface SensorSource {
    /** true when real heart-rate, accelerometer and gyroscope sensors are used. */
    val isReal: Boolean
    val onBody: Boolean?
    fun start()
    fun stop()
}

/**
 * Real watch sensors: heart rate (~1 Hz), accelerometer and gyroscope (25 Hz, delivered in 1 s batches so the
 * processor can sleep in between), and off-body detection where available.
 */
class DeviceSensors(context: Context, private val batcher: SensorBatcher) : SensorSource, SensorEventListener {
    private val sm = context.getSystemService(SensorManager::class.java)
    private val heart = sm.getDefaultSensor(Sensor.TYPE_HEART_RATE)
    private val acc = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyr = sm.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    private val offBody = sm.getDefaultSensor(Sensor.TYPE_LOW_LATENCY_OFFBODY_DETECT)

    override val isReal: Boolean get() = heart != null && acc != null

    @Volatile
    override var onBody: Boolean? = null
        private set

    override fun start() {
        val periodUs = 40_000          // 25 Hz
        val batchUs = 1_000_000        // deliver once per second
        heart?.let { sm.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL) }
        acc?.let { sm.registerListener(this, it, periodUs, batchUs) }
        gyr?.let { sm.registerListener(this, it, periodUs, batchUs) }
        offBody?.let { sm.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL) }
    }

    override fun stop() = sm.unregisterListener(this)

    override fun onSensorChanged(e: SensorEvent) {
        // event timestamps are elapsed-realtime nanoseconds -> convert to wall clock
        val tMs = System.currentTimeMillis() - (SystemClock.elapsedRealtimeNanos() - e.timestamp) / 1_000_000
        when (e.sensor.type) {
            Sensor.TYPE_HEART_RATE -> batcher.addHeartRate(
                tMs, e.values[0],
                reliable = e.accuracy != SensorManager.SENSOR_STATUS_NO_CONTACT &&
                    e.accuracy != SensorManager.SENSOR_STATUS_UNRELIABLE,
            )
            Sensor.TYPE_ACCELEROMETER -> batcher.addAcc(tMs, e.values[0], e.values[1], e.values[2])
            Sensor.TYPE_GYROSCOPE -> batcher.addGyr(tMs, e.values[0], e.values[1], e.values[2])
            Sensor.TYPE_LOW_LATENCY_OFFBODY_DETECT -> onBody = e.values[0] > 0.5f
        }
    }

    override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) = Unit
}

/**
 * Synthetic sensors for the emulator or a watch without a heart-rate sensor.
 * [shaking] produces 5 Hz convulsion-like movement and a rising heart rate (for demos).
 */
class SimulatedSensors(private val batcher: SensorBatcher, private val scope: CoroutineScope) : SensorSource {
    override val isReal = false
    override val onBody: Boolean? = true

    @Volatile
    var shaking = false
    private var job: Job? = null

    override fun start() {
        job = scope.launch {
            var hr = 70f
            var t = 0.0
            while (isActive) {
                val now = System.currentTimeMillis()
                val amp = if (shaking) 12.0 else 0.3
                val wave = (amp * sin(2 * PI * 5.0 * t)).toFloat()
                batcher.addAcc(now, wave + noise(), noise(), 9.81f + noise())
                batcher.addGyr(now, if (shaking) wave / 4 else noise() / 10, noise() / 10, noise() / 10)
                if ((t * 25).toInt() % 25 == 0) {
                    hr += if (shaking) (150f - hr) * 0.08f else (70f - hr) * 0.03f
                    batcher.addHeartRate(now, hr + noise() * 2, reliable = true)
                }
                t += 0.04
                delay(40)
            }
        }
    }

    override fun stop() {
        job?.cancel()
    }

    private fun noise() = (Random.nextFloat() - 0.5f) * 0.2f
}

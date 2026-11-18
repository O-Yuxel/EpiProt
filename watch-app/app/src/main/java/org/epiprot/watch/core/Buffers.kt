package org.epiprot.watch.core

import org.epiprot.watch.protocol.Sample
import org.epiprot.watch.protocol.SensorBatch

/** Keeps the newest [capacity] items; the oldest are dropped when full. */
class BackupBuffer<T>(private val capacity: Int) {
    private val items = ArrayDeque<T>()

    val size: Int get() = items.size

    @Synchronized
    fun add(item: T) {
        if (items.size >= capacity) items.removeFirst()
        items.addLast(item)
    }

    @Synchronized
    fun peek(): T? = items.firstOrNull()

    @Synchronized
    fun removeFirst(): T? = items.removeFirstOrNull()
}

/**
 * Collects raw sensor events and turns them into one [SensorBatch] per second.
 * Times are wall-clock milliseconds.
 */
class SensorBatcher(private val heartRateMaxAgeMs: Long = 5_000) {
    private var seq = 0
    private var heartRate = Float.NaN
    private var heartRateTimeMs = Long.MIN_VALUE
    private val acc = ArrayList<Pair<Long, FloatArray>>()
    private val gyr = ArrayList<Pair<Long, FloatArray>>()

    @Synchronized
    fun addHeartRate(tMs: Long, bpm: Float, reliable: Boolean) {
        if (reliable && bpm in 25f..250f) {
            heartRate = bpm
            heartRateTimeMs = tMs
        }
    }

    @Synchronized
    fun addAcc(tMs: Long, x: Float, y: Float, z: Float) {
        acc.add(tMs to floatArrayOf(x, y, z))
    }

    @Synchronized
    fun addGyr(tMs: Long, x: Float, y: Float, z: Float) {
        gyr.add(tMs to floatArrayOf(x, y, z))
    }

    /** Latest valid heart rate, or NaN when it is older than [heartRateMaxAgeMs]. */
    @Synchronized
    fun currentHeartRate(nowMs: Long): Float =
        if (nowMs - heartRateTimeMs <= heartRateMaxAgeMs) heartRate else Float.NaN

    @Synchronized
    fun flush(nowMs: Long, onBody: Boolean?): SensorBatch {
        val first = (acc.asSequence() + gyr.asSequence()).minOfOrNull { it.first }
        val start = minOf(first ?: (nowMs - 1000), nowMs)
        fun toSamples(src: List<Pair<Long, FloatArray>>) =
            src.sortedBy { it.first }.map { (t, v) -> Sample((t - start).toInt().coerceIn(0, 0xFFFF), v[0], v[1], v[2]) }
        val batch = SensorBatch(seq++, start, currentHeartRate(nowMs), onBody, toSamples(acc), toSamples(gyr))
        acc.clear()
        gyr.clear()
        return batch
    }
}

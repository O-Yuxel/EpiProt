package org.epiprot.phone.headband

import org.epiprot.phone.headband.HeadbandProtocol as P

/** Where the receiver hands the data. Live data go to detection, catch-up data to the diary. */
interface HeadbandSink {
    /** Live EEG: 4 channels x n samples in µV, starting at [firstMs] (phone clock); NaN = bad / not for the model. */
    fun eeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int)

    /** Live head movement, one sample: g and °/s. */
    fun movement(tMs: Double, accG: FloatArray, gyrDps: FloatArray)

    /** Stored data sent after a reconnect: too late for detection, kept for the event diary. */
    fun catchUp(packet: P.Packet, phoneMs: Double) {}

    /** Catch-up EEG (µV), for the model's memory of the recent past (HeadbandPipeline). */
    fun lateEeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) {}

    /** Catch-up head movement, one sample. */
    fun lateMovement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) {}
}

/** What the phone knows about the headband right now (for the status screen and the warnings). */
data class HeadbandState(
    val lastPacketMs: Long = 0,
    val batteryPct: Int = -1,
    val batteryMv: Int = 0,
    val charging: Boolean = false,
    val chargerAttached: Boolean = false,
    val streaming: Boolean = false,
    val lowBattery: Boolean = false,
    val errors: Int = 0,
    val leadOff: Int = 0,
    val impedanceKohm: IntArray? = null,
    val lastContactCheckMs: Long = 0,
    val unconfirmed: Long = 0,
    val received: Long = 0,
    val duplicates: Long = 0,
    val catchUp: Long = 0,
    val missing: Long = 0,
)

/**
 * Turns headband packets into samples on the phone's timeline (PROTOCOL.md):
 *  - packets received twice (lost confirmation) are dropped by sequence number (rule P4);
 *  - raw values are converted with the constants the headband reports (rule P1);
 *  - saturated samples and EEG measured during a contact check become NaN, never guessed (rule P2);
 *  - headband clock -> phone clock: the lowest arrival delay over the last 10 minutes
 *    (radio delay only adds time; the window follows the slow drift between the two crystals).
 */
class HeadbandReceiver(val info: P.DeviceInfo, private val sink: HeadbandSink) {
    var state = HeadbandState()
        private set

    private val seen = HashSet<Long>()
    private var maxSeq = -1L
    private var firstSeq = -1L
    private var lastRaw = -1L
    private var lastUnwrapped = 0L
    private val clock = SlidingMin(600_000.0)
    private var contiguous = -1L
    /** Catch-up packets that came before any live packet: the clock is not known yet, so they wait. */
    private val waiting = ArrayList<Pair<Long, ByteArray>>()

    /** Highest sequence number up to which every packet arrived: what the phone confirms (ACK). */
    fun ackSeq(): Long {
        if (firstSeq < 0) return -1
        if (contiguous < firstSeq - 1) contiguous = firstSeq - 1
        while (seen.contains(contiguous + 1)) contiguous++
        return contiguous
    }

    fun onPacket(arrivalMs: Long, bytes: ByteArray) {
        val p = P.decode(bytes)
        val catchUpFirst = p.flags and P.FLAG_CATCHUP != 0
        if (catchUpFirst && clock.isEmpty) {               // headband clock -> phone clock comes from live packets
            if (waiting.size < 100_000) waiting += arrivalMs to bytes
            return
        }
        if (!seen.add(p.seq)) { state = state.copy(duplicates = state.duplicates + 1); return }
        if (firstSeq < 0) firstSeq = p.seq
        if (p.seq > maxSeq) maxSeq = p.seq
        if (seen.size > 400_000) seen.removeAll { it < maxSeq - 300_000 }
        val tDevMs = unwrap(p.tDev) / P.TICKS_PER_S * 1000
        val catchUp = p.flags and P.FLAG_CATCHUP != 0
        if (!catchUp) {
            clock.add(arrivalMs.toDouble(), arrivalMs - tDevMs)
            if (waiting.isNotEmpty()) {                     // first live packet: now the stored ones can be placed
                val w = ArrayList(waiting); waiting.clear()
                for ((a, b) in w) onPacket(a, b)
            }
        }
        val phoneMs = tDevMs + clock.value
        state = state.copy(lastPacketMs = arrivalMs, received = state.received + 1,
            missing = maxSeq - firstSeq + 1 - (state.received + 1))
        if (catchUp) {
            state = state.copy(catchUp = state.catchUp + 1)
            sink.catchUp(p, phoneMs)
            when (p) {
                is P.Eeg -> sink.lateEeg(phoneMs, toMicrovolts(p), p.leadOff)
                is P.Mov -> for ((i, r) in p.raw.withIndex()) sink.lateMovement(phoneMs + i * 1000.0 / info.movRate,
                    FloatArray(3) { r[it] / info.accLsbPerG.toFloat() }, FloatArray(3) { r[3 + it] / info.gyrLsbPerDps })
                else -> {}
            }
            return
        }
        when (p) {
            is P.Eeg -> sink.eeg(phoneMs, toMicrovolts(p), p.leadOff)
            is P.Mov -> for ((i, r) in p.raw.withIndex()) {
                val acc = FloatArray(3) { r[it] / info.accLsbPerG.toFloat() }
                val gyr = FloatArray(3) { r[3 + it] / info.gyrLsbPerDps }
                sink.movement(phoneMs + i * 1000.0 / info.movRate, acc, gyr)
            }
            is P.Status -> state = state.copy(batteryPct = p.batteryPct, batteryMv = p.batteryMv,
                charging = p.state and P.ST_CHARGING != 0, chargerAttached = p.state and P.ST_CHARGER != 0,
                streaming = p.state and P.ST_STREAMING != 0, lowBattery = p.state and P.ST_LOW_BATTERY != 0,
                errors = p.errors, leadOff = p.leadOff, unconfirmed = p.unconfirmed)
            is P.Contact -> state = state.copy(impedanceKohm = p.impedanceKohm, lastContactCheckMs = arrivalMs)
        }
    }

    /** µV per channel; saturated codes and contact-check samples are NaN. */
    fun toMicrovolts(p: P.Eeg): Array<FloatArray> {
        val n = p.codes.size
        val k = info.eegLsbNv / 1000f
        val check = p.flags and P.FLAG_CONTACT_CHECK != 0
        return Array(P.EEG_CH) { c ->
            FloatArray(n) { i ->
                val v = p.codes[i][c]
                if (check || v <= P.INT24_MIN || v >= P.INT24_MAX) Float.NaN else v * k
            }
        }
    }

    /** 32-bit headband clock ticks -> continuous ticks (wraps every 36 h); also for older catch-up packets. */
    private fun unwrap(raw: Long): Long {
        if (lastRaw < 0) { lastRaw = raw; lastUnwrapped = raw; return raw }
        var d = raw - lastRaw
        if (d > 1L shl 31) d -= 1L shl 32
        if (d < -(1L shl 31)) d += 1L shl 32
        val u = lastUnwrapped + d
        if (d > 0) { lastRaw = raw; lastUnwrapped = u }
        return u
    }

    /** Minimum of the values added during the last [windowMs]. */
    private class SlidingMin(private val windowMs: Double) {
        private val q = ArrayDeque<Pair<Double, Double>>()
        val value: Double get() = q.firstOrNull()?.second ?: 0.0
        val isEmpty: Boolean get() = q.isEmpty()
        fun add(t: Double, v: Double) {
            while (q.isNotEmpty() && q.last().second >= v) q.removeLast()
            q.addLast(t to v)
            while (q.first().first < t - windowMs) q.removeFirst()
        }
    }
}

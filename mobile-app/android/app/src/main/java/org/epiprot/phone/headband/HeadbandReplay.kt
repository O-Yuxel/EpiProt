package org.epiprot.phone.headband

import org.epiprot.phone.engine.WindowAssembler
import org.epiprot.phone.model.WindowInput
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.roundToLong
import org.epiprot.phone.headband.HeadbandProtocol as P

/**
 * A recorded headband stream (.ehb, written by the Python simulator, mobile-app/src/epiprot/headband):
 * b"EHB1", u32 JSON length, JSON metadata, then (u32 arrival ms, u16 length, packet bytes).
 */
class HeadbandStream(val meta: JSONObject, val info: P.DeviceInfo, val records: List<Pair<Long, ByteArray>>) {
    companion object {
        fun parse(data: ByteArray): HeadbandStream {
            require(data.size > 8 && String(data, 0, 4, Charsets.US_ASCII) == "EHB1") { "not a headband stream" }
            val bb = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
            val n = bb.getInt(4)
            val meta = JSONObject(String(data, 8, n, Charsets.UTF_8))
            val info = P.DeviceInfo.decode(meta.getString("device_info").chunked(2).map { it.toInt(16).toByte() }.toByteArray())
            val out = ArrayList<Pair<Long, ByteArray>>()
            var o = 8 + n
            while (o + 6 <= data.size) {
                val ms = bb.getInt(o).toLong() and 0xFFFFFFFFL
                val len = bb.getShort(o + 4).toInt() and 0xFFFF
                out += ms to data.copyOfRange(o + 6, o + 6 + len)
                o += 6 + len
            }
            return HeadbandStream(meta, info, out)
        }
    }
}

/**
 * Plays a recorded stream through the same receiver and window assembler the live headband uses:
 * yields every headband state change (status, contact check) and every finished 5 s window, in order.
 * Times are the stream's own (arrival ms + [baseMs]); the caller decides how fast to go.
 */
class HeadbandReplay(private val stream: HeadbandStream, private val baseMs: Long = 1_000_000_000L) {
    sealed interface Step {
        data class State(val state: HeadbandState) : Step
        class Window(val input: WindowInput) : Step
    }

    var catchUp = 0
        private set

    fun steps(): Sequence<Step> = sequence {
        var asm: WindowAssembler? = null
        val sink = object : HeadbandSink {
            override fun eeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) {
                (asm ?: WindowAssembler(firstMs.roundToLong()).also { asm = it }).addHeadbandEeg(firstMs, uv, leadOff)
            }
            override fun movement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) { asm?.addHeadMovement(tMs, accG, gyrDps) }
            override fun catchUp(packet: P.Packet, phoneMs: Double) { catchUp++ }
        }
        val rx = HeadbandReceiver(stream.info, sink)
        var last = baseMs
        for ((ms, b) in stream.records) {
            last = baseMs + ms
            rx.onPacket(last, b)
            val type = b[0].toInt() and 0xFF
            if (type == P.TYPE_STATUS || type == P.TYPE_CONTACT) yield(Step.State(rx.state))
            asm?.let { a -> for ((w, _) in a.closeReady(last)) yield(Step.Window(w)) }
        }
        asm?.let { a -> for ((w, _) in a.closeReady(last + 7_000)) yield(Step.Window(w)) }
    }
}

/** Contact state of each electrode, for the status screen. */
object PadStatus {
    enum class Contact { OK, DRYING, NONE, UNKNOWN }
    data class Pad(val name: String, val contact: Contact, val kohm: Int?)

    fun of(s: HeadbandState?): List<Pad> = P.ELECTRODES.mapIndexed { i, name ->
        val z = s?.impedanceKohm?.getOrNull(i)
        val off = s != null && s.leadOff and (1 shl i) != 0
        val contact = when {
            off || z == P.Z_UNKNOWN -> Contact.NONE
            z == null -> Contact.UNKNOWN
            z > HeadbandAlerts.REPLACE_PAD_KOHM -> Contact.DRYING
            else -> Contact.OK
        }
        Pad(name, contact, z?.takeIf { it != P.Z_UNKNOWN })
    }
}

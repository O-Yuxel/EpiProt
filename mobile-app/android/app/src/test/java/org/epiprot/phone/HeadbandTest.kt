package org.epiprot.phone

import org.epiprot.phone.engine.WindowAssembler
import org.epiprot.phone.headband.Channels
import org.epiprot.phone.headband.HeadbandProtocol as P
import org.epiprot.phone.headband.HeadbandReceiver
import org.epiprot.phone.headband.HeadbandSink
import org.epiprot.phone.health.HealthMonitor
import org.epiprot.phone.model.WindowInput
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.roundToLong

/** Stream made by the Python simulator (tools/make_headband_fixture.py) and what Python read from it. */
object HeadbandFixture {
    private val dir = File("src/test/resources/fixtures")
    val expected = JSONObject(File(dir, "headband_expected.json").readText())
    val records: List<Pair<Long, ByteArray>>
    val info: P.DeviceInfo

    init {
        val data = File(dir, "headband.ehb").readBytes()
        require(String(data, 0, 4, Charsets.US_ASCII) == "EHB1")
        val bb = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        val n = bb.getInt(4)
        val meta = JSONObject(String(data, 8, n, Charsets.UTF_8))
        info = P.DeviceInfo.decode(meta.getString("device_info").chunked(2).map { it.toInt(16).toByte() }.toByteArray())
        val out = ArrayList<Pair<Long, ByteArray>>()
        var o = 8 + n
        while (o < data.size) {
            val ms = bb.getInt(o).toLong() and 0xFFFFFFFFL
            val len = bb.getShort(o + 4).toInt() and 0xFFFF
            out += ms to data.copyOfRange(o + 6, o + 6 + len)
            o += 6 + len
        }
        records = out
    }
}

class HeadbandProtocolTest {
    private val exp = HeadbandFixture.expected

    @Test
    fun decodesThePythonStreamExactlyAsPythonDoes() = with(HeadbandFixture) {
        val packets = records.map { P.decode(it.second) }
        assertEquals(exp.getInt("packets"), packets.size)
        val eeg = packets.filterIsInstance<P.Eeg>()
        val mov = packets.filterIsInstance<P.Mov>()
        val contact = packets.filterIsInstance<P.Contact>()
        assertEquals(exp.getInt("eeg_packets"), eeg.size)
        assertEquals(exp.getInt("mov_packets"), mov.size)
        assertEquals(exp.getInt("status_packets"), packets.count { it is P.Status })
        assertEquals(exp.getInt("contact_packets"), contact.size)
        assertEquals(exp.getInt("catch_up"), packets.count { it.flags and P.FLAG_CATCHUP != 0 })
        assertEquals(exp.getInt("lead_off_packets"), eeg.count { it.leadOff != 0 })
        assertEquals(exp.getInt("contact_check_packets"), eeg.count { it.flags and P.FLAG_CONTACT_CHECK != 0 })
        assertEquals(P.MINOR, exp.getJSONObject("info").getInt("minor"))
        assertEquals(exp.getJSONObject("info").getDouble("eeg_lsb_nv"), info.eegLsbNv.toDouble(), 1e-3)

        // EEG in µV per channel, with Python's NaN rules (saturated, contact check)
        val rx = HeadbandReceiver(info, object : HeadbandSink {
            override fun eeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) {}
            override fun movement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) {}
        })
        val nan = IntArray(4); val sum = DoubleArray(4)
        for (p in eeg) {
            val uv = rx.toMicrovolts(p)
            for (c in 0 until 4) for (i in uv[c].indices) {
                val v = uv[c][i]
                if (v.isNaN()) nan[c]++ else sum[c] += p.codes[i][c] * info.eegLsbNv.toDouble() / 1000
            }
        }
        val total = eeg.sumOf { it.codes.size }
        assertEquals(exp.getInt("eeg_samples"), total)
        for (c in 0 until 4) {
            assertEquals(exp.getJSONArray("eeg_nan").getInt(c), nan[c])
            val e = exp.getJSONArray("eeg_sum_uv").getDouble(c)
            assertEquals(e, sum[c], abs(e) * 1e-6)
        }
        for (a in 0 until 3) {
            assertEquals(exp.getJSONArray("acc_sum_g").getDouble(a), mov.sumOf { m -> m.raw.sumOf { it[a].toDouble() } } / info.accLsbPerG, 1e-6)
            assertEquals(exp.getJSONArray("gyr_sum_dps").getDouble(a), mov.sumOf { m -> m.raw.sumOf { it[3 + a].toDouble() } } / info.gyrLsbPerDps, 1e-2)
        }
        for ((i, p) in contact.withIndex()) {
            val e = exp.getJSONArray("contact_kohm").getJSONArray(i)
            for (k in 0 until 5) assertEquals(e.getInt(k), p.impedanceKohm[k])
        }
    }

    @Test
    fun unknownMajorVersionIsRefused() {
        val b = HeadbandFixture.records.size.let { ByteArray(P.DeviceInfo.SIZE) }.also { it[0] = 2 }
        assertThrows(IllegalArgumentException::class.java) { P.DeviceInfo.decode(b) }
    }
}

class HeadbandChannelTest {
    private fun bit(vararg e: String) = e.fold(0) { acc, n -> acc or (1 shl P.ELECTRODES.indexOf(n)) }

    @Test
    fun standardPairWhenAllPadsTouch() = assertEquals(Channels.Choice(0, 1, true), Channels.choose(0))

    @Test
    fun aPadWithoutContactSwitchesToAPairThatDoesNotUseIt() {
        assertEquals(Channels.Choice(2, 3, true), Channels.choose(bit("L-top")))      // ch1, ch2 use L-top
        assertEquals(Channels.Choice(2, 1, true), Channels.choose(bit("L-bottom")))   // ch1, ch4 use L-bottom
        assertEquals(Channels.Choice(0, 3, true), Channels.choose(bit("R-top")))      // ch2, ch3 use R-top
        assertEquals(Channels.Choice(0, 1, true), Channels.choose(bit("R-bottom")))   // only backups use it
        assertTrue(Channels.choose(bit("L-top")).backup)
    }

    @Test
    fun noUsablePairOrBiasLostMeansBadContact() {
        assertFalse(Channels.choose(bit("L-top", "R-top")).contactOk)
        assertFalse(Channels.choose(bit("bias")).contactOk)
    }

    @Test
    fun badContactMakesTheBrainSignalPoorEvenIfItLooksNormal() {
        val f = mapOf("eegL_rms" to 1.5, "eegX_rms" to 1.4, "head_acc_std" to 0.1, "ecg_hr" to 70.0, "body_acc_std" to 0.1)
        assertEquals(HealthMonitor.Quality.OK, HealthMonitor.quality(f)["brain"])
        assertEquals(HealthMonitor.Quality.POOR, HealthMonitor.quality(f, contactBad = true)["brain"])
    }
}

class HeadbandReceiverTest {
    private class Collect : HeadbandSink {
        var assembler: WindowAssembler? = null
        var catchUp = 0
        override fun eeg(firstMs: Double, uv: Array<FloatArray>, leadOff: Int) {
            val a = assembler ?: WindowAssembler(firstMs.roundToLong()).also { assembler = it }
            a.addHeadbandEeg(firstMs, uv, leadOff)
        }
        override fun movement(tMs: Double, accG: FloatArray, gyrDps: FloatArray) { assembler?.addHeadMovement(tMs, accG, gyrDps) }
        override fun catchUp(packet: P.Packet, phoneMs: Double) { catchUp++ }
    }

    private fun run(): Triple<Collect, HeadbandReceiver, List<WindowInput>> {
        val sink = Collect()
        val rx = HeadbandReceiver(HeadbandFixture.info, sink)
        for ((ms, b) in HeadbandFixture.records) rx.onPacket(ms, b)
        val a = sink.assembler!!
        val windows = a.closeReady(a.startMs + 40_000 + 2_000).map { it.first }        // 40 s recording
        return Triple(sink, rx, windows)
    }

    @Test
    fun liveDataBecomeModelWindowsAndStoredDataGoToTheDiary() {
        val (sink, rx, w) = run()
        assertEquals(8, w.size)                                              // 40 s
        assertEquals(HeadbandFixture.expected.getInt("catch_up"), sink.catchUp)
        assertEquals(0L, rx.state.duplicates)
        assertEquals(0L, rx.state.missing)
        // first window: complete EEG on the standard pair, 125 movement samples in group-B units
        val w0 = w[0]
        assertEquals(Channels.Choice(0, 1, true), w0.channels)
        assertTrue(w0.eegUv!!.all { ch -> ch.all { it.isFinite() } })
        val z = w0.mov.getValue("head_acc")[2]
        assertTrue(z.all { it.isFinite() })
        assertEquals(1f / 6f, z.average().toFloat(), 0.002f)                // 1 g
        // 25-31 s: L-top off -> backup channels 3 + 4, still usable
        assertEquals(Channels.Choice(2, 3, true), w[5].channels)
        assertFalse(w[5].contactBad)
        // 25-27 s is also a contact check: those 2 s (whole packets) are left out of detection
        assertTrue(w[5].eegUv!!.all { ch -> ch.count { it.isNaN() } in 500..530 })
        assertEquals(Channels.Choice(2, 3, true), w[6].channels)            // 30-31 s still off
        assertTrue(w[6].eegUv!!.all { ch -> ch.all { it.isFinite() } })
        // 12-17.5 s: phone out of range -> those windows miss live data (the diary gets them later)
        assertTrue(w[3].eegUv == null || w[3].eegUv!![0].count { it.isFinite() } < 1280)
    }

    @Test
    fun statusAndContactCheckReachThePhoneState() {
        val (_, rx, _) = run()
        val s = rx.state
        assertTrue(s.streaming)
        assertEquals(HeadbandFixture.expected.getJSONArray("status_battery_pct_first_last").getInt(1), s.batteryPct)
        assertNotNull(s.impedanceKohm)
        assertEquals(5, s.impedanceKohm!!.size)
    }
}

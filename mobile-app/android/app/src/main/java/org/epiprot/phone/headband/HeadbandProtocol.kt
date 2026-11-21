package org.epiprot.phone.headband

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Headband Bluetooth LE packets, byte for byte as in device-firmware/PROTOCOL.md (version 1.1).
 * Same layout as the Python reference (mobile-app/src/epiprot/headband/protocol.py); the unit tests
 * decode a stream made by the Python simulator.
 */
object HeadbandProtocol {
    const val MAJOR = 1
    const val MINOR = 1
    const val TYPE_EEG = 0x01
    const val TYPE_MOV = 0x02
    const val TYPE_STATUS = 0x03
    const val TYPE_CONTACT = 0x04
    const val FLAG_CATCHUP = 0x01
    const val FLAG_CONTACT_CHECK = 0x02
    const val TICKS_PER_S = 32768.0
    const val EEG_CH = 4
    const val INT24_MIN = -(1 shl 23)
    const val INT24_MAX = (1 shl 23) - 1
    const val Z_UNKNOWN = 0xFFFF

    // status state / error bits, lead-off bits
    const val ST_CHARGING = 1; const val ST_CHARGER = 2; const val ST_STREAMING = 4; const val ST_LOW_BATTERY = 8
    const val ERR_EEG_SATURATION = 1; const val ERR_IMU_OVERFLOW = 2; const val ERR_FLASH_FULL = 4
    const val ERR_WATCHDOG = 8; const val ERR_BROWNOUT = 16; const val ERR_EEG_CHIP = 32; const val ERR_IMU_CHIP = 64
    const val LEAD_BIAS = 16

    /** Electrode names in bit order of the lead-off bits and of the contact packet. */
    val ELECTRODES = listOf("L-top", "L-bottom", "R-top", "R-bottom", "bias")

    /** Electrodes (bit numbers) of channels 1..4 (index 0..3), HARDWARE.md. */
    val CHANNEL_ELECTRODES = arrayOf(intArrayOf(0, 1), intArrayOf(0, 2), intArrayOf(2, 3), intArrayOf(1, 3))

    sealed interface Packet { val seq: Long; val tDev: Long; val flags: Int }

    class Eeg(override val seq: Long, override val flags: Int, val sampleIndex: Long, override val tDev: Long,
              val leadOff: Int, val codes: Array<IntArray>) : Packet       // codes[time point][channel]

    class Mov(override val seq: Long, override val flags: Int, override val tDev: Long,
              val raw: Array<ShortArray>) : Packet                           // raw[time point][acc xyz, gyro xyz]

    data class Status(override val seq: Long, override val flags: Int, override val tDev: Long, val batteryMv: Int,
                      val batteryPct: Int, val state: Int, val leadOff: Int, val tempC: Int, val unconfirmed: Long,
                      val errors: Int, val uptimeS: Long) : Packet

    class Contact(override val seq: Long, override val flags: Int, override val tDev: Long,
                  val impedanceKohm: IntArray) : Packet                      // per electrode, Z_UNKNOWN = no contact

    data class DeviceInfo(
        val major: Int, val minor: Int, val firmware: String, val serial: String,
        val eegRate: Int, val eegChannels: Int, val eegLsbNv: Float, val movRate: Int,
        val accLsbPerG: Int, val gyrLsbPerDps: Float, val layout: Int,
    ) {
        companion object {
            const val SIZE = 28

            /** Refuses an unknown major version instead of misreading the data (PROTOCOL.md, rule P6). */
            fun decode(b: ByteArray): DeviceInfo {
                require(b.size >= SIZE) { "device info too short" }
                val bb = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN)
                val major = bb.get().toInt() and 0xFF
                val minor = bb.get().toInt() and 0xFF
                require(major == MAJOR) { "unsupported headband protocol $major.$minor" }
                val fw = "${bb.get().toInt() and 0xFF}.${bb.get().toInt() and 0xFF}.${bb.get().toInt() and 0xFF}"
                val ser = ByteArray(8).also { bb.get(it) }.toString(Charsets.US_ASCII).trimEnd('\u0000')
                return DeviceInfo(major, minor, fw, ser, bb.short.toInt() and 0xFFFF, bb.get().toInt() and 0xFF,
                    bb.float, bb.get().toInt() and 0xFF, bb.short.toInt() and 0xFFFF, bb.float, bb.get().toInt() and 0xFF)
            }
        }
    }

    fun decode(b: ByteArray): Packet {
        val bb = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN)
        val type = bb.get().toInt() and 0xFF
        val flags = bb.get().toInt() and 0xFF
        val seq = bb.int.toLong() and 0xFFFFFFFFL
        return when (type) {
            TYPE_EEG -> {
                val si = bb.int.toLong() and 0xFFFFFFFFL
                val td = bb.int.toLong() and 0xFFFFFFFFL
                val n = bb.get().toInt() and 0xFF
                val lo = bb.get().toInt() and 0xFF
                val codes = Array(n) {
                    IntArray(EEG_CH) {
                        val v = (bb.get().toInt() and 0xFF) or ((bb.get().toInt() and 0xFF) shl 8) or ((bb.get().toInt() and 0xFF) shl 16)
                        if (v >= 1 shl 23) v - (1 shl 24) else v
                    }
                }
                Eeg(seq, flags, si, td, lo, codes)
            }
            TYPE_MOV -> {
                val td = bb.int.toLong() and 0xFFFFFFFFL
                val n = bb.get().toInt() and 0xFF
                Mov(seq, flags, td, Array(n) { ShortArray(6) { bb.short } })
            }
            TYPE_STATUS -> Status(seq, flags, bb.int.toLong() and 0xFFFFFFFFL, bb.short.toInt() and 0xFFFF,
                bb.get().toInt() and 0xFF, bb.get().toInt() and 0xFF, bb.get().toInt() and 0xFF, bb.get().toInt(),
                bb.int.toLong() and 0xFFFFFFFFL, bb.short.toInt() and 0xFFFF, bb.int.toLong() and 0xFFFFFFFFL)
            TYPE_CONTACT -> Contact(seq, flags, bb.int.toLong() and 0xFFFFFFFFL, IntArray(5) { bb.short.toInt() and 0xFFFF })
            else -> throw IllegalArgumentException("unknown headband packet type $type")
        }
    }
}

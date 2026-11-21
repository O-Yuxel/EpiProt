package org.epiprot.phone.headband

import org.epiprot.phone.headband.HeadbandProtocol.CHANNEL_ELECTRODES
import org.epiprot.phone.headband.HeadbandProtocol.LEAD_BIAS

/**
 * Which two of the headband's four EEG channels go to the model.
 *
 * The model was trained on SeizeIT2, where the first input is a same-side channel behind one ear
 * (left or right) and the second a cross-head channel or the other ear's same-side channel. Every
 * pair below has that shape, so when a pad loses contact the model keeps getting the kind of
 * signal it knows.
 */
object Channels {
    /** Channel pairs (0-based) in order of preference: ch1+ch2 is the standard layout. */
    val PAIRS = listOf(0 to 1, 2 to 1, 0 to 3, 2 to 3, 0 to 2)

    data class Choice(val first: Int, val second: Int, val contactOk: Boolean) {
        val backup: Boolean get() = !(first == 0 && second == 1)
    }

    fun usable(channel: Int, leadOff: Int): Boolean = CHANNEL_ELECTRODES[channel].none { leadOff and (1 shl it) != 0 }

    /** [leadOff]: electrodes without contact during the window (bits as in the EEG packets). */
    fun choose(leadOff: Int): Choice {
        if (leadOff and LEAD_BIAS != 0) return Choice(0, 1, false)        // mains hum on every channel
        for ((a, b) in PAIRS) if (usable(a, leadOff) && usable(b, leadOff)) return Choice(a, b, true)
        return Choice(0, 1, false)
    }
}

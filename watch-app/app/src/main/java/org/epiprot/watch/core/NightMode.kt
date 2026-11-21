package org.epiprot.watch.core

/**
 * Night mode (decided with the user): from [startMin] to [endMin] (minutes after midnight, set on the
 * phone) non-urgent warnings are shown without vibration. The seizure alarm and urgent warnings
 * (detection not working) always vibrate; that is decided in WatchStateMachine, not here.
 *
 * The patient can switch night mode on or off on the watch; that lasts until the schedule itself
 * changes next (e.g. switched off at 23:30 -> back on the next evening).
 */
class NightMode(var enabled: Boolean = true, var startMin: Int = 23 * 60, var endMin: Int = 7 * 60) {
    private var override: Boolean? = null
    private var overrideAgainst: Boolean? = null

    fun scheduled(minuteOfDay: Int): Boolean {
        if (!enabled || startMin == endMin) return false
        return if (startMin < endMin) minuteOfDay in startMin until endMin
        else minuteOfDay >= startMin || minuteOfDay < endMin
    }

    fun isNight(minuteOfDay: Int): Boolean {
        val s = scheduled(minuteOfDay)
        val o = override
        if (o != null && overrideAgainst == s) return o
        override = null
        return s
    }

    fun toggle(minuteOfDay: Int) {
        val now = isNight(minuteOfDay)
        override = !now
        overrideAgainst = scheduled(minuteOfDay)
    }
}

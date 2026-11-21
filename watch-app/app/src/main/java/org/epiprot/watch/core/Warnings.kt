package org.epiprot.watch.core

/**
 * Sensor-warning codes sent by the phone's sensor-health monitor
 * (mobile-app/src/epiprot/app/health.py) and its headband alerts (HeadbandAlerts.kt),
 * plus one code raised by the watch itself.
 */
enum class WarningCode(val wire: String) {
    HEADBAND_MISSING("headband_missing"),
    BRAIN_WEAK("brain_weak"),
    HEAD_MOV_MISSING("head_mov_missing"),
    WATCH_MISSING("watch_missing"),
    HEART_MISSING("heart_missing"),
    BODY_MOV_MISSING("body_mov_missing"),
    PAD_CONTACT_LOST("pad_contact_lost"),
    PAD_REPLACE("pad_replace"),
    HEADBAND_BATTERY_LOW("headband_battery_low"),
    HEADBAND_BATTERY_CRITICAL("headband_battery_critical"),
    HEADBAND_CHARGING("headband_charging"),

    /** Raised on the watch when the phone has not been reachable for 60 s. */
    PHONE_DISCONNECTED("phone_disconnected");

    companion object {
        fun fromWire(s: String): WarningCode? = entries.firstOrNull { it.wire == s }
    }
}

/** What the problem means for seizure detection. */
enum class Impact(val wire: String) {
    LIMITED("limited"),
    WEAKER("weaker"),
    BACKUP_MODEL("backup"),
    NO_ALARMS("no_alarms"),
    NONE("none");

    companion object {
        fun fromWire(s: String): Impact = entries.firstOrNull { it.wire == s } ?: NONE
    }
}

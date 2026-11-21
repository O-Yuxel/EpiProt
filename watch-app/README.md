# EpiProt watch app

A companion app for a **Wear OS** watch (Samsung Galaxy Watch4 or newer, Google Pixel Watch).
It measures and shows; all decisions are made by the phone app.

**Status:** Kotlin, Jetpack Compose for Wear OS. Builds, all unit tests pass, runs on the Wear OS 5 emulator
(alarm + PIN, warnings, Turkish/English checked) and was tested paired with the real phone running the phone app.
Not yet tested on a real watch; see *Next steps*.

Toolchain: Gradle 9.9.1 (wrapper included), Android Gradle Plugin 9.4.1 (built-in Kotlin), Kotlin 2.3.21,
compileSdk 36, minSdk 30, targetSdk 34. Builds with the Java 25 bundled with Android Studio 2026.2.

## What it does

| Task | Details |
|---|---|
| Heart rate | Reads the heart-rate sensor continuously. The sensor only reports changes, so a value stays valid for 30 s; losing skin contact clears it at once |
| Movement | Accelerometer + gyroscope at 25 Hz, delivered in 1 s batches so the processor can sleep in between |
| Sending | One small sensor packet per second to the phone app (Wear OS Data Layer, Bluetooth) |
| Backup | If the phone is out of reach, keeps the last ~10 minutes and sends them first when it is back |
| Alarm | Strong repeating vibration + red screen: "Seizure detected. Caregiver alerted. If you are fine, enter your PIN." (30 s) |
| PIN | 4 digits, checked on the watch (salted SHA-256 hash from the phone). A tap is never enough. Wrong PINs are counted and reported. |
| After the PIN window | "Help is on the way"; the alarm can no longer be cancelled on the watch |
| Check-ins | "Are you OK?" during recovery monitoring, answered with the PIN |
| Sensor warnings | Shows the phone's warnings with what to do and what it means for detection; never on top of an alarm |
| Phone lost | If the phone has not been reachable for 60 s, the watch itself warns: "Phone not connected. Seizure alarms do NOT work until this is fixed." |
| Status | Battery, charging and on-body status to the phone once a minute |
| Languages | English and Turkish (follows the watch language) |
| Demo mode | Buttons on the home screen simulate the phone's messages (alarm, check-in, warnings), so the app can be shown without a phone app. Without a heart-rate sensor (emulator) sensors are simulated, including convulsion-like shaking. |

## Code

```
app/src/main/java/org/epiprot/watch/
├── protocol/Protocol.kt         message paths and formats shared with the phone app
├── core/WatchStateMachine.kt    alarm / PIN / check-in / warning logic (no Android code, unit-tested)
├── core/PinVerifier.kt          PIN check (salted hash; demo PIN 1234 until the phone sends one)
├── core/Buffers.kt              1 s sensor batches, 10 min backup buffer
├── core/Warnings.kt             warning codes (same as mobile-app/src/epiprot/app/health.py)
├── sensors/Sensors.kt           real watch sensors, or simulated ones
├── link/PhoneLink.kt            Data Layer connection to the phone app + message receiver
├── service/MonitoringService.kt foreground service that keeps monitoring with the screen off
├── feedback/Feedback.kt         vibration patterns, notifications, waking the screen
├── WatchController.kt           connects logic, sensors, phone link and screens
└── ui/                          screens (home, alarm + PIN pad, check-in, warnings)
app/src/test/                    unit tests for the logic and the message formats
```

## Messages between watch and phone

| Direction | Path | Content |
|---|---|---|
| watch → phone | `/epiprot/sensor` | binary, once per second: sequence number, start time, heart rate, on-body flag, accelerometer and gyroscope samples |
| watch → phone | `/epiprot/pin` | `{context: alarm\|checkin, alarm_id, ok, attempt, time_ms}` |
| watch → phone | `/epiprot/status` | `{battery_pct, charging, on_body, heart_sensor, time_ms, alarm_id, monitoring_allowed}` |
| phone → watch | `/epiprot/alarm_start` | `{alarm_id, pin_window_s}` |
| phone → watch | `/epiprot/alarm_end` | `{alarm_id, reason}` |
| phone → watch | `/epiprot/checkin` | `{alarm_id, number}` |
| phone → watch | `/epiprot/sensor_warning` | `{code, impact, detail, urgent}`; codes: `headband_missing`, `brain_weak`, `head_mov_missing`, `watch_missing`, `heart_missing`, `body_mov_missing`, `pad_contact_lost`, `pad_replace`, `headband_battery_low`, `headband_battery_critical`, `headband_charging`, `headband_off`; impact: `no_alarms`, `limited`, `weaker`, `backup`, `none`; detail = pads concerned, battery %, or off / disconnected / unpaired; urgent = vibrates in night mode |
| phone → watch | `/epiprot/sensor_fixed` | `{code}` |
| phone → watch | `/epiprot/settings` | `{pin_salt, pin_hash, pin_window_s, night_enabled, night_start_min, night_end_min}` |
| phone → watch | `/epiprot/consent` | `{monitoring_allowed}` |

The phone app must use the **same application id** (`org.epiprot.app`) and the **same signing key**,
otherwise Wear OS does not connect the two apps.

## Running it

Requirements: **Android Studio** (includes Java, the Android SDK and the Wear OS emulator).

1. Android Studio → *Open* → the `watch-app` folder. Let it sync.
2. *Device Manager* → create a **Wear OS** virtual device (e.g. "Wear OS Large Round", Wear OS 5 / API 34).
   On the development PC this exists already as `EpiProt_Watch`.
3. Run the `app` configuration on it. Allow body sensors when asked.
   Emulator heart rate: *Extended controls* → *Virtual sensors*, or `adb emu sensor set heart-rate 72`.
4. On the home screen, scroll down to **Demo** and try: seizure alarm → PIN 1234; check-in; sensor warning.

Command line: `gradlew assembleDebug` (APK in `app/build/outputs/apk/debug/`). Unit tests: `gradlew test` (or right-click `app/src/test` → *Run tests*).

Connecting the emulator watch to a real Android phone (for the phone app later): install the *Wear OS by Google*
companion app on the phone, connect the phone by USB, run `adb forward tcp:5601 tcp:5601`, then pair in the
companion app.

## Next steps

- Test on a real Galaxy Watch: battery use with continuous heart rate, waking the screen for an alarm when the
  watch is idle, heart-rate quality during strong movement.
- The model learned heart rate from a chest ECG; a watch measures it with light (PPG). This must be validated
  and the model retrained with watch data.

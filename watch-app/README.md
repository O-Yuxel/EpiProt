# EpiProt watch app

A small companion app for a **Wear OS** watch (for example Samsung Galaxy Watch or Google Pixel Watch).
It measures and shows; all decisions are made by the phone app.

**Status:** specification only, not built yet.

## Why our own watch app?

The watch makers' health apps sync heart rate to the phone in batches, minutes later. Seizure detection needs
**live** data, and the alarm needs a PIN screen on the watch. Wear OS lets us install our own app and gives a
ready-made message channel between the watch app and the phone app (Data Layer API over Bluetooth).

## What it does

| Task | Details |
|---|---|
| Heart rate | Reads the heart-rate sensor continuously and sends it to the phone |
| Movement | Reads the accelerometer and gyroscope and sends them to the phone |
| Alarm | Vibrates and shows "Seizure detected. If you are fine, enter your PIN." (30 s) |
| PIN | 4-digit PIN entered and checked on the watch, so it works even if the connection drops for a moment; a tap is not enough |
| Check-ins | "Are you OK?" every 5 minutes after a seizure, answered with the PIN |
| Sensor warnings | Shows the phone's warnings, e.g. "Heart rate is not measured. Tighten the watch strap." |
| Status | Sends battery level and wear status to the phone |
| Backup | Keeps the last 10 minutes of data if the connection drops and sends them later |

The PIN and other settings are entered in the phone app and copied to the watch automatically.

## Messages between watch and phone (proposal)

| Direction | Message |
|---|---|
| watch → phone | `sensor`: time stamp, heart rate, movement samples |
| watch → phone | `pin_ok` / `pin_wrong` with time stamp |
| watch → phone | `status`: battery, worn / not worn |
| phone → watch | `alarm_start`, `alarm_end` |
| phone → watch | `checkin` ("Are you OK?") |
| phone → watch | `sensor_warning` with the text to show, `sensor_fixed` |
| phone → watch | `settings` (PIN hash, language) |

## Open points

- The model learned heart rate from a chest ECG. A watch measures it with light (PPG), which can fail during
  convulsions. This must be tested and the model retrained with watch data.
- Continuous heart rate will likely need daily charging.

## Technology

Kotlin, Wear OS 3+, Health Services / SensorManager, Wearable Data Layer API. Published together with the
phone app under the same app listing, so the two apps find each other automatically.

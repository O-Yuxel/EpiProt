# EpiProt headband firmware

Software for the small processor inside the headband. It **measures and sends; it makes no decisions.**
The detection model runs on the phone.

**Status:** hardware and Bluetooth protocol designed on paper; no physical device is built in this project.

## What it does

| Task | Details |
|---|---|
| EEG | 4 channels behind the ears (2 used by the model, 2 backups), exactly 256 Hz, 24-bit |
| Head movement | 3-axis accelerometer + 3-axis gyroscope, 25 Hz |
| Electrode contact | Checks continuously whether every electrode touches the skin and reports it to the phone |
| Streaming | Sends raw data to the phone over encrypted Bluetooth LE, about 3.7 KB/s |
| No data loss | Keeps everything the phone has not confirmed (up to about 40 minutes) and sends it after a reconnect |
| Time stamps | Every packet has a sequence number and a crystal-clock time stamp, so the phone detects any missing samples |
| Status | Battery, charging, electrode contact, errors, once per second |

## Connection to the phone

1. First use: "Connect headband" in the phone app and the passkey from the user manual in the box; phone and headband are paired once.
2. After that the headband reconnects automatically whenever it is on and the phone is within range.
3. The phone app receives the packets in the background.

Full protocol, byte by byte: [PROTOCOL.md](PROTOCOL.md).

## Hardware

Designed on paper in [HARDWARE.md](HARDWARE.md), with every design decision and its reason: semi-dry electrodes,
TI ADS1299-4 4-channel EEG front-end at exactly 256 samples/s, Bosch BMI270 motion sensor, Nordic nRF52840 Bluetooth
module, 700 mAh rechargeable battery (about 2 days), about $58–74 in parts.
Code in C / C++ (Zephyr / nRF Connect SDK).

## Why the model is not on the headband (yet)

The model needs data from both the headband and the watch, the raw data for the event log go to the phone
anyway, and caregiver messages leave from the phone. A small EEG + head-movement backup model on the headband,
so that the watch can be alerted without the phone, is a possible later version.

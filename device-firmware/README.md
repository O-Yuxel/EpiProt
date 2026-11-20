# EpiProt headband firmware

Software for the small processor inside the headband. It **measures and sends; it makes no decisions.**
The detection model runs on the phone.

**Status:** specification only, not built yet.

## What it does

| Task | Details |
|---|---|
| EEG | 2 channels behind the ears (left behind-ear and a left-right cross channel), at least 256 Hz |
| Head movement | 3-axis accelerometer + 3-axis gyroscope, at least 25 Hz |
| Electrode contact | Checks continuously whether the electrodes touch the skin and reports it to the phone |
| Streaming | Sends the data to the phone over Bluetooth Low Energy, about 10 packets per second |
| Backup | Keeps the last 10 minutes in memory; if the connection drops it sends them when it comes back |
| Time stamps | Every packet has a sequence number and a time stamp, so the phone can detect missing packets |
| Status | Battery level, contact status, firmware version |

Data rate is about 1.8 kB/s for the whole system, well within Bluetooth Low Energy.

## Connection to the phone

1. First use: "Connect headband" in the phone app; phone and headband are paired once.
2. After that the headband reconnects automatically whenever it is on and the phone is within about 10 m.
3. The phone app subscribes to the headband's data service and receives the packets in the background.

## Data packet (proposal)

| Field | Size |
|---|---|
| Sequence number | 2 bytes |
| Time stamp (ms) | 4 bytes |
| EEG, 2 channels × 25 samples, 16 bit | 100 bytes |
| Movement, 6 axes × 2–3 samples, 16 bit | 24–36 bytes |
| Contact / battery flags | 1 byte |

## Hardware

Designed on paper in [HARDWARE.md](HARDWARE.md), with every design decision and its reason: semi-dry electrodes,
TI ADS1299-4 4-channel EEG front-end at exactly 256 samples/s, Bosch BMI270 motion sensor, Nordic nRF52840 Bluetooth
module, 700 mAh rechargeable battery (about 2 days), about $58–74 in parts.
Code in C / C++ (Zephyr / nRF Connect SDK).

## Why the model is not on the headband (yet)

The model needs data from both the headband and the watch, the raw data for the event log go to the phone
anyway, and caregiver messages leave from the phone. A small EEG + head-movement backup model on the headband,
so that the watch can be alerted without the phone, is a possible later version.

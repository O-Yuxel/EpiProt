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
TI ADS1299-4 4-channel EEG front-end at exactly 256 samples/s, TDK ICM-42688-P motion sensor clocked by the radio
crystal (exactly 25 Hz), Nordic nRF52840 Bluetooth module, 700 mAh rechargeable battery (about 2 days), about $59–76
in parts.
Code in C / C++ (Zephyr / nRF Connect SDK).

## Virtual headband (simulator)

No physical headband is built, so a software copy of it was written: `mobile-app/src/epiprot/headband/`.
It takes a real SeizeIT2 recording, passes it through the designed hardware (electrode layout, electrode DC offsets,
ADS1299 noise and 24-bit steps, crystal clocks, motion sensor), packs it into the Bluetooth packets of
[PROTOCOL.md](PROTOCOL.md), writes them to a stream file (`.ehb`), and reads them back as the phone would.

| Check (sub-115, 15 min around a tonic-clonic seizure) | Result |
|---|---|
| Packets lost | 0 of 19 816 |
| Data rate | 3.7 KB/s, as specified |
| EEG on the phone vs. original | 0.2 µV RMS difference (the amplifier noise) on a ~280 µV signal |
| EEG model features | largest difference 6 % of the feature's normal spread |
| Movement model features | typical difference 0.03 (log scale) with the locked sensor clock; 0.57 with a free-running one (decision D13) |

```bash
python -m epiprot.headband.simulate --raw-dir /raw --sub sub-115 --out epiprot_results/headband/sub-115
python -m epiprot.headband.imu_clock_study --raw-dir /raw sub-115 sub-058
python -m epiprot.headband.calibration --raw-dir /raw        # SeizeIT2 movement scale groups (D14)
```

## Why the model is not on the headband (yet)

The model needs data from both the headband and the watch, the raw data for the event log go to the phone
anyway, and caregiver messages leave from the phone. A small EEG + head-movement backup model on the headband,
so that the watch can be alerted without the phone, is a possible later version.

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

### Fault scenarios

`python -m epiprot.headband.fault_study --raw-dir /raw --sub sub-115 --out epiprot_results/headband/faults`
runs one hour of a real recording with one fault each and replays the phone: a 5 s window is judged only with
the packets that arrived in time, and the phone's sensor-health rules (`epiprot.app.health`) decide the warnings.

| Fault | Phone warning (today) | With contact bits (planned) | Data |
|---|---|---|---|
| Phone out of range 10 min | headband missing, after 90 s | same | nothing lost: 13 240 stored packets sent after reconnecting |
| Phone out of range 45 min | headband missing, after 90 s | same | oldest ~7 min lost (store holds ~38 min), reported by the headband |
| Pad dries out over 40 min | brain signal weak, once contact is lost | same | **"replace pad" from the contact check (D15) 36 min earlier** |
| Pad falls off (L-top) | brain signal weak, after 95 s | same | backup channels 3 and 4 stay fully usable |
| Loose cable | **none** | brain signal weak, after 95 s | bad samples are marked and left out |
| Bias electrode off | **none** | brain signal weak, after 90 s | mains hum raises 30–60 Hz power ~3000 times |
| Charging | headband missing, after 90 s | same | headband reports "charging" |
| Motion sensor fails | head movement missing, after 90 s | same | headband reports the sensor error |
| Battery runs out | headband missing, after 90 s | same | low battery reported first |

**Decided with the user for the phone integration step:**
- ✅ (phone part 2) **Every headband warning is shown on the watch**: replace pad, electrode contact lost, brain signal weak,
  headband missing, battery low, charging, motion sensor error.
- ✅ (phone part 3) **The phone shows the headband's live state** (like the heart-rate status for the watch): connection, battery,
  contact of each pad, brain signal and head movement arriving or not, last contact check.
- ✅ (phone part 2) **Night mode on the watch** (time range set once on the phone, e.g. 23:00–07:00; can also be switched on the watch):
  - the seizure alarm always vibrates (the patient must be able to cancel a false alarm, "Are you OK?" checks must work);
  - warnings that mean detection is not working still vibrate: headband missing, brain signal lost,
    battery about to run out (< 30 min);
  - non-urgent warnings are shown without vibration: replace pad, battery low, charging;
  - when night mode ends the watch vibrates once softly and shows a summary of the silent warnings.

**For the phone integration step** (found here):
1. ✅ (phone part 1) Use the contact (lead-off) bits for the brain-signal check; without them a loose cable or a lost bias electrode
   goes unnoticed while the data are bad.
2. ✅ (phone part 1) Switch the model to a backup channel pair when a pad of channel 1 or 2 loses contact.
3. ✅ (phone part 2) Show "headband charging" instead of "headband missing" when the status says so.
4. ✅ (phone part 1) Ignore packets received twice (same sequence number); send catch-up packets to the diary, not to detection.
5. ✅ (phone part 1) Movement: convert to the SeizeIT2 group-B scale (D14) and place samples in their 25 Hz slots (D13).
6. ✅ (phone part 2) Show "replace the pad behind the left ear (lower)" when a contact check reports a pad above 150 kOhm (D15),
   and leave EEG flagged as "contact check" out of detection.

## Why the model is not on the headband (yet)

The model needs data from both the headband and the watch, the raw data for the event log go to the phone
anyway, and caregiver messages leave from the phone. A small EEG + head-movement backup model on the headband,
so that the watch can be alerted without the phone, is a possible later version.

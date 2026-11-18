# EpiProt

**A wearable system that detects tonic-clonic (big convulsive) seizures while they happen, alerts a
caregiver with the location, watches over the patient after the seizure, and keeps a seizure diary
with raw brain, heart and movement signals for the doctor.**

| 96% | 0.20 / day | 42 s |
|:---:|:---:|:---:|
| tonic-clonic seizures detected (53 of 55) | false alarms per day (about 1 every 5 days) | median time from seizure onset to alarm |

Results on the SeizeIT2 wearable dataset (125 patients, 11,538 hours), patient-wise cross-validation:
every patient was tested by models that never saw them in training.

---

## The system has three parts, one folder each

```
 Headband  ── Bluetooth ──►  Phone app  ◄── Bluetooth ──►  Watch
 (EEG + head movement)       (the brain)                   (heart rate, movement, PIN)
                                │
                                ├── SMS + location ──► caregiver
                                └── report (e-mail) ──► doctor
```

### 📱 [`mobile-app/`](mobile-app/) — EpiProt phone app
The brain of the system. Everything that decides runs here.
- **Seizure detection model** (5 s + 30 s LightGBM models, with a fallback when movement data is missing)
- **Alarm flow:** caregiver alerted at the moment of the alarm; a 4-digit PIN cancels a false alarm and sends a
  "false alarm" message; emergency message after 5 minutes; "Are you OK?" check-ins after the seizure
- **Sensor-health monitor:** warns on the watch when the headband or watch is not measuring properly
- **Event log** on the phone (SQLite) with raw EEG, heart and movement around every event
- **Doctor report** (PDF with charts) generated on the phone, sent when online

Status: model trained and evaluated; app logic is a working Python prototype tested on real recordings.
The Android app (Kotlin) is the next step.

### ⌚ [`watch-app/`](watch-app/) — EpiProt watch app
A small companion app on a Wear OS watch. It measures and shows; it does not decide.
- Sends live heart rate and wrist movement to the phone
- Vibrates on an alarm and asks for the PIN (checked on the watch)
- Shows the "Are you OK?" check-ins and the sensor warnings

Status: specification written, not built yet.

### 🎧 [`device-firmware/`](device-firmware/) — headband software
Runs on the small processor inside the headband.
- Samples 2-channel behind-the-ear EEG and head movement
- Checks electrode contact
- Streams the data to the phone over Bluetooth Low Energy, keeps a 10-minute backup if the connection drops

Status: specification written, not built yet.

---

## Where each piece of software runs

| Software part | Headband | Watch | Phone |
|---|:---:|:---:|:---:|
| Signal sampling, time stamps, electrode contact check | ✔ | ✔ | |
| 10-minute backup buffer if Bluetooth drops | ✔ | ✔ | |
| Vibration, alarm screen, PIN entry and check | | ✔ | |
| Detection model | | | ✔ |
| Alarm and recovery flow, SMS to the caregiver | | | ✔ |
| Sensor-health monitor | | warnings | ✔ |
| Event log, 48 h raw buffer, doctor report | | | ✔ |

The phone is the hub because all sensors meet there, the raw data for the event log arrives there anyway
(about 1.8 kB/s), and messages to the caregiver leave from the phone.

## How the parts talk to each other

| What | From → to | How |
|---|---|---|
| Brain signal + head movement | headband → phone | Bluetooth Low Energy; paired once, then reconnects automatically |
| Heart rate, movement, PIN result | watch ↔ phone | Wear OS Data Layer (Bluetooth) between the two EpiProt apps |
| Caregiver alert | phone → caregiver's phone | SMS with a map link of the location; numbers entered in the app |
| Doctor report | phone → doctor | encrypted zip (PDF + event table + raw signals) by e-mail, with the patient's consent |

## Privacy

Health data stay on the patient's phone, encrypted. Nothing is uploaded to a server. Data are sent to the
doctor only with the patient's consent (KVKK / GDPR special category data).

## Disclaimer

EpiProt is a student research prototype (NYAS Junior Academy). It is not a certified medical device and does
not replace medical care.

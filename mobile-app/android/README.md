# EpiProt phone app (Android)

The hub of the system: receives the watch and headband data, runs the seizure detector every 5 s,
handles alarms and sends the caregiver messages. Kotlin, Jetpack Compose (Material 3).

**Status:** builds, 74 unit tests pass, lint without errors (including parity with the Python code). Tested on a real phone
(Xiaomi, Android 13) with the watch app on the Wear OS emulator, and with a second phone playing the headband over
real Bluetooth LE (`device-firmware/README.md`, "Real Bluetooth test"). The demo replays a real recorded seizure →
alarm → caregiver message with location → audit trail. Not yet tested on a real watch; the headband exists as a
design and a simulator only.

## What runs on the phone

| Part | File | Same as (Python) |
|---|---|---|
| 5 s window features (EEG, heart rate, movement) | `model/WindowFeatures.kt` | `gbm/tc_features.py` |
| 30 s features (EEG spectrogram, heart-rate statistics), model B, change features | `model/Features30s.kt`, `model/Detector.kt` | `gbm/tc30s_features.py`, `gbm/detect.py` |
| context features (1 min / 10 min history), running median | `model/Detector.kt` (`ContextExpander`) | `gbm/tc_detect.py` `expand()` |
| LightGBM models, read from LightGBM's text format (no native library) | `model/Gbdt.kt` | `lightgbm` |
| score scaling, alarm rule, seizure start / end estimate | `model/Detector.kt` | `gbm/tc_ensemble.py`, `app/simulate.py` |
| alarm flow (PIN, false alarm message, emergency, check-ins, re-alert, handover) | `alarm/AlarmFlow.kt` | `app/flow.py` |
| sensor-health monitor (warnings to the watch) | `health/HealthMonitor.kt` | `app/health.py` |
| 5 s windows from the incoming samples | `engine/WindowAssembler.kt` | – |
| the chain per window | `engine/MonitoringEngine.kt` | – |
| event log (SQLite), settings, PIN hash | `data/Store.kt` | `app/eventlog.py` |
| caregiver SMS with location, watch messages | `comm/Comm.kt` | – |
| foreground service | `service/MonitoringService.kt` | – |
| screens: home (status, alarm, demo), events, settings | `ui/MainActivity.kt` | – |
| headband page: pairing, connect / disconnect / off / unpair, pads, firmware update | `ui/Headband.kt`, `headband/FirmwareUpdate.kt` | – |
| caregiver mode: role choice, followed patients, loud alarm, "I am going" | `caregiver/`, `ui/Caregiver.kt` | – |
| seizure diary (added by hand) | `ui/Diary.kt` | – |
| shower mode backup timer | `alarm/ShowerWatch.kt` | – |
| phone notifications, battery warnings | `service/PhoneAlerts.kt`, `health/DeviceBatteryAlerts.kt` | – |
| watch message formats (copy of the watch app's file) | `protocol/Protocol.kt` | `watch-app/.../Protocol.kt` |

The **unit tests** (`app/src/test`) check that the phone gives the same numbers as Python on real SeizeIT2 data
(fixtures exported by `mobile-app/src/epiprot/app/export_model.py` and `tools/make_health_fixture.py`):
window features, context features, both models (to 1e-9), score scaling, alarm times, and every sensor warning
of three patients. Plus the alarm flow, window assembly and a full replay of the demo seizure.

## The model on the phone

Only data the EpiProt hardware really provides: **headband EEG + headband movement + the watch's 1 Hz heart
rate**. No chest ECG, no wrist movement.

| Model | Input | Features |
|---|---|---|
| A (5 s) | EEG, watch heart rate, headband movement | 200 |
| A' (5 s, backup while the headband movement sensor sends nothing) | EEG, watch heart rate | 120 |
| B (30 s) | EEG spectrum (computed from the raw signal on the phone) + watch heart rate mean / std / min / max | 204 |
| A_nohr (5 s, backup while the watch sends no heart rate) | EEG, headband movement | 192 |
| B_nohr (30 s, same) | EEG spectrum | 184 |

Rule: max of the scaled 5 s and 30 s scores, threshold for 0.25 false alarms/day. In every window without a heart
rate, or with a stuck heart rate (varied < 1 bpm over the last minute), the phone uses A_nohr and B_nohr: models
that never saw a heart rate, so a heart rate that drops out or freezes (watch taken off, optical sensor lost
during a convulsion) cannot fool them.
**Cross-validated: 54 / 55 tonic-clonic seizures (98%), 0.24 false alarms/day, median alarm 46 s after onset.**

How we got there (all patient-wise 5-fold cross-validation, 0.25/day budget):

| System | Detected | FA/day |
|---|---|---|
| original (B used the raw chest ECG and beat-to-beat intervals) | 53/55 | 0.20 |
| B rebuilt from what the phone can compute (`gbm/tc30s_features.py`), A with head + wrist movement | 53/55 | 0.22 |
| **A without wrist movement** (chosen) | **54/55** | **0.24** |
| movement only as change vs the person's own recent past (unit-free), head only | 52/55 | 0.26 |
| same, head + wrist | 53/55 | 0.24 |

What happens when the watch heart rate is missing (`gbm/hr_robustness.py`; models trained on clean data, only the
test patients' heart rate removed, before the context features are computed, as on the phone):

| Heart rate | Without backup | **With the backup models** |
|---|---|---|
| as recorded | 54/55, 0.24/day | **54/55, 0.24/day** |
| lost from each seizure's onset until 5 min after its end | 46/55, 0.25 | **54/55, 0.25** |
| none at all (watch not worn) | 46/55, 0.05 | **53/55, 0.28** |
| headband alone (backup models only) | – | **53/55, 0.26, median 53 s** |

A heart rate that is present but WRONG (optical sensor fooled by movement) is the harder case, because the phone
cannot see it (`hr_robustness.py --scenarios hr_erratic_sz hr_frozen_sz hr_spurious`):

| Wrong heart rate | Before | **With the stuck check** | Backup always on (rejected) |
|---|---|---|---|
| none (correct) | 54/55, 0.24 | **54/55, 0.23** | 53/55, 0.24 |
| random 60-180 during the seizure | 53/55, 0.23 | **53/55, 0.22** | 53/55, 0.24 |
| stuck at the pre-seizure value | 40/55, 0.24 | **53/55, 0.24** | 52/55, 0.24 |
| false high rate 10 % of the day (activity) | 54/55, 0.41 | 54/55, 0.39 | 53/55, 0.32 |

Stuck check: a heart rate that varied less than 1 bpm over the last minute counts as missing, so the no-heart-rate
models take over (`Detector.hrStuck`, same rule as `stuck_mask`). The threshold must be tuned with real watch data
(the simulation used an exactly constant value). False high rates from activity still raise false alarms; checking
the heart rate against the wrist-movement cadence needs real watch recordings (SeizeIT2 has no wrist sensor).

Training model A with simulated heart-rate dropouts instead was tried and rejected: it learned "heart rate stops
-> seizure" (55/55 with dropouts at seizure onset, but 0.91 false alarms/day without a watch, 52/55 with a normal
heart rate). So the headband is the core sensor; the watch heart rate adds about one seizure and ~7 s earlier alarms.

The wrist movement is not needed for detection; the watch's movement is only used to tell whether the watch is
worn and sending. `assets/model/` is made by `export_model.py --group5 eeg+ecg+head --mov-cols head_acc_std --nohr5 ... --nohr30 ...
--stuck-hr 1.0` (final models trained on all 125 patients; threshold chosen on the out-of-fold scores of all
patients: 54/55, 0.23/day there).

## Not validated yet (honest list)

* **Heart rate:** the model learned it from a chest ECG; the watch measures it optically. Missing and stuck heart
  rates are handled by the backup models (tested in simulation); the stuck threshold must be tuned with real
  watch data, and a false high rate during activity still raises false alarms (0.24 -> 0.39/day in simulation).
* **Movement:** in SeizeIT2 the "head" movement sensor was the EEG recorder at the **back of the neck**; in the
  headband (v3) it sits in the left pod on the side of the neck, held by the ear hooks. The features use only the
  movement's size (orientation does not matter), but the amplitude can differ. Movement is worth 5 of 55 seizures
  (54/55 with it, 49/55 without, same false-alarm rate), so it must be checked with real headband recordings.
  Units: converted to the SeizeIT2 group-B scale (D14; the unit-free variant lost 2 seizures).
* **EEG:** the headband gives the same two behind-the-ear channels as the SeizeIT2 device (plus two backups).
* Training data come from hospital monitoring units. All of this needs data from the real EpiProt hardware and
  probably retraining.
* The demo seizure (sub-115) was part of the training data of the exported model: the demo shows the chain
  working, it is not a performance test.

## Staying on

* The service is sticky and the user's choice is remembered: after the process is killed it comes back (tested:
  ~10 s), after a reboot or an app update `RestartReceiver` starts it again (tested on the emulator: ~2.5 min after
  boot, Android delivers BOOT_COMPLETED app by app). Location is not used by a service restarted in the background
  (while-in-use rule) until the app is opened. If Android refuses the start, a "tap to resume" notification appears.
  The watch app does the same.
* Settings → Keep EpiProt running: battery-optimisation exemption (asked with an explanation) and phone-brand hints
  (Xiaomi autostart, Samsung sleeping apps, Huawei app launch, Oppo/Realme/OnePlus/Vivo); a home-screen card appears
  while monitoring runs under battery optimisation.
* `EnduranceTest`: the whole chain over hours of replayed data (default 2 h; `gradlew testDebugUnitTest
  --tests "*EnduranceTest" -PenduranceHours=24`). 24 h on this PC: 17 280 windows, 3.7 ms per window (99 %: 14 ms),
  96 alarms for 96 replayed seizures, memory flat (18.9 MB). Battery use must still be measured on a real phone.

## Safety and privacy

Consent system (first-start setup, privacy centre, every scenario): see [`PRIVACY.md`](PRIVACY.md).

* **Test mode by default:** messages are written to the log and shown in the app, not sent. Real SMS only after
  turning it on in Settings (with the caregiver's consent: health data + location).
* Messages go only to the numbers entered in the app; all data stay on the phone (KVKK / GDPR special
  category data).
* The PIN is stored only as a salted SHA-256 hash, which is also what the watch receives.

## Running it

Requirements: Android Studio (Java, Android SDK, emulator).

```
cd mobile-app/android
gradlew assembleDebug        # APK in app/build/outputs/apk/debug/
gradlew test                 # unit tests
```

Or open `mobile-app/android` in Android Studio and run `app` on a phone emulator or an Android phone (USB
debugging). Then: Settings → patient name, a caregiver number, PIN → Home → *Start demo*.

The phone app and the watch app use the same application id (`org.epiprot.app`) and must be signed with the same
key. Debug builds on the same computer share the debug key, so they find each other once the watch is paired with
the phone.

Regenerating the model assets and test fixtures (repository root, Docker image `epiprot-gbm`):

```
python -m epiprot.gbm.tc30s_features --raw-dir /raw --out-dir epiprot_results/gbm/sz30_hw
python -m epiprot.gbm.detect --data-dir epiprot_results/gbm/sz30_hw --out-dir epiprot_results/gbm/detect_hw \
    --features both --models lgbm --raw-dir /raw
python -m epiprot.gbm.hr_robustness --out-dir epiprot_results/gbm/hr_robust
python -m epiprot.gbm.hr_robustness --out-dir epiprot_results/gbm/hr_nohr --parts b eeg+head --no-hr
O=epiprot_results/gbm/hr_robust; H=epiprot_results/gbm/hr_nohr
python -m epiprot.app.export_model --raw-dir /raw --group5 eeg+ecg+head --mov-cols head_acc_std \
    --oof5 $O/a_eeg+ecg+head_clean.npz --fallback $O/a_eeg+ecg_clean.npz --oof30 $O/b_clean.npz \
    --nohr5 $H/a_eeg+head_clean.npz --nohr30 $H/b_clean.npz --stuck-hr 1.0 \
    --assets mobile-app/android/app/src/main/assets/model \
    --fixtures mobile-app/android/app/src/test/resources/fixtures
python mobile-app/android/tools/make_30s_fixture.py /raw mobile-app/android/app/src/test/resources/fixtures
python mobile-app/android/tools/make_health_fixture.py mobile-app/android/app/src/test/resources/fixtures
python mobile-app/android/tools/make_demo_asset.py --raw-dir /raw --sub sub-115 \
    --out mobile-app/android/app/src/main/assets/demo/demo_seizure.bin
```

## Next steps

* Check the new headband page (pairing, connect / disconnect, switch off, unpair) and the warnings on the real
  phone and watch.
* Test on a real Wear OS watch (heart rate quality, battery).
* "Install on watch" button (opens the Play Store on the watch when the watch app is missing).

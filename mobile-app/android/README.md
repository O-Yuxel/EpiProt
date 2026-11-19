# EpiProt phone app (Android)

The hub of the system: receives the watch (and later the headband) data, runs the seizure detector every 5 s,
handles alarms and sends the caregiver messages. Kotlin, Jetpack Compose (Material 3).

**Status:** first version. Builds, 30 unit tests pass (including parity with the Python code), runs on the
Android emulator: the demo replays a real recorded seizure → alarm → caregiver message with location → audit
trail. Not yet tested together with the watch on real devices; the headband does not exist yet.

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
rate the phone uses A_nohr and B_nohr: models that never saw a heart rate, so a heart rate that drops out (watch
taken off, optical sensor lost during a convulsion) cannot fool them.
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

Training model A with simulated heart-rate dropouts instead was tried and rejected: it learned "heart rate stops
-> seizure" (55/55 with dropouts at seizure onset, but 0.91 false alarms/day without a watch, 52/55 with a normal
heart rate). So the headband is the core sensor; the watch heart rate adds about one seizure and ~7 s earlier alarms.

The wrist movement is not needed for detection; the watch's movement is only used to tell whether the watch is
worn and sending. `assets/model/` is made by `export_model.py --group5 eeg+ecg+head --mov-cols head_acc_std --nohr5 ... --nohr30 ...`
(final models trained on all 125 patients; threshold chosen on the out-of-fold scores of all patients:
53/55, 0.22/day there).

## Not validated yet (honest list)

* **Heart rate:** the model learned it from a chest ECG; the watch measures it optically. Missing heart rate is
  handled by the backup models; a heart rate that is present but WRONG (optical sensor locked onto the movement)
  is not tested yet.
* **Movement:** in SeizeIT2 the "head" movement sensor was the EEG device on the **upper back**. Putting the
  headband's electronics at the back of the neck keeps it close to that. Units differ between recordings;
  `Calibration` in `engine/WindowAssembler.kt` holds assumed conversion factors (the unit-free variant was
  tested and lost 2 seizures, so calibrating the sensor is the better way).
* **EEG:** the headband must give two behind-the-ear channels like the SeizeIT2 device.
* Training data come from hospital monitoring units. All of this needs data from the real EpiProt hardware and
  probably retraining.
* The demo seizure (sub-115) was part of the training data of the exported model: the demo shows the chain
  working, it is not a performance test.

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
    --nohr5 $H/a_eeg+head_clean.npz --nohr30 $H/b_clean.npz \
    --assets mobile-app/android/app/src/main/assets/model \
    --fixtures mobile-app/android/app/src/test/resources/fixtures
python mobile-app/android/tools/make_30s_fixture.py /raw mobile-app/android/app/src/test/resources/fixtures
python mobile-app/android/tools/make_health_fixture.py mobile-app/android/app/src/test/resources/fixtures
python mobile-app/android/tools/make_demo_asset.py --raw-dir /raw --sub sub-115 \
    --out mobile-app/android/app/src/main/assets/demo/demo_seizure.bin
```

## Next steps

* Pair the watch emulator with the phone (emulator or the real phone) and test alarm + PIN end to end.
* Doctor report (PDF) and encrypted data package from the phone (`app/report.py`), 48 h raw-data buffer.
* Headband: BLE connection once the device and its packet format exist (`device-firmware/README.md`).
* "Install on watch" button (opens the Play Store on the watch when the watch app is missing).

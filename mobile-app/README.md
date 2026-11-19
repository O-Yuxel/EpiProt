# EpiProt phone app

The brain of EpiProt: it receives the data from the headband and the watch, runs the seizure detection
model, handles the alarm, keeps the event log and builds the doctor report.

**Status:** the model and the app logic were developed in Python and tested on real SeizeIT2 recordings; the
Android app built from them is in [`android/`](android/README.md) (Kotlin, verified against the Python code).

## What is in this folder

```
mobile-app/
├── src/epiprot/
│   ├── gbm/        seizure detection model: features, training, evaluation (final model lives here)
│   ├── app/        phone app prototype: alarm flow, sensor warnings, event log, report, model export
│   └── ...         earlier research (CHB-MIT pipeline, CNN, prediction experiments)
├── tests/
├── pyproject.toml
└── Dockerfile, Dockerfile.gbm
```

### The detection model (`src/epiprot/gbm/`)

| File | Role |
|---|---|
| `tc_features.py` | 5 s window features from raw EEG, ECG and movement |
| `tc_detect.py` | 5 s models (feature groups, e.g. EEG + heart + headband movement); hard-negative mining, ECG-dropout training |
| `detect.py` | 30 s model |
| `tc_ensemble.py` | final system: max of the 5 s and 30 s scores, backups when movement or heart rate is missing / stuck |
| `tc30s_features.py` | 30 s features the phone computes itself (EEG spectrum, watch-like heart rate) |
| `hr_robustness.py` | missing or wrong watch heart rate (missing, random, stuck, false high); backup models without heart rate |
| `tc_errors.py` | error analysis: missed seizures, false alarms, latency |
| `cluster_risk.py` | seizure recurrence after a seizure (why the cluster warning was dropped) |

Final result, the model in the Android app (patient-wise 5-fold cross-validation, threshold chosen inside the
training patients), using only what the EpiProt hardware provides (headband EEG + headband movement + the watch's
1 Hz heart rate): **54 / 55 tonic-clonic seizures (98%), 0.24 false alarms per day, median alarm 46 s after
onset.**

Robustness (`hr_robustness.py`): backup models without heart rate take over whenever the watch sends none or its
heart rate is stuck: 54/55 with the heart rate lost during every seizure, 53/55 without a watch, 53/55 with the
sensor stuck during seizures (before the stuck check: 40/55). Details: [`android/README.md`](android/README.md).

An earlier version whose 30 s model used the raw chest ECG (not available on the EpiProt hardware) reached
53/55, 0.20 false alarms per day, 42 s.

### The phone app prototype (`src/epiprot/app/`)

The Android app built from it is in [`android/`](android/README.md); `export_model.py` exports the final models
(5 s, 30 s and the no-heart-rate backups) and the alarm rule for it.


| File | Role |
|---|---|
| `flow.py` | alarm flow: caregiver alerted at the alarm, PIN cancel (30 s) with a "false alarm" message, emergency after 5 min, "Are you OK?" check-ins every 5 min, re-alert after 15 min |
| `health.py` | sensor-health monitor: warning on the watch when data are missing or bad for 2 minutes |
| `eventlog.py` | event log on the phone (SQLite): events, alarm audit trail, sensor warnings, outbox |
| `signals.py` | raw EEG / ECG / movement from 2 min before to 5 min after each event |
| `report.py` | doctor report (PDF) and data package, generated on the phone |
| `simulate.py` | runs one SeizeIT2 patient through the whole chain |

## Running

Data: SeizeIT2 (BIDS) mounted at `/raw`. Results are written to `epiprot_results/` in the repository root
(not in git).

```bash
docker build -t epiprot-test mobile-app
docker build -t epiprot-gbm -f mobile-app/Dockerfile.gbm mobile-app

# phone app demo on one patient (run from the repository root)
docker run --rm -v "$PWD:/app" -v "/path/to/SeizeIT2:/raw:ro" -w /app \
  -e PYTHONPATH=/app/mobile-app/src epiprot-gbm \
  python -m epiprot.app.simulate --raw-dir /raw --sub sub-115 --out-dir epiprot_results/app_demo/sub-115

# tests
docker run --rm -v "$PWD:/app" -w /app/mobile-app -e PYTHONPATH=/app/mobile-app/src epiprot-gbm python -m pytest
```

## Next steps

1. Headband: Bluetooth connection once the device and its packet format exist.
2. Data from the real EpiProt headband and watch; tune the heart-rate checks and fine-tune the models.
3. Everything needed before real use (legal, ethics, medical-device process): [`../docs/`](../docs/).

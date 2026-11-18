# EpiProt phone app

The brain of EpiProt: it receives the data from the headband and the watch, runs the seizure detection
model, handles the alarm, keeps the event log and builds the doctor report.

**Status:** the model and all app logic are written in Python and tested on real SeizeIT2 recordings.
The real Android app (Kotlin) will be built from this prototype in `android/` (not started).

## What is in this folder

```
mobile-app/
├── src/epiprot/
│   ├── gbm/        seizure detection model: features, training, evaluation (final model lives here)
│   ├── app/        phone app prototype: alarm flow, sensor warnings, event log, report
│   └── ...         earlier research (CHB-MIT pipeline, CNN, prediction experiments)
├── tests/
├── pyproject.toml
└── Dockerfile, Dockerfile.gbm
```

### The detection model (`src/epiprot/gbm/`)

| File | Role |
|---|---|
| `tc_features.py` | 5 s window features from raw EEG, ECG and movement |
| `tc_detect.py` | 5 s model (EEG + heart + movement, 280 features) and fallback (EEG + heart, 120 features); hard-negative mining, ECG-dropout training |
| `detect.py` | 30 s model (316 features) |
| `tc_ensemble.py` | final system: max of the two scores, fallback when movement is missing |
| `tc_errors.py` | error analysis: missed seizures, false alarms, latency |
| `cluster_risk.py` | seizure recurrence after a seizure (why the cluster warning was dropped) |

Final result (patient-wise 5-fold cross-validation, threshold chosen inside the training patients):
**53 / 55 tonic-clonic seizures (96%), 0.20 false alarms per day, median alarm 42 s after onset.**

### The phone app prototype (`src/epiprot/app/`)

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

1. Retrain the final models once on all 125 patients with a fixed threshold.
2. Export them to a phone format (ONNX or generated C/Kotlin code).
3. Build the Android app: foreground service, Bluetooth connection to the headband, Wear OS Data Layer to the
   watch, SMS to caregivers, encrypted database, e-mail of the doctor package.

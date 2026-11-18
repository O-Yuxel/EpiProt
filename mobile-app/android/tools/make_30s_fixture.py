"""Fixture for the Kotlin 30 s features: raw EEG of a few 30 s windows + the Python features."""
import csv, json, sys
from pathlib import Path
import numpy as np
from epiprot.gbm import tc30s_features as T
from epiprot.gbm.tc_features import _read, _run_num
raw, out = Path(sys.argv[1]), Path(sys.argv[2])
base = raw / "sub-050" / "ses-01"
tsv = sorted((base / "eeg").glob("*_events.tsv"), key=_run_num)[0]
stem = tsv.name.replace("_events.tsv", "")
x, fs, _ = _read(base / "eeg" / f"{stem}_eeg.edf")
x = x[:2] * 1e6
pick = [3, 100, 400]
n = max(pick) + 1
F = T.eeg_features(x, n)
rng = np.random.default_rng(0)
wins = []
for i in pick:
    seg = x[:, i * 7680:(i + 1) * 7680].astype(np.float32)
    hr = (70 + 5 * rng.standard_normal(30)).astype(np.float32); hr[[3, 17]] = np.nan
    fh = T.hr_window_features(np.repeat(hr[None], 1, 0).ravel(), 1)[0]
    wins.append({"eeg": [seg[0].astype(float).tolist(), seg[1].astype(float).tolist()],
                 "hr": [None if not np.isfinite(v) else float(v) for v in hr],
                 "features": [None if not np.isfinite(v) else float(v) for v in np.r_[F[i], fh, 0.0]]})
(out / "windows30.json").write_text(json.dumps({"names": T.names(), "windows": wins}))
print("ok", len(wins))

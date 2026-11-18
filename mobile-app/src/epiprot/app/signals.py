"""Raw signal snippets for the event log (simulates the phone's rolling raw-data buffer).

On the real phone the last 48 h of raw data are kept in a ring buffer
(~1.8 kB/s: EEG 2 x 256 Hz, ECG 256 Hz, movement 12 x 25 Hz, 16 bit -> ~155 MB/day),
so an event - also one entered by hand the next morning - can get its raw signals attached.
Here the snippet is read from the SeizeIT2 EDF files, on the same timeline as tc_features
(numeric run order, floor(duration / 5 s) windows per run).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np

W = 5.0
PRE_S, POST_S = 120.0, 300.0


def runs(raw_dir: Path, sub: str):
    tsvs = sorted((raw_dir / sub / "ses-01" / "eeg").glob("*_events.tsv"),
                  key=lambda p: int(re.search(r"run-(\d+)", p.name).group(1)))
    out, pos = [], 0.0
    for t in tsvs:
        with open(t, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        n = int((float(rows[0]["recordingDuration"]) if rows else 0.0) // W)
        if n > 0:
            out.append((pos, n * W, t.name.replace("_events.tsv", "")))
        pos += n * W
    return out


def _read(path: Path, t0: float, t1: float):
    import mne
    if not path.exists():
        return None, None, None
    r = mne.io.read_raw_edf(str(path), preload=False, verbose="ERROR")
    t1 = min(t1, r.times[-1])
    if t1 <= t0:
        return None, None, None
    r.crop(tmin=max(0.0, t0), tmax=t1)
    x = r.get_data().astype(np.float32)
    return x, float(r.info["sfreq"]), list(r.ch_names)


def snippet(raw_dir: Path, sub: str, onset_s: float, out_path: Path) -> dict:
    """Save EEG/ECG/movement from onset-2 min to onset+5 min. Returns sensor availability."""
    for start, length, stem in runs(raw_dir, sub):
        if start <= onset_s < start + length:
            break
    else:
        return {}
    base = raw_dir / sub / "ses-01"
    t0 = max(0.0, onset_s - start - PRE_S)
    t1 = onset_s - start + POST_S
    save, status = {"t0_rel_onset": np.float32(-(onset_s - start - t0))}, {}
    for mod in ("eeg", "ecg", "mov"):
        x, fs, ch = _read(base / mod / f"{stem}_{mod}.edf", t0, t1)
        if x is None:
            status[mod] = 1.0
            continue
        save[mod] = x.astype(np.float16) if mod == "mov" else (x * 1e6).astype(np.float16)  # uV
        save[f"{mod}_fs"] = np.float32(fs)
        save[f"{mod}_ch"] = np.array(ch)
        status[mod] = float(np.mean(~np.isfinite(x)))
    np.savez_compressed(out_path, **save)
    return status

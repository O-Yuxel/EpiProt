"""Heart-rate / HRV features per 30 s window from the raw SeizeIT2 ECG (SensorDot).

The STFT cache only holds the ECG *spectrogram*, which barely captures heart rate.
Here R-peaks are detected on the raw ECG and per-window HRV is computed, aligned to
the chronological timeline (numeric run order, floor(recordingDuration/30) windows per
run, same as epiprot.gbm.timeline).

Output: epiprot_results/gbm/hrv/sub-XXX.npz with H (N, n_feat) float32 (NaN = no ECG /
too few beats) and names.

Usage: python -m epiprot.gbm.hrv --raw-dir /raw --out-dir epiprot_results/gbm/hrv --workers 6
"""
from __future__ import annotations

import argparse
import csv
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt

WIN_S = 30.0
NAMES = ["hr_mean", "hr_std", "rr_sdnn", "rr_rmssd", "rr_pnn50", "rr_cv", "hr_min",
         "hr_max", "beats_valid_frac"]


def _run_num(p: Path) -> int:
    return int(re.search(r"run-(\d+)", p.name).group(1))


def r_peaks(x: np.ndarray, fs: float) -> np.ndarray:
    """Simple robust R-peak detector: 5-25 Hz band-pass, energy, adaptive height."""
    sos = butter(3, [5, min(25, fs / 2 - 1)], btype="band", fs=fs, output="sos")
    e = sosfiltfilt(sos, x) ** 2
    # adaptive threshold per 10 s block: 30 % of the block's 99th percentile
    blk = int(10 * fs)
    nb = int(np.ceil(len(e) / blk))
    pad = np.pad(e, (0, nb * blk - len(e)))
    thr = 0.3 * np.percentile(pad.reshape(nb, blk), 99, axis=1)
    thr = np.repeat(thr, blk)[: len(e)]
    pk, _ = find_peaks(e, height=thr, distance=int(0.33 * fs))
    return pk


def window_hrv(peaks: np.ndarray, fs: float, n_win: int) -> np.ndarray:
    out = np.full((n_win, len(NAMES)), np.nan, np.float32)
    if len(peaks) < 3:
        return out
    t = peaks / fs
    rr = np.diff(t)
    tr = t[1:]
    ok = (rr > 0.3) & (rr < 2.0)
    ok[1:] &= np.abs(np.diff(rr)) < 0.3 * rr[:-1]  # drop ectopic / missed-beat jumps
    w = (tr // WIN_S).astype(np.int64)
    for i in range(n_win):
        lo, hi = np.searchsorted(w, [i, i + 1])
        if hi - lo < 10:
            continue
        r = rr[lo:hi][ok[lo:hi]]
        if len(r) < 10:
            continue
        hr = 60.0 / r
        d = np.diff(r)
        out[i] = [hr.mean(), hr.std(), r.std() * 1000, np.sqrt(np.mean(d ** 2)) * 1000,
                  np.mean(np.abs(d) > 0.05), r.std() / r.mean(), hr.min(), hr.max(),
                  ok[lo:hi].mean()]
    return out


def process_patient(raw_dir: Path, sub: str, out_dir: Path) -> tuple[str, int, float]:
    import mne
    t0 = time.time()
    dst = out_dir / f"{sub}.npz"
    if dst.exists():
        return sub, -1, 0.0
    tsvs = sorted((raw_dir / sub / "ses-01" / "eeg").glob("*_events.tsv"), key=_run_num)
    blocks = []
    for tsv in tsvs:
        with open(tsv, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        n_win = int((float(rows[0]["recordingDuration"]) if rows else 0.0) // WIN_S)
        ecg = raw_dir / sub / "ses-01" / "ecg" / tsv.name.replace("_events.tsv", "_ecg.edf")
        H = np.full((n_win, len(NAMES)), np.nan, np.float32)
        if ecg.exists() and n_win > 0:
            try:
                raw = mne.io.read_raw_edf(str(ecg), preload=True, verbose="ERROR")
                x = raw.get_data()[0].astype(np.float64)
                fs = raw.info["sfreq"]
                raw.close()
                H = window_hrv(r_peaks(x, fs), fs, n_win)
            except Exception as e:  # corrupt file: keep NaNs
                print(f"  {ecg.name}: {e}", flush=True)
        blocks.append(H)
    H = np.vstack(blocks) if blocks else np.zeros((0, len(NAMES)), np.float32)
    tmp = out_dir / f"{sub}.tmp.npz"
    np.savez(tmp, H=H, names=np.array(NAMES))
    tmp.replace(dst)
    return sub, len(H), time.time() - t0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--subs", nargs="*", default=None)
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    subs = a.subs or sorted(p.name for p in a.raw_dir.glob("sub-*") if p.is_dir())
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(process_patient, a.raw_dir, s, a.out_dir) for s in subs]
        for i, f in enumerate(as_completed(futs), 1):
            s, n, dt = f.result()
            print(f"[{i}/{len(subs)}] {s}: {'skip' if n < 0 else f'{n} windows in {dt:.0f}s'} "
                  f"| {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

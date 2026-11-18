"""30 s window features that the EpiProt phone can compute itself (for the 30 s model B).

Only what the EpiProt hardware provides:
  * headband EEG, 2 behind-the-ear channels (256 Hz, uV, no per-recording normalisation):
    spectrogram per 30 s window (1 s Hann segments, 0.5 s hop -> 59 segments, 1..40 Hz in 1 Hz bins),
    then the same 23 spectral features per channel as epiprot.gbm.features
    (band log-powers, relative powers, variability over time, ratios, entropy, SEF90, peak frequency)
  * "watch-like" heart rate: one value per second (60 / median beat interval of the last 5 s),
    as a smartwatch reports it, then mean / std / min / max over the 30 s window
    (the ECG is only used to simulate that 1 Hz heart rate; no beat-to-beat features).
  * hr_missing: 1 when no heart-rate data at all (no ECG in SeizeIT2 / watch not sending)

Windows: floor(recordingDuration / 30) per run, runs in numeric order (same timeline as
epiprot.gbm.timeline / tc_ensemble.run_lengths). Seizures as window indices [onset, end).

Output epiprot_results/gbm/sz30_hw/sub-XXX.npz: F, names, seizures (format of detect.py).

Usage: python -m epiprot.gbm.tc30s_features --raw-dir /raw --out-dir epiprot_results/gbm/sz30_hw
"""
from __future__ import annotations

import argparse
import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from .features import feature_names as spec_names
from .features import window_features
from .hrv import r_peaks
from .tc_features import _read, _run_num

W = 30.0
FS = 256.0
SEG, HOP = 256, 128
FBINS = np.arange(1, 41)          # Hz, = FFT bins of a 256-sample segment at 256 Hz
HR_NAMES = ["hr_mean", "hr_std", "hr_min", "hr_max"]
MIN_HR_SECONDS = 15


def spectrogram_db(x: np.ndarray) -> np.ndarray:
    """x: (n_win, 7680) uV -> (n_win, 40, 59) dB, scipy.signal.spectrogram(..., 'hann', density) semantics."""
    n_seg = (x.shape[1] - SEG) // HOP + 1
    w = np.hanning(SEG + 1)[:-1]                     # periodic Hann (scipy get_window('hann'))
    idx = np.arange(SEG)[None, :] + HOP * np.arange(n_seg)[:, None]
    seg = x[:, idx]                                  # (n_win, n_seg, SEG)
    seg = seg - seg.mean(axis=2, keepdims=True)      # detrend='constant'
    spec = np.fft.rfft(seg * w, axis=2)[:, :, FBINS]
    p = (np.abs(spec) ** 2) * 2 / (FS * (w ** 2).sum())
    return (10 * np.log10(p + 1e-10)).transpose(0, 2, 1).astype(np.float32)


def eeg_features(x2: np.ndarray | None, n: int) -> np.ndarray:
    """x2: (2, samples) uV or None -> (n, 46)."""
    out = np.full((n, 46), np.nan, np.float32)
    if x2 is None:
        return out
    m = int(W * FS)
    for c in range(2):
        xc = x2[c, : n * m]
        if len(xc) < n * m:
            xc = np.pad(xc, (0, n * m - len(xc)), constant_values=np.nan)
        X = spectrogram_db(xc.reshape(n, m).astype(np.float64))
        X3 = np.stack([X, X, X], axis=1)             # window_features expects 3 channels
        F = window_features(X3)[:, :23]              # first channel's 23 features
        bad = ~np.isfinite(X).all(axis=(1, 2))
        F[bad] = np.nan
        out[:, 23 * c:23 * (c + 1)] = F
    return out


def watch_like_hr(peaks: np.ndarray, fs: float, n_sec: int) -> np.ndarray:
    """1 Hz heart rate: 60 / median of the beat intervals that ended in the last 5 s."""
    hr = np.full(n_sec, np.nan, np.float32)
    if len(peaks) < 3:
        return hr
    t = peaks / fs
    rr = np.diff(t)
    te = t[1:]
    ok = (rr > 0.3) & (rr < 2.0)
    te, rr = te[ok], rr[ok]
    lo = np.searchsorted(te, np.arange(n_sec) + 1 - 5, side="right")
    hi = np.searchsorted(te, np.arange(n_sec) + 1, side="right")
    for s in range(n_sec):
        if hi[s] - lo[s] >= 2:
            hr[s] = 60.0 / np.median(rr[lo[s]:hi[s]])
    return hr


def hr_window_features(hr1: np.ndarray, n: int) -> np.ndarray:
    out = np.full((n, 4), np.nan, np.float32)
    for i in range(n):
        v = hr1[int(i * W):int((i + 1) * W)]
        v = v[np.isfinite(v)]
        if len(v) >= MIN_HR_SECONDS:
            out[i] = [v.mean(), v.std(), v.min(), v.max()]
    return out


def names() -> list[str]:
    return spec_names()[:46] + HR_NAMES + ["hr_missing"]     # eegL_* (left), eegC_* (cross channel)


def process(raw_dir: Path, sub: str, out_dir: Path):
    t0 = time.time()
    dst = out_dir / f"{sub}.npz"
    if dst.exists():
        return sub, -1, 0.0
    base = raw_dir / sub / "ses-01"
    blocks, sz, pos = [], [], 0
    for tsv in sorted((base / "eeg").glob("*_events.tsv"), key=_run_num):
        with open(tsv, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        n = int((float(rows[0]["recordingDuration"]) if rows else 0.0) // W)
        if n <= 0:
            continue
        stem = tsv.name.replace("_events.tsv", "")
        xe, fse, _ = _read(base / "eeg" / f"{stem}_eeg.edf")
        ok_eeg = xe is not None and xe.shape[0] >= 2 and fse == FS
        fe = eeg_features(xe[:2] * 1e6 if ok_eeg else None, n)
        del xe
        xc, fsc, _ = _read(base / "ecg" / f"{stem}_ecg.edf")
        if xc is not None:
            try:
                pk = r_peaks(xc[0].astype(np.float64), fsc)
            except Exception:
                pk = np.array([], int)
            fh_ = hr_window_features(watch_like_hr(pk, fsc, int(n * W)), n)
            miss = np.zeros((n, 1), np.float32)
        else:
            fh_ = np.full((n, 4), np.nan, np.float32)
            miss = np.ones((n, 1), np.float32)
        del xc
        blocks.append(np.hstack([fe, fh_, miss]))
        for r in rows:
            if r["eventType"].lower().startswith("sz"):
                o, d = float(r["onset"]), float(r["duration"])
                a = pos + int(o // W)
                b = pos + int(np.ceil((o + d) / W))
                if a < pos + n:
                    sz.append((a, min(max(b, a + 1), pos + n)))
        pos += n
    F = np.vstack(blocks).astype(np.float32)
    sz = sorted(sz)
    tmp = out_dir / f"{sub}.tmp.npz"
    np.savez(tmp, F=F, names=np.array(names()), seizures=np.array(sz, np.int64).reshape(-1, 2))
    tmp.replace(dst)
    return sub, len(F), time.time() - t0


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
        futs = [ex.submit(process, a.raw_dir, s, a.out_dir) for s in subs]
        for i, f in enumerate(as_completed(futs), 1):
            s, n, dt = f.result()
            print(f"[{i}/{len(subs)}] {s}: {'skip' if n < 0 else f'{n} windows in {dt:.0f}s'} "
                  f"| {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

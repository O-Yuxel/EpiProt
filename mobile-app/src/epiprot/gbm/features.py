"""Per-window spectral features from the cached STFT tensors.

Input cache (epiprot_results/1d_cache_final/{train,test}_sub-XXX.npz):
    X: (N, 3, 40, 59) float32 -- log-power (dB) spectrogram per 30 s window,
       channels = [EEG BTEleft, EEG CROSStop, ECG], freq bins 1..40 Hz (1 Hz step),
       59 time bins (~0.5 s hop). Signals were z-scored per recording before STFT.
    y: (N,) float32 -- 1 = pre-ictal (5-30 min before onset), 0 = other, -1 = excluded.
Windows are stored in chronological order (verified from label run structure).

Output (epiprot_results/gbm/features/sub-XXX.npz, uncompressed):
    F: (N, n_feat) float32, y: (N,) float32, names: feature names.

Decompressing the 32 GB cache is the slow part, so this runs once, in parallel.

Usage:
    python -m epiprot.gbm.features --cache-dir epiprot_results/1d_cache_final \
        --out-dir epiprot_results/gbm/features --workers 6
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

CHANNELS = ["eegL", "eegC", "ecg"]
FREQS = np.arange(1, 41, dtype=np.float32)  # bin i <-> (i+1) Hz
BANDS = {
    "delta": (1, 4),
    "theta": (4, 8),
    "alpha": (8, 13),
    "beta": (13, 30),
    "gamma": (30, 41),
}
_BAND_IDX = {b: (FREQS >= lo) & (FREQS < hi) for b, (lo, hi) in BANDS.items()}


def feature_names() -> list[str]:
    per_ch = (
        [f"logpow_{b}" for b in BANDS]
        + [f"relpow_{b}" for b in BANDS]
        + [f"tvar_{b}" for b in BANDS]
        + ["logpow_total", "tvar_total", "theta_alpha", "slow_fast",
           "spec_entropy", "sef90", "peak_freq", "peak_freq_lo"]
    )
    return [f"{c}_{n}" for c in CHANNELS for n in per_ch] + ["ecg_missing"]


def window_features(X: np.ndarray) -> np.ndarray:
    """X: (N, C, F, T) dB spectrograms -> (N, n_feat) float32. Fully vectorised."""
    X = X.astype(np.float32, copy=False)
    N, C = X.shape[0], X.shape[1]
    P = np.power(10.0, X / 10.0, dtype=np.float32)  # linear power (N,C,F,T)
    P_mean = P.mean(axis=3)  # (N,C,F) average spectrum over the window
    total = P_mean.sum(axis=2) + 1e-12  # (N,C)
    eps = 1e-12

    feats = []
    band_pow = {}
    for b, idx in _BAND_IDX.items():
        bp = P_mean[:, :, idx].sum(axis=2) + eps
        band_pow[b] = bp
        feats.append(np.log10(bp))
    for b in BANDS:
        feats.append(band_pow[b] / total)
    # temporal variability inside the window (std over time of band log-power)
    for b, idx in _BAND_IDX.items():
        bt = np.log10(P[:, :, idx, :].sum(axis=2) + eps)  # (N,C,T)
        feats.append(bt.std(axis=2))
    tot_t = np.log10(P.sum(axis=2) + eps)  # (N,C,T)
    feats.append(np.log10(total))
    feats.append(tot_t.std(axis=2))
    feats.append(np.log10(band_pow["theta"] / band_pow["alpha"]))
    feats.append(np.log10((band_pow["delta"] + band_pow["theta"])
                          / (band_pow["alpha"] + band_pow["beta"])))
    p_norm = P_mean / total[:, :, None]
    feats.append(-(p_norm * np.log(p_norm + eps)).sum(axis=2) / np.log(len(FREQS)))
    cum = np.cumsum(p_norm, axis=2)
    feats.append(FREQS[np.clip((cum < 0.9).sum(axis=2), 0, len(FREQS) - 1)])
    feats.append(FREQS[P_mean.argmax(axis=2)])
    # dominant 1-3 Hz component (for ECG this tracks heart rate, 60-180 bpm)
    feats.append(FREQS[:3][P_mean[:, :, :3].argmax(axis=2)])

    per_ch = np.stack(feats, axis=2)  # (N, C, n_per_ch)
    out = per_ch.reshape(N, -1)
    # a missing ECG channel was zero-filled -> spectrogram ~ -100 dB everywhere
    ecg_missing = (X[:, 2].max(axis=(1, 2)) < -90).astype(np.float32)[:, None]
    return np.concatenate([out, ecg_missing], axis=1).astype(np.float32)


def _process(src: Path, out_dir: Path, chunk: int = 2000) -> tuple[str, int, float]:
    t0 = time.time()
    sub = src.stem.split("_", 1)[1]
    dst = out_dir / f"{sub}.npz"
    if dst.exists():
        return sub, -1, 0.0
    with np.load(src) as z:
        X = z["X"]
        y = z["y"].astype(np.float32)
    F = np.concatenate([window_features(X[i:i + chunk]) for i in range(0, len(X), chunk)])
    del X
    tmp = out_dir / f"{sub}.tmp.npz"
    np.savez(tmp, F=F, y=y, names=np.array(feature_names()))
    tmp.replace(dst)
    return sub, len(y), time.time() - t0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="epiprot.gbm.features")
    ap.add_argument("--cache-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(args.cache_dir.glob("*_sub-*.npz"))
    print(f"{len(files)} files, {len(feature_names())} features/window", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_process, f, args.out_dir) for f in files]
        for i, fut in enumerate(as_completed(futs), 1):
            sub, n, dt = fut.result()
            msg = "skip (exists)" if n < 0 else f"{n} windows in {dt:.0f}s"
            print(f"[{i}/{len(files)}] {sub}: {msg} | elapsed {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

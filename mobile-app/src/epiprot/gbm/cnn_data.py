"""One-off conversion of the compressed STFT cache into fast per-patient memmaps.

For each patient: windows put in chronological order (timeline.py), each (channel, freq)
row robust-standardised with the patient's own median/IQR (removes between-patient and
between-device scale differences), stored as float16 .npy -> random access for CNN
training without decompressing 32 GB every run.

Usage: python -m epiprot.gbm.cnn_data --cache-dir epiprot_results/1d_cache_final \
           --raw-dir /raw --out-dir epiprot_results/gbm/spec16 --workers 6
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from .timeline import build_timeline


def convert(src: Path, raw_dir: Path, out_dir: Path) -> tuple[str, int, float]:
    t0 = time.time()
    sub = src.stem.split("_", 1)[1]
    dst = out_dir / f"{sub}.npy"
    if dst.exists():
        return sub, -1, 0.0
    with np.load(src) as z:
        X = z["X"]
    tl = build_timeline(raw_dir, sub, len(X))
    if tl is not None:
        X = X[tl.perm]
    prof = X.mean(axis=3)  # (N, C, F) mean spectrum per window
    med = np.median(prof, axis=0)
    q75, q25 = np.percentile(prof, [75, 25], axis=0)
    iqr = np.maximum(q75 - q25, 1e-3)
    out = np.lib.format.open_memmap(out_dir / f"{sub}.tmp.npy", mode="w+",
                                    dtype=np.float16, shape=X.shape)
    for i in range(0, len(X), 2000):
        blk = (X[i:i + 2000] - med[None, :, :, None]) / iqr[None, :, :, None]
        out[i:i + 2000] = np.clip(blk, -20, 20).astype(np.float16)
    out.flush()
    del out
    (out_dir / f"{sub}.tmp.npy").replace(dst)
    return sub, len(X), time.time() - t0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(a.cache_dir.glob("*_sub-*.npz"))
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(convert, f, a.raw_dir, a.out_dir) for f in files]
        for i, f in enumerate(as_completed(futs), 1):
            s, n, dt = f.result()
            print(f"[{i}/{len(files)}] {s}: {'skip' if n < 0 else f'{n} in {dt:.0f}s'} "
                  f"| {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

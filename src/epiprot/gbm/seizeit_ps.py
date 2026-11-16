"""SeizeIT2 -> per-patient files in the chb_loso format (F, names, seizures).

Window features (epiprot_results/gbm/features) put in chronological order with the raw
timeline, plus HRV (already chronological), seizures from the raw annotations.

Usage: python -m epiprot.gbm.seizeit_ps --feat-dir epiprot_results/gbm/features \
           --hrv-dir epiprot_results/gbm/hrv --raw-dir /raw --out-dir epiprot_results/gbm/sz_ps
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from .timeline import build_timeline


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--feat-dir", type=Path, required=True)
    ap.add_argument("--hrv-dir", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    nsz = 0
    for f in sorted(a.feat_dir.glob("sub-*.npz")):
        z = np.load(f)
        F, names = z["F"].astype(np.float32), [str(x) for x in z["names"]]
        tl = build_timeline(a.raw_dir, f.stem, len(F))
        if tl is None:
            print(f"{f.stem}: timeline mismatch, skipped")
            continue
        F = F[tl.perm]
        hp = a.hrv_dir / f"{f.stem}.npz"
        if hp.exists():
            h = np.load(hp)
            H = h["H"].astype(np.float32)
            if len(H) == len(F):
                F = np.hstack([F, H])
                names += [str(x) for x in h["names"]]
        np.savez(a.out_dir / f"{f.stem}.npz", F=F, names=np.array(names),
                 seizures=np.array(tl.seizures, dtype=np.int64).reshape(-1, 2))
        nsz += len(tl.seizures)
    print(f"done, {nsz} seizures")


if __name__ == "__main__":
    main()

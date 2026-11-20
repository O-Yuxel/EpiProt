"""Minimal EDF reader (numpy only), enough for the SeizeIT2 wearable files."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def read_labels(path: str | Path) -> list[str]:
    with open(path, "rb") as f:
        h = f.read(256)
        ns = int(h[252:256])
        hh = f.read(16 * ns)
    return [hh[i * 16:(i + 1) * 16].decode("latin-1").strip() for i in range(ns)]


def read_edf(path: str | Path) -> dict:
    """Returns labels, units, sampling rates and the signals in physical units."""
    with open(path, "rb") as f:
        h = f.read(256)
        ns, nrec, dur = int(h[252:256]), int(h[236:244]), float(h[244:252])
        hh = f.read(256 * ns)
        raw = np.frombuffer(f.read(), "<i2")

    def text(off: int, w: int) -> list[str]:
        return [hh[off + i * w: off + (i + 1) * w].decode("latin-1").strip() for i in range(ns)]

    def num(off: int) -> np.ndarray:
        return np.array([float(v) for v in text(off, 8)])

    o = 0
    labels = text(o, 16); o += 16 * ns
    o += 80 * ns                                    # transducer
    units = text(o, 8); o += 8 * ns
    pmin = num(o); o += 8 * ns
    pmax = num(o); o += 8 * ns
    dmin = num(o); o += 8 * ns
    dmax = num(o); o += 8 * ns
    o += 80 * ns                                    # prefiltering
    spr = num(o).astype(int)
    rec = int(spr.sum())
    nrec = min(nrec, len(raw) // rec) if nrec > 0 else len(raw) // rec
    raw = raw[: nrec * rec].reshape(nrec, rec)
    sig, c = [], 0
    for i in range(ns):
        d = raw[:, c:c + spr[i]].ravel().astype(np.float64)
        c += spr[i]
        g = (pmax[i] - pmin[i]) / (dmax[i] - dmin[i])
        sig.append((d - dmin[i]) * g + pmin[i])
    return {"labels": labels, "units": units, "fs": [s / dur for s in spr], "signals": sig}

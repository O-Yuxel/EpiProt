"""Temporal-context features (causal: only past windows are used).

A pre-ictal state is a slow change relative to the patient's own baseline, so on top of
the per-window features we add short- and long-term causal moving averages and their
differences. Each patient's features are first robust-standardised with that patient's
own median / IQR (an unsupervised "calibration" step; no labels involved).
"""
from __future__ import annotations

import numpy as np

SHORT = 10    # 5 min
LONG = 120    # 60 min
XLONG = 720   # 6 h


def causal_mean(F: np.ndarray, w: int) -> np.ndarray:
    """Mean over the last `w` windows (fewer at the start), per column."""
    c = np.cumsum(np.vstack([np.zeros((1, F.shape[1]), np.float64), F]), axis=0)
    idx = np.arange(1, len(F) + 1)
    lo = np.maximum(0, idx - w)
    return ((c[idx] - c[lo]) / (idx - lo)[:, None]).astype(np.float32)


def patient_standardise(F: np.ndarray) -> np.ndarray:
    med = np.median(F, axis=0)
    q75, q25 = np.percentile(F, [75, 25], axis=0)
    iqr = q75 - q25
    iqr[iqr < 1e-6] = 1.0
    return ((F - med) / iqr).astype(np.float32)


def build_context(F: np.ndarray, names: list[str]) -> tuple[np.ndarray, list[str]]:
    keep = [i for i, n in enumerate(names) if n != "ecg_missing"]
    base = patient_standardise(F[:, keep])
    bnames = [names[i] for i in keep]
    s = causal_mean(base, SHORT)
    lg = causal_mean(base, LONG)
    xl = causal_mean(base, XLONG)
    X = np.hstack([base, s, s - lg, lg - xl, F[:, [names.index("ecg_missing")]]])
    cols = (bnames + [f"{n}@5m" for n in bnames] + [f"{n}@5m-60m" for n in bnames]
            + [f"{n}@60m-6h" for n in bnames] + ["ecg_missing"])
    return X.astype(np.float32), cols

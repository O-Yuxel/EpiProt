"""Demonstration: why many published seizure-prediction numbers are so high.

Same features and model as epiprot.gbm.cv, but evaluated the way many papers do:
windows from ALL patients are shuffled and split randomly 80/20, so neighbouring 30 s
windows of the same patient and the same pre-ictal period land in both train and test.
Also reports the common balanced-test "accuracy".

Compare with the honest patient-wise result (new patients never seen in training).

Usage: python -m epiprot.gbm.leaky_demo --feat-dir epiprot_results/gbm/features \
           --raw-dir /raw --hrv-dir epiprot_results/gbm/hrv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import (accuracy_score, precision_score, recall_score, roc_auc_score)

from .cv import LGB_PARAMS, load_all


def report(name, y, p, thr=0.5):
    yh = (p >= thr).astype(int)
    print(f"{name:42s} AUC={roc_auc_score(y, p):.3f} recall={recall_score(y, yh):.3f} "
          f"precision={precision_score(y, yh, zero_division=0):.3f} "
          f"accuracy={accuracy_score(y, yh):.3f}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--feat-dir", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--hrv-dir", type=Path, default=None)
    ap.add_argument("--lead-min", type=float, default=30.0)
    ap.add_argument("--sop-min", type=float, default=90.0)
    ap.add_argument("--no-history", dest="history", action="store_false")
    a = ap.parse_args(argv)
    data, _ = load_all(a.feat_dir, 60.0, 30.0, a.lead_min, a.sop_min, a.history, a.raw_dir, a.hrv_dir)
    rng = np.random.default_rng(0)

    # balanced dataset (as in most papers): all positives + equal number of negatives
    Xs, ys, gs = [], [], []
    for gi, (s, d) in enumerate(sorted(data.items())):
        pos, neg = np.flatnonzero(d["y"] == 1), np.flatnonzero(d["y"] == 0)
        neg = rng.choice(neg, min(len(neg), max(len(pos), 1)), replace=False)
        idx = np.r_[pos, neg]
        Xs.append(d["X"][idx]); ys.append(d["y"][idx]); gs.append(np.full(len(idx), gi))
    X, y, g = np.vstack(Xs), np.concatenate(ys), np.concatenate(gs)
    print(f"balanced set: {len(y)} windows, {int(y.sum())} positive, {len(data)} patients")

    params = LGB_PARAMS | {"metric": "auc"}
    # 1) random window split (leaky)
    perm = rng.permutation(len(y))
    cut = int(0.8 * len(y))
    tr, te = perm[:cut], perm[cut:]
    b = lgb.train(params, lgb.Dataset(X[tr], y[tr]), 600)
    report("RANDOM window split (common in papers)", y[te], b.predict(X[te]))

    # 2) patient-wise split (honest): test patients never seen
    pats = rng.permutation(len(data))
    test_p = set(pats[: len(pats) // 5])
    te2 = np.isin(g, list(test_p))
    b2 = lgb.train(params, lgb.Dataset(X[~te2], y[~te2]), 600)
    report("PATIENT-wise split (new patients)", y[te2], b2.predict(X[te2]))


if __name__ == "__main__":
    main()

"""Diagnostics: is the signal there at all?

(a) detection   : ictal windows vs clean interictal, patient-wise CV, cross-patient.
                  If this works the features are sound.
(b) personalised: per patient, train on the chronologically first part (containing
                  >= 2 lead seizures), test on the rest (>= 1 lead seizure).

Usage: python -m epiprot.gbm.diagnostics --feat-dir epiprot_results/gbm/features
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import roc_auc_score

from .context import build_context
from .labels import _runs, relabel

P = dict(objective="binary", learning_rate=0.05, num_leaves=31, min_child_samples=50,
         feature_fraction=0.6, bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=0)
GAP = 10  # first 10 windows of each -1 run are the 5-min gap, the rest is ictal


def ictal_labels(y):
    out = np.where(y == 0, 0.0, -1.0)
    for s, e in _runs(y == -1):
        out[s + GAP:e] = 1.0
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--feat-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    data = {}
    for f in sorted(a.feat_dir.glob("sub-*.npz")):
        with np.load(f) as z:
            X, _ = build_context(z["F"], list(z["names"]))
            yc, ev = relabel(z["y"])
            data[f.stem] = (X, z["y"], yc, ev)
    subs = sorted(data)
    rng = np.random.default_rng(0)
    order = list(subs)
    rng.shuffle(order)
    res = {}

    # (a) detection, cross-patient 5-fold
    probs, ys = [], []
    for k in range(5):
        te = set(order[k::5])
        def stack(ss, neg_cap):
            Xs, Ys = [], []
            for s in ss:
                X, y, _, _ = data[s]
                yi = ictal_labels(y)
                pos, neg = np.flatnonzero(yi == 1), np.flatnonzero(yi == 0)
                if neg_cap and len(neg) > neg_cap:
                    neg = rng.choice(neg, neg_cap, replace=False)
                idx = np.r_[pos, neg]
                Xs.append(X[idx]); Ys.append(yi[idx])
            return np.vstack(Xs), np.concatenate(Ys)
        Xtr, ytr = stack([s for s in subs if s not in te], 3000)
        Xte, yte = stack(sorted(te), 0)
        b = lgb.train(P, lgb.Dataset(Xtr, ytr), 300)
        probs.append(b.predict(Xte)); ys.append(yte)
    p, y = np.concatenate(probs), np.concatenate(ys)
    res["detection_cross_patient_auc"] = float(roc_auc_score(y, p))
    print(f"(a) DETECTION cross-patient AUC = {res['detection_cross_patient_auc']:.3f} "
          f"(ictal windows={int(y.sum())})", flush=True)

    # (b) personalised prediction
    per = {}
    pooled_p, pooled_y = [], []
    for s in subs:
        X, _, yc, ev = data[s]
        if len(ev) < 3:
            continue
        cut = ev[-2].pos_start - 1 if len(ev) == 3 else ev[len(ev) * 2 // 3].pos_start - 1
        tr = np.arange(len(yc)) < cut
        mtr, mte = tr & (yc >= 0), (~tr) & (yc >= 0)
        if yc[mte].sum() == 0 or yc[mtr].sum() == 0:
            continue
        b = lgb.train(P | {"min_child_samples": 20}, lgb.Dataset(X[mtr], yc[mtr]), 200)
        pp = b.predict(X[mte])
        per[s] = {"events_train": int(sum(e.pos_end <= cut for e in ev)),
                  "events_test": int(sum(e.pos_start > cut for e in ev)),
                  "auc": float(roc_auc_score(yc[mte], pp))}
        pooled_p.append(pp); pooled_y.append(yc[mte])
    aucs = np.array([v["auc"] for v in per.values()])
    res["personalised"] = {"n_patients": len(per), "median_auc": float(np.median(aucs)),
                           "mean_auc": float(aucs.mean()),
                           "frac_auc_gt_0.7": float((aucs > 0.7).mean()),
                           "frac_auc_gt_0.8": float((aucs > 0.8).mean()), "per_patient": per}
    print(f"(b) PERSONALISED prediction: {len(per)} patients with >=3 lead seizures | "
          f"median AUC={np.median(aucs):.3f} mean={aucs.mean():.3f} "
          f">0.7: {(aucs > 0.7).mean():.0%} >0.8: {(aucs > 0.8).mean():.0%}", flush=True)
    print("   per-patient AUC:", {k: round(v["auc"], 2) for k, v in per.items()})
    if a.out:
        a.out.write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

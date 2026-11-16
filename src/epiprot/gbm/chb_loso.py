"""CHB-MIT patient-specific seizure PREDICTION, leave-one-seizure-out (honest).

Clinical scenario: the device is calibrated per patient with the EEG already recorded
during the hospital video-EEG stay (no new seizures needed). Evaluation mimics this:

  * per patient, the timeline is split into segments, one per lead seizure (boundaries at
    the midpoints between consecutive lead-seizure onsets). Every window is tested
    exactly once.
  * test segment e: model trained on all other segments (1 h margin removed around the
    test segment so neighbouring windows cannot leak).
  * the alarm threshold / smoothing is chosen WITHOUT the test seizure: nested
    leave-one-seizure-out inside the training segments, max sensitivity subject to an
    FA/h budget.
  * labels: positive = [onset - L - S, onset - L) (alarm at least L minutes ahead),
    the last L minutes, ictal and 60 min post-ictal excluded; training negatives must
    be >= `inter_gap_h` from any seizure. False alarms are counted in all clean
    interictal windows (y == 0).

Usage: python -m epiprot.gbm.chb_loso --feat-dir epiprot_results/gbm/chb \
           --out-dir epiprot_results/gbm/chb_loso --lead-min 30 --sop-min 30
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import roc_auc_score

from .context import causal_mean, patient_standardise
from .events import PatientSeries, evaluate, pick_operating_point
from .labels import WIN_PER_MIN, Event, relabel

PARAMS = {"objective": "binary", "learning_rate": 0.03, "num_leaves": 15,
          "min_child_samples": 20, "feature_fraction": 0.3, "bagging_fraction": 0.8,
          "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1, "seed": 42,
          "num_threads": 10}
KS = (1, 4, 10, 20, 40)


def context(F: np.ndarray, mode: str = "full") -> np.ndarray:
    med = np.nanmedian(F, axis=0)
    F = np.where(np.isnan(F), med, F)
    b = patient_standardise(F)
    s, lg, xl = causal_mean(b, 10), causal_mean(b, 120), causal_mean(b, 720)
    if mode == "base":
        return b
    if mode == "short":
        return np.hstack([b, s, causal_mean(b, 30)]).astype(np.float32)
    return np.hstack([b, s, s - lg, lg - xl]).astype(np.float32)


def segments(events: list[Event], n: int) -> list[tuple[int, int]]:
    on = [e.onset for e in events]
    cuts = [0] + [(on[i] + on[i + 1]) // 2 for i in range(len(on) - 1)] + [n]
    return list(zip(cuts[:-1], cuts[1:]))


def train_mask(n, segs, exclude, margin):
    m = np.ones(n, bool)
    for j in exclude:
        a, b = segs[j]
        m[max(0, a - margin):min(n, b + margin)] = False
    return m


def fit(X, y, m, rounds):
    idx = np.flatnonzero(m & (y >= 0))
    yy = y[idx]
    if yy.sum() == 0 or yy.sum() == len(yy):
        return None
    pos = max(1, int(yy.sum()))
    p = PARAMS | {"scale_pos_weight": (len(yy) - pos) / pos}
    return lgb.train(p, lgb.Dataset(X[idx], yy), rounds)


def seg_series(sub, prob, y_eval, events, a, b):
    ev = [Event(e.pos_start - a, e.pos_end - a, e.onset - a) for e in events
          if a <= e.onset < b]
    return PatientSeries(sub, prob, y_eval[a:b], ev)


def run_patient(path: Path, lead, sop, max_fah, inter_gap_h, margin_h, rounds, ctx="full"):
    z = np.load(path)
    sub = path.stem
    X = context(z["F"], ctx)
    n = len(X)
    seizures = [tuple(map(int, s)) for s in z["seizures"]]
    y_eval, events = relabel(np.zeros(n, np.float32), lead_min=lead, sop_min=sop,
                             seizures=seizures)
    # a seizure inside another lead seizure's pre-ictal period = same cluster:
    # only the first one is a lead event
    ons = np.array([s[0] for s in seizures])
    keep = [e for e in events if not ((ons >= e.pos_start) & (ons < e.onset)).any()]
    for e in events:
        if e not in keep:
            seg = y_eval[e.pos_start:e.pos_end]
            seg[seg == 1] = -1.0
    events = keep
    y_tr = y_eval.copy()
    gap = int(inter_gap_h * 60 * WIN_PER_MIN)
    for on, end in seizures:
        lo, hi = max(0, on - gap), min(n, end + gap)
        blk = y_tr[lo:hi]
        blk[blk == 0] = -1.0
    if len(events) < 3:
        return {"sub": sub, "lead_events": len(events), "skipped": True}
    segs = segments(events, n)
    margin = int(margin_h * 60 * WIN_PER_MIN)
    refr = int(sop * WIN_PER_MIN)
    oof = np.zeros(n, np.float32)
    folds = []
    for e in range(len(events)):
        # nested: choose threshold/smoothing on the other seizures only
        inner = []
        for j in range(len(events)):
            if j == e:
                continue
            bi = fit(X, y_tr, train_mask(n, segs, [e, j], margin), rounds)
            if bi is None:
                continue
            a, b = segs[j]
            inner.append(seg_series(sub, bi.predict(X[a:b]), y_eval, events, a, b))
        op = pick_operating_point(inner, max_fah, ks=KS, refractory=refr, sop_min=sop)
        bm = fit(X, y_tr, train_mask(n, segs, [e], margin), rounds)
        a, b = segs[e]
        oof[a:b] = bm.predict(X[a:b])
        r = evaluate([seg_series(sub, oof[a:b], y_eval, events, a, b)], op["thr"], op["k"],
                     refr, sop)
        folds.append({"seizure": e, "thr": op["thr"], "k": op["k"],
                      "inner_sens": op["sensitivity"], "inner_fah": op["fa_per_hour"],
                      "hit": r["predicted"], "fa": r["false_alarms"],
                      "inter_h": r["interictal_hours"]})
    hit = sum(f["hit"] for f in folds)
    fa = sum(f["fa"] for f in folds)
    hours = sum(f["inter_h"] for f in folds)
    fah = fa / hours if hours else float("nan")
    m = y_eval >= 0
    auc = float(roc_auc_score(y_eval[m], oof[m])) if len(np.unique(y_eval[m])) == 2 else None
    return {"sub": sub, "seizures": len(seizures), "lead_events": len(events),
            "predicted": hit, "sensitivity": hit / len(events), "false_alarms": fa,
            "interictal_hours": hours, "fa_per_hour": fah,
            "chance_sensitivity": float(1 - np.exp(-fah * sop / 60)),
            "window_auc": auc, "folds": folds}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--feat-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--lead-min", type=float, default=30.0)
    ap.add_argument("--sop-min", type=float, default=30.0)
    ap.add_argument("--max-fah", type=float, default=0.15)
    ap.add_argument("--inter-gap-h", type=float, default=1.0)
    ap.add_argument("--margin-h", type=float, default=1.0)
    ap.add_argument("--rounds", type=int, default=300)
    ap.add_argument("--ctx", choices=["full", "short", "base"], default="full")
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for f in sorted(a.feat_dir.glob("chb*.npz")):
        r = run_patient(f, a.lead_min, a.sop_min, a.max_fah, a.inter_gap_h, a.margin_h,
                        a.rounds, a.ctx)
        res.append(r)
        if r.get("skipped"):
            print(f"{r['sub']}: only {r['lead_events']} lead seizures -> skipped", flush=True)
        else:
            print(f"{r['sub']}: {r['predicted']}/{r['lead_events']} predicted "
                  f"(sens {r['sensitivity']:.0%}), FA/h {r['fa_per_hour']:.3f}, "
                  f"chance {r['chance_sensitivity']:.0%}, AUC {r['window_auc']}", flush=True)
    ok = [r for r in res if not r.get("skipped")]
    ev = sum(r["lead_events"] for r in ok)
    hit = sum(r["predicted"] for r in ok)
    fa = sum(r["false_alarms"] for r in ok)
    hrs = sum(r["interictal_hours"] for r in ok)
    fah = fa / hrs
    summ = {"lead_min": a.lead_min, "sop_min": a.sop_min, "max_fah": a.max_fah,
            "patients": len(ok), "events": ev, "predicted": hit, "sensitivity": hit / ev,
            "fa_per_hour": fah, "chance_sensitivity": float(1 - np.exp(-fah * a.sop_min / 60)),
            "patients_sens_ge_80": sum(r["sensitivity"] >= 0.8 for r in ok)}
    print(json.dumps(summ, indent=2))
    (a.out_dir / "results.json").write_text(json.dumps({"summary": summ, "patients": res},
                                                       indent=2))


if __name__ == "__main__":
    main()

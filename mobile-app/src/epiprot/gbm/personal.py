"""Patient-adapted prediction: global model + fine-tuning on the patient's own past.

Device scenario: the headset ships with a global model; during the first days/weeks
of wear it records the patient's seizures and adapts. Evaluated strictly
chronologically per patient:

    past   = windows before the first-half cut (>= ceil(n/2) lead seizures)
    future = windows after the cut (remaining lead seizures)

For every test patient (patient-wise K-fold, so the global model never saw them):
    global   : model trained on the other folds' patients only
    personal : model trained on the patient's own past only
    adapted  : global model, boosting continued on the patient's own past

Thresholds for event-level metrics are set from the PAST only: the score quantile that
gives the FA budget on the patient's past interictal windows (out-of-sample for the
global model, in-sample for adapted/personal -> optimistic FA, reported as such).

Usage: python -m epiprot.gbm.personal --feat-dir epiprot_results/gbm/features \
           --out-dir epiprot_results/gbm/personal_30_30 --lead-min 30 --sop-min 30 --tsls
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import roc_auc_score

from .cv import LGB_PARAMS, load_all, train_one
from .events import PatientSeries, evaluate, smooth
from .labels import Event

ADAPT_PARAMS = LGB_PARAMS | {"learning_rate": 0.05, "min_child_samples": 20,
                             "num_leaves": 15, "metric": "none"}


def split_patient(d, min_events=3):
    ev = d["events"]
    if len(ev) < min_events:
        return None
    m = int(np.ceil(len(ev) / 2))
    cut = (ev[m - 1].onset + ev[m].pos_start) // 2  # between last past and first future event
    return cut, ev[:m], [Event(e.pos_start - cut, e.pos_end - cut, e.onset - cut) for e in ev[m:]]


def balanced_rows(y, rng, neg_cap=4000):
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    if len(neg) > neg_cap:
        neg = rng.choice(neg, neg_cap, replace=False)
    return np.sort(np.r_[pos, neg])


def thr_from_past(score_past, y_past, k, fa_budget, refractory):
    """Lowest threshold whose alarm count on past interictal windows stays within budget."""
    s = smooth(score_past, k)
    hours = (y_past == 0).sum() * 30 / 3600
    for q in np.linspace(0.90, 0.99999, 300):
        t = float(np.quantile(s, q))
        ps = PatientSeries("p", score_past, y_past, [])
        r = evaluate([ps], t, k, refractory)
        if hours > 0 and r["false_alarms"] / hours <= fa_budget:
            return t
    return float(s.max()) + 1e-9


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--feat-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--lead-min", type=float, default=30.0)
    ap.add_argument("--sop-min", type=float, default=30.0)
    ap.add_argument("--tsls", action="store_true")
    ap.add_argument("--raw-dir", type=Path, default=None)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--adapt-rounds", type=int, default=150)
    ap.add_argument("--k", type=int, default=8, help="smoothing windows for alarms")
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)  # noqa: E731

    data, cols = load_all(a.feat_dir, 60.0, 30.0, a.lead_min, a.sop_min, a.tsls, a.raw_dir)
    subs = sorted(data)
    refr = int(a.sop_min * 2)
    rng = np.random.default_rng(42)
    order = list(subs)
    rng.shuffle(order)
    folds = [order[i::a.folds] for i in range(a.folds)]
    eligible = {s for s in subs if split_patient(data[s])}
    log(f"{len(subs)} patients, {len(eligible)} with >=3 lead seizures (evaluated)")

    rows = {}
    series = {m: [] for m in ("global", "personal", "adapted")}
    past_series = {m: [] for m in series}
    for fi, test_subs in enumerate(folds):
        tr = [s for s in subs if s not in set(test_subs)]
        g, _, _ = train_one(data, tr, rng, 4000)
        for s in test_subs:
            if s not in eligible:
                continue
            d = data[s]
            cut, _, fut_events = split_patient(d)
            X, y = d["X"], d["y"]
            Xp, yp, Xf, yf = X[:cut], y[:cut], X[cut:], y[cut:]
            idx = balanced_rows(yp, rng)
            ds = lgb.Dataset(Xp[idx], yp[idx], free_raw_data=False)
            pers = lgb.train(ADAPT_PARAMS, ds, a.adapt_rounds)
            adap = lgb.train(ADAPT_PARAMS, ds, a.adapt_rounds, init_model=g,
                             keep_training_booster=True)
            preds = {
                "global": (g.predict(Xp, num_iteration=g.best_iteration),
                           g.predict(Xf, num_iteration=g.best_iteration)),
                "personal": (pers.predict(Xp), pers.predict(Xf)),
                "adapted": (adap.predict(Xp), adap.predict(Xf)),
            }
            mf = yf >= 0
            r = {"past_events": len(d["events"]) - len(fut_events),
                 "future_events": len(fut_events)}
            for m, (pp, pf) in preds.items():
                r[f"auc_{m}"] = float(roc_auc_score(yf[mf], pf[mf])) if yf[mf].min() < 1 else None
                series[m].append(PatientSeries(s, pf, yf, fut_events))
                past_series[m].append((pp, yp))
            rows[s] = r
        log(f"fold {fi + 1}/{a.folds} done ({len(rows)} patients so far)")

    res = {"config": {k: str(v) for k, v in vars(a).items()}, "n_patients": len(rows),
           "per_patient": rows, "summary": {}}
    for m in series:
        aucs = np.array([r[f"auc_{m}"] for r in rows.values() if r[f"auc_{m}"] is not None])
        summ = {"median_auc": float(np.median(aucs)), "mean_auc": float(aucs.mean()),
                "frac_auc_ge_0.8": float((aucs >= 0.8).mean()),
                "frac_auc_ge_0.9": float((aucs >= 0.9).mean())}
        for b in (0.1, 0.2, 0.5):
            evs = []
            for ps, (pp, yp) in zip(series[m], past_series[m]):
                t = thr_from_past(pp, yp, a.k, b, refr)
                evs.append((ps, t))
            agg = {"events": 0, "predicted": 0, "false_alarms": 0, "interictal_hours": 0.0}
            for ps, t in evs:
                r = evaluate([ps], t, a.k, refr, a.sop_min)
                for key in agg:
                    agg[key] += r[key]
            fah = agg["false_alarms"] / agg["interictal_hours"]
            agg |= {"sensitivity": agg["predicted"] / max(agg["events"], 1), "fa_per_hour": fah,
                    "chance_sensitivity": float(1 - np.exp(-fah * a.sop_min / 60))}
            summ[f"event_fa_budget_{b}"] = agg
        res["summary"][m] = summ
        e2 = summ["event_fa_budget_0.2"]
        log(f"{m:9s}: median AUC={summ['median_auc']:.3f} mean={summ['mean_auc']:.3f} "
            f">=0.8: {summ['frac_auc_ge_0.8']:.0%} | budget 0.2/h -> sens={e2['sensitivity']:.3f} "
            f"({e2['predicted']}/{e2['events']}) FA/h={e2['fa_per_hour']:.3f} "
            f"chance={e2['chance_sensitivity']:.3f}")
    (a.out_dir / "personal_results.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

"""Patient-wise cross-validated LightGBM seizure prediction on SeizeIT2.

Fixes vs. the old CNN pipeline (epiprot.cnn.seizeit_cli):
  * negatives are sampled from EVERY patient (old code took all 100k from sub-001..009)
  * separate validation patients for early stopping / threshold choice (old code used test)
  * post-ictal and 30-60 min pre-onset windows are no longer "negatives"
  * evaluation is patient-wise K-fold over all 125 patients, plus event-level metrics

Usage:
    python -m epiprot.gbm.cv --feat-dir epiprot_results/gbm/features \
        --out-dir epiprot_results/gbm/run1 --folds 5
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

from .context import build_context
from .events import PatientSeries, evaluate, pick_operating_point
from .labels import relabel, seizures_from_cache_labels
from .timeline import build_timeline

FA_BUDGETS = (0.1, 0.2, 0.5)  # false alarms per hour

LGB_PARAMS = dict(
    objective="binary", learning_rate=0.05, num_leaves=63, min_child_samples=200,
    feature_fraction=0.6, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
    metric="average_precision", verbose=-1, num_threads=0, seed=42,
)


def time_since_last_seizure(y_orig: np.ndarray, seizures=None) -> np.ndarray:
    """Causal: log10(hours since the end of the last seizure); 3.0 (~1000 h) if none yet.
    On a device the past seizures are known (diary / detector), so this is legitimate."""
    n = len(y_orig)
    last = np.full(n, -1, np.int64)
    if seizures is None:
        seizures = seizures_from_cache_labels(y_orig)
    for _onset, end in seizures:
        if end < n:
            last[end] = end
    last = np.maximum.accumulate(last)
    hrs = (np.arange(n) - last) * 30 / 3600
    return np.where(last < 0, 3.0, np.log10(hrs + 1e-3)).astype(np.float32)[:, None]


HISTORY_COLS = ["log_h_since_last_seizure", "log_h_since_2nd_last_seizure",
                "n_seizures_6h", "n_seizures_24h", "n_seizures_72h", "n_seizures_so_far"]


def seizure_history(y_orig: np.ndarray, seizures=None) -> np.ndarray:
    """Causal seizure-diary features: only seizures that have ENDED before window i count."""
    n = len(y_orig)
    if seizures is None:
        seizures = seizures_from_cache_labels(y_orig)
    ends = np.array(sorted(e for _o, e in seizures if e < n), dtype=np.int64)
    idx = np.arange(n)
    k = np.searchsorted(ends, idx, side="right")  # number of seizures ended at or before i

    def since(j):
        ok = k >= j
        h = np.full(n, 1000.0)
        h[ok] = (idx[ok] - ends[k[ok] - j]) * 30 / 3600
        return np.log10(h + 1e-3)

    def count(hours):
        lo = np.searchsorted(ends, idx - int(hours * 120), side="right")
        return (k - lo).astype(np.float32)

    return np.stack([since(1), since(2), count(6), count(24), count(72),
                     k.astype(np.float32)], axis=1).astype(np.float32)


def load_all(feat_dir: Path, postictal_min: float, pre_buffer_min: float,
             lead_min: float = 5.0, sop_min: float = 25.0, tsls: bool = False,
             raw_dir: Path | None = None, hrv_dir: Path | None = None):
    """Load features, rebuild context and labels. With `raw_dir`, windows are put in true
    chronological run order and seizures come from the raw annotations (see timeline.py)."""
    data = {}
    n_fixed = 0
    for f in sorted(feat_dir.glob("sub-*.npz")):
        if ".tmp" in f.name:
            continue
        with np.load(f) as z:
            F, y, names = z["F"], z["y"], list(z["names"])
        seizures = None
        if raw_dir is not None:
            tl = build_timeline(raw_dir, f.stem, len(y))
            if tl is not None:
                n_fixed += int((tl.perm != np.arange(len(y))).any())
                F, y, seizures = F[tl.perm], y[tl.perm], tl.seizures
            else:
                print(f"WARNING: {f.stem}: timeline could not be aligned, using cache labels")
        if hrv_dir is not None and seizures is not None:
            hz = np.load(hrv_dir / f"{f.stem}.npz")
            H = hz["H"]
            if len(H) == len(F):
                miss = ~np.isfinite(H[:, :1])
                med = np.nanmedian(H, axis=0) if np.isfinite(H).any() else np.zeros(H.shape[1])
                H = np.where(np.isfinite(H), H, np.nan_to_num(med)[None, :]).astype(np.float32)
                F = np.hstack([F, H, miss.astype(np.float32)])
                names = names + list(hz["names"]) + ["hrv_missing"]
            else:
                print(f"WARNING: {f.stem}: HRV length {len(H)} != {len(F)}, skipped")
        X, cols = build_context(F, names)
        if tsls:
            X = np.hstack([X, seizure_history(y, seizures)])
            cols = cols + HISTORY_COLS
        yc, events = relabel(y, postictal_min, pre_buffer_min,
                             lead_min=lead_min, sop_min=sop_min, seizures=seizures)
        data[f.stem] = {"X": X, "y_orig": y, "y": yc, "events": events}
    if raw_dir is not None:
        print(f"timeline: {n_fixed} patients re-ordered chronologically", flush=True)
    return data, cols


def make_train_set(data, subs, neg_per_patient, rng):
    Xs, ys = [], []
    for s in subs:
        d = data[s]
        pos = np.flatnonzero(d["y"] == 1)
        neg = np.flatnonzero(d["y"] == 0)
        if len(neg) > neg_per_patient:
            neg = rng.choice(neg, neg_per_patient, replace=False)
        idx = np.sort(np.r_[pos, neg])
        Xs.append(d["X"][idx])
        ys.append(d["y"][idx])
    return np.vstack(Xs), np.concatenate(ys)


def labeled(data, subs, key="y"):
    X = np.vstack([data[s]["X"][data[s][key] >= 0] for s in subs])
    y = np.concatenate([data[s][key][data[s][key] >= 0] for s in subs])
    return X, y


def window_metrics(y, p) -> dict:
    prec, rec, thr = precision_recall_curve(y, p)
    out = {"n": int(len(y)), "pos": int(y.sum()), "auc": float(roc_auc_score(y, p)),
           "pr_auc": float(average_precision_score(y, p))}
    for r in (0.9, 0.7, 0.5):
        ok = rec[:-1] >= r
        out[f"precision@recall{r}"] = float(prec[:-1][ok].max()) if ok.any() else 0.0
    return out


def train_one(data, train_subs, rng, neg_per_patient, val_frac=0.15):
    train_subs = list(train_subs)
    rng.shuffle(train_subs)
    n_val = max(3, int(round(val_frac * len(train_subs))))
    val_subs, fit_subs = train_subs[:n_val], train_subs[n_val:]
    Xtr, ytr = make_train_set(data, fit_subs, neg_per_patient, rng)
    Xva, yva = labeled(data, val_subs)
    dtr = lgb.Dataset(Xtr, ytr, free_raw_data=True)
    dva = lgb.Dataset(Xva, yva, reference=dtr)
    booster = lgb.train(LGB_PARAMS, dtr, num_boost_round=3000, valid_sets=[dva],
                        callbacks=[lgb.early_stopping(150, verbose=False)])
    return booster, val_subs, fit_subs


def series_for(data, subs, booster):
    return [PatientSeries(s, booster.predict(data[s]["X"], num_iteration=booster.best_iteration),
                          data[s]["y"], data[s]["events"]) for s in subs]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="epiprot.gbm.cv")
    ap.add_argument("--feat-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--neg-per-patient", type=int, default=4000)
    ap.add_argument("--postictal-min", type=float, default=60.0)
    ap.add_argument("--pre-buffer-min", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--lead-min", type=float, default=30.0, help="min warning time before onset")
    ap.add_argument("--sop-min", type=float, default=30.0, help="length of the pre-ictal period")
    ap.add_argument("--tsls", action="store_true", help="add time-since-last-seizure feature")
    ap.add_argument("--only-cols", default=None,
                    help="regex: keep only matching feature columns (ablation)")
    ap.add_argument("--hrv-dir", type=Path, default=None, help="HRV features (needs --raw-dir)")
    ap.add_argument("--raw-dir", type=Path, default=None,
                    help="SeizeIT2 BIDS root: fixes run order and uses raw seizure times")
    ap.add_argument("--no-final", action="store_true", help="skip the all-patients final model")
    args = ap.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)  # noqa: E731

    data, cols = load_all(args.feat_dir, args.postictal_min, args.pre_buffer_min,
                          args.lead_min, args.sop_min, args.tsls, args.raw_dir, args.hrv_dir)
    if args.only_cols:
        import re
        keep = [i for i, c in enumerate(cols) if re.search(args.only_cols, c)]
        cols = [cols[i] for i in keep]
        for d in data.values():
            d["X"] = d["X"][:, keep]
    refr = int(args.sop_min * 2)
    ev_kw = dict(refractory=refr, sop_min=args.sop_min)
    subs = sorted(data)
    n_ev = sum(len(d["events"]) for d in data.values())
    log(f"{len(subs)} patients, {len(cols)} features, {n_ev} lead seizures, "
        f"pos={sum(int((d['y'] == 1).sum()) for d in data.values())} "
        f"neg={sum(int((d['y'] == 0).sum()) for d in data.values())}")

    rng = np.random.default_rng(args.seed)
    order = list(subs)
    rng.shuffle(order)
    folds = [order[i::args.folds] for i in range(args.folds)]

    test_series, oof = [], {}
    fold_ops = []
    importance = np.zeros(len(cols))
    for fi, test_subs in enumerate(folds):
        train_subs = [s for s in subs if s not in set(test_subs)]
        booster, val_subs, _ = train_one(data, train_subs, rng, args.neg_per_patient)
        importance += booster.feature_importance("gain")
        val_series = series_for(data, val_subs, booster)
        ts = series_for(data, test_subs, booster)
        test_series += ts
        for s in ts:
            oof[s.sub] = s.prob
        ops = {}
        for b in FA_BUDGETS:
            op = pick_operating_point(val_series, b, **ev_kw)
            ops[b] = {"thr": op["thr"], "k": op["k"]}
        fold_ops.append({"test": test_subs, "val": val_subs, "best_iter": booster.best_iteration,
                         "ops": ops, "series": ts})
        Xte, yte = labeled(data, test_subs)
        wm = window_metrics(yte, booster.predict(Xte, num_iteration=booster.best_iteration))
        log(f"fold {fi + 1}/{args.folds}: iters={booster.best_iteration} "
            f"AUC={wm['auc']:.3f} PR-AUC={wm['pr_auc']:.3f} P@R0.9={wm['precision@recall0.9']:.3f}")

    # ---- pooled out-of-fold results over all patients ----
    y_all = np.concatenate([data[s]["y"] for s in subs])
    p_all = np.concatenate([oof[s] for s in subs])
    m = y_all >= 0
    results = {"config": {k: str(v) for k, v in vars(args).items()},
               "n_patients": len(subs), "n_features": len(cols), "lead_seizures": n_ev,
               "window_clean_labels": window_metrics(y_all[m], p_all[m])}
    yo = np.concatenate([data[s]["y_orig"] for s in subs])
    mo = yo >= 0
    results["window_original_labels"] = window_metrics(yo[mo], p_all[mo])

    results["event_level"] = {}
    for b in FA_BUDGETS:
        agg = {"events": 0, "predicted": 0, "false_alarms": 0, "interictal_hours": 0.0}
        per_patient = {}
        for fo in fold_ops:
            r = evaluate(fo["series"], fo["ops"][b]["thr"], fo["ops"][b]["k"], **ev_kw)
            for key in agg:
                agg[key] += r[key]
            per_patient |= r["per_patient"]
        fah = agg["false_alarms"] / agg["interictal_hours"]
        agg |= {"sensitivity": agg["predicted"] / agg["events"], "fa_per_hour": fah,
                "fa_per_day": fah * 24, "chance_sensitivity": float(1 - np.exp(-fah * args.sop_min / 60))}
        results["event_level"][f"fa_budget_{b}"] = agg
        results.setdefault("per_patient", {})[f"fa_budget_{b}"] = per_patient
        log(f"event-level (val-chosen thr, FA budget {b}/h): sens={agg['sensitivity']:.3f} "
            f"({agg['predicted']}/{agg['events']}) FA/h={fah:.3f} chance_sens={agg['chance_sensitivity']:.3f}")

    w = results["window_clean_labels"]
    log(f"POOLED window-level (clean labels): AUC={w['auc']:.3f} PR-AUC={w['pr_auc']:.3f} "
        f"P@R0.9={w['precision@recall0.9']:.3f} P@R0.5={w['precision@recall0.5']:.3f}")

    imp = sorted(zip(cols, importance / args.folds), key=lambda t: -t[1])
    results["top_features"] = [[c, float(v)] for c, v in imp[:30]]
    np.savez(args.out_dir / "oof_predictions.npz", **{s: oof[s] for s in subs})
    (args.out_dir / "results.json").write_text(json.dumps(results, indent=2))
    log(f"saved {args.out_dir / 'results.json'}")

    if not args.no_final:
        booster, val_subs, _ = train_one(data, subs, rng, args.neg_per_patient)
        vs = series_for(data, val_subs, booster)
        ops = {str(b): {k: v for k, v in pick_operating_point(vs, b, **ev_kw).items()
                        if k in ("thr", "k")}
               for b in FA_BUDGETS}
        booster.save_model(str(args.out_dir / "final_model.txt"),
                           num_iteration=booster.best_iteration)
        (args.out_dir / "final_model_config.json").write_text(json.dumps(
            {"features": cols, "operating_points": ops, "refractory_windows": refr,
             "lead_min": args.lead_min, "sop_min": args.sop_min,
             "window_seconds": 30, "note": "features: epiprot.gbm.features + epiprot.gbm.context"},
            indent=2))
        log(f"final model saved (val patients {val_subs})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

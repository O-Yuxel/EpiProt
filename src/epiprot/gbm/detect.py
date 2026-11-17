"""Real-time seizure DETECTION on SeizeIT2, patient-wise CV, several models x feature sets.

Data: epiprot_results/gbm/sz_ps/sub-XXX.npz (chronological 30 s window features: 2-channel
behind-the-ear EEG + ECG spectra, HRV from R-peaks; seizures from the raw annotations).

Labels per 30 s window:
  1  = overlaps a seizure
  -1 = 1 window before onset and 10 windows (5 min) after the end (transition, ignored)
  0  = everything else (false alarms are counted here)

Feature sets (all causal: only the current and past windows):
  direct : the window's own feature values, unchanged (no per-patient normalisation)
  change : how the window differs from the patient's own recent past, scaled by the
           patient's IQR: x(t) - mean(previous 5 min), x(t) - mean(previous 60 min),
           x(t) - x(t-1)
  both   : direct + change

Models: LightGBM, logistic regression, random forest, MLP (neural network).

Evaluation (5 folds by patient, same split for every model; 15 % of the training
patients are validation patients used ONLY to pick the alarm threshold):
  * window level: AUC, PR-AUC
  * event level: a seizure is detected if an alarm fires between its onset and 1 min
    after its end; false alarms per 24 h of non-seizure recording; detection latency.
    Threshold chosen on validation patients for a false-alarm budget (per day).

Usage: python -m epiprot.gbm.detect --data-dir epiprot_results/gbm/sz_ps \
           --out-dir epiprot_results/gbm/detect --features direct change both \
           --models lgbm logreg rf mlp
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .context import causal_mean

PRE, POST, AFTER_END = 1, 10, 2   # windows
FA_BUDGETS = (0.5, 1.0, 2.0, 5.0)  # false alarms per 24 h
WIN_H = 30.0 / 3600.0
LAST_FLAGS: list = []


def prev_mean(F, w):
    c = causal_mean(F, w)
    return np.vstack([F[:1], c[:-1]])


def make_features(F, kind):
    med = np.nanmedian(F, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    F = np.where(np.isfinite(F), F, med).astype(np.float32)
    if kind == "direct":
        return F
    q75, q25 = np.percentile(F, [75, 25], axis=0)
    iqr = np.where(q75 - q25 > 1e-6, q75 - q25, 1.0)
    d5 = (F - prev_mean(F, 10)) / iqr
    d60 = (F - prev_mean(F, 120)) / iqr
    d1 = (F - np.vstack([F[:1], F[:-1]])) / iqr
    ch = np.hstack([d5, d60, d1]).astype(np.float32)
    return ch if kind == "change" else np.hstack([F, ch])


def labels(n, seizures):
    y = np.zeros(n, np.int8)
    for on, end in seizures:
        y[max(0, on - PRE):min(n, end + POST)] = -1
    for on, end in seizures:
        y[on:end] = 1
    return y


def load(data_dir):
    out = {}
    for f in sorted(data_dir.glob("sub-*.npz")):
        z = np.load(f)
        sz = [tuple(map(int, s)) for s in z["seizures"]]
        out[f.stem] = {"F": z["F"].astype(np.float32), "seizures": sz,
                       "y": labels(len(z["F"]), sz)}
    return out


def model_factory(name, threads):
    if name == "lgbm":
        return None  # trained with early stopping below
    if name == "logreg":
        return make_pipeline(StandardScaler(), LogisticRegression(
            C=0.1, class_weight="balanced", max_iter=500))
    if name == "rf":
        return RandomForestClassifier(n_estimators=200, min_samples_leaf=10, max_features="sqrt",
                                      class_weight="balanced_subsample", n_jobs=threads,
                                      random_state=0)
    if name == "mlp":
        return make_pipeline(StandardScaler(), MLPClassifier(
            hidden_layer_sizes=(128, 64), alpha=1e-3, batch_size=512, learning_rate_init=1e-3,
            max_iter=40, early_stopping=True, n_iter_no_change=5, random_state=0))
    raise ValueError(name)


def train_set(data, X, subs, neg_per, rng, oversample=1):
    Xs, ys = [], []
    for s in subs:
        y = data[s]["y"]
        pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
        if len(neg) > neg_per:
            neg = rng.choice(neg, neg_per, replace=False)
        idx = np.r_[np.repeat(pos, oversample), neg]
        Xs.append(X[s][idx])
        ys.append(y[idx])
    return np.vstack(Xs), np.concatenate(ys).astype(np.int32)


def fit_predict(name, data, X, fit_subs, val_subs, pred_subs, rng, neg_per, threads):
    if name == "lgbm":
        Xt, yt = train_set(data, X, fit_subs, neg_per, rng)
        Xv, yv = train_set(data, X, val_subs, 10 ** 9, rng)
        pos = yt.sum()
        params = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 31,
                  "min_child_samples": 50, "feature_fraction": 0.7, "bagging_fraction": 0.8,
                  "bagging_freq": 1, "lambda_l2": 1.0, "metric": "average_precision",
                  "scale_pos_weight": (len(yt) - pos) / pos, "verbose": -1, "seed": 0,
                  "num_threads": threads}
        b = lgb.train(params, lgb.Dataset(Xt, yt), 2000, valid_sets=[lgb.Dataset(Xv, yv)],
                      callbacks=[lgb.early_stopping(100, verbose=False)])
        return {s: b.predict(X[s], num_iteration=b.best_iteration) for s in pred_subs}
    # MLP has no class weights -> oversample the seizure windows instead
    Xt, yt = train_set(data, X, fit_subs, neg_per, rng, oversample=10 if name == "mlp" else 1)
    m = model_factory(name, threads)
    m.fit(Xt, yt)
    return {s: m.predict_proba(X[s])[:, 1].astype(np.float32) for s in pred_subs}


def smooth(p, k):
    if k <= 1:
        return p
    return causal_mean(p[:, None].astype(np.float32), k)[:, 0]


def score_events(p, y, seizures, thr, k, refractory=10):
    s = smooth(p, k)
    above = np.flatnonzero(s >= thr)
    alarms, nxt = [], -1
    for i in above:
        if i >= nxt:
            alarms.append(i)
            nxt = i + refractory
    alarms = np.asarray(alarms, np.int64)
    hit, lat = 0, []
    flags = []
    for on, end in seizures:
        a = alarms[(alarms >= on) & (alarms < end + AFTER_END)]
        flags.append(bool(len(a)))
        if len(a):
            hit += 1
            lat.append((a[0] - on) * 30.0)
    LAST_FLAGS[:] = flags
    fa = int((y[alarms] == 0).sum()) if len(alarms) else 0
    return hit, len(seizures), fa, float((y == 0).sum() * WIN_H), lat


def evaluate(preds, data, subs, thr, k):
    hit = n = fa = 0
    hours = 0.0
    lat = []
    for s in subs:
        h, ns, f, hr, l = score_events(preds[s], data[s]["y"], data[s]["seizures"], thr, k)
        hit, n, fa, hours, lat = hit + h, n + ns, fa + f, hours + hr, lat + l
    return {"detected": hit, "seizures": n, "sensitivity": hit / max(1, n),
            "false_alarms": fa, "hours": hours, "fa_per_day": fa / hours * 24,
            "median_latency_s": float(np.median(lat)) if lat else None}


def pick(preds, data, subs, budget):
    allp = np.concatenate([preds[s] for s in subs])
    thrs = np.unique(np.quantile(allp, 1 - np.logspace(-1, -5, 60)))
    best = None
    for k in (1, 2, 3):
        for t in thrs:
            r = evaluate(preds, data, subs, t, k)
            if r["fa_per_day"] <= budget and (best is None or r["sensitivity"] > best[2]):
                best = (t, k, r["sensitivity"])
    return (best[0], best[1]) if best else (float(thrs[-1]), 3)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--features", nargs="+", default=["direct", "change", "both"])
    ap.add_argument("--models", nargs="+", default=["lgbm", "logreg", "rf", "mlp"])
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--neg-per-patient", type=int, default=2000)
    ap.add_argument("--threads", type=int, default=10)
    ap.add_argument("--raw-dir", type=Path, default=None, help="for per-seizure-type results")
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)  # noqa: E731
    data = load(a.data_dir)
    subs = sorted(data)
    order = list(subs)
    np.random.default_rng(42).shuffle(order)
    folds = [order[i::a.folds] for i in range(a.folds)]
    nsz = sum(len(d["seizures"]) for d in data.values())
    types = {}
    if a.raw_dir is not None:
        for s in subs:
            types[s] = seizure_types(a.raw_dir, s, len(data[s]["y"]))
            assert len(types[s]) == len(data[s]["seizures"]), s
    log(f"{len(subs)} patients, {nsz} seizures, "
        f"{sum(int((d['y'] == 1).sum()) for d in data.values())} seizure windows")

    results = {}
    for kind in a.features:
        X = {s: make_features(d["F"], kind) for s, d in data.items()}
        log(f"feature set '{kind}': {next(iter(X.values())).shape[1]} features")
        for name in a.models:
            oof, fold_ops = {}, []
            for fi, test in enumerate(folds):
                rng = np.random.default_rng(100 + fi)
                tr = [s for s in subs if s not in set(test)]
                rng.shuffle(tr)
                nv = max(3, round(0.15 * len(tr)))
                val, fit = tr[:nv], tr[nv:]
                p = fit_predict(name, data, X, fit, val, val + test, rng, a.neg_per_patient,
                                a.threads)
                ops = {b: pick(p, data, val, b) for b in FA_BUDGETS}
                fold_ops.append((test, ops))
                for s in test:
                    oof[s] = p[s]
            y = np.concatenate([data[s]["y"] for s in subs])
            pp = np.concatenate([oof[s] for s in subs])
            m = y >= 0
            res = {"auc": float(roc_auc_score(y[m], pp[m])),
                   "pr_auc": float(average_precision_score(y[m], pp[m])), "event": {}}
            for b in FA_BUDGETS:
                agg = {"detected": 0, "seizures": 0, "false_alarms": 0, "hours": 0.0}
                lats = []
                for test, ops in fold_ops:
                    r = evaluate(oof, data, test, *ops[b])
                    for kk in agg:
                        agg[kk] += r[kk]
                    if r["median_latency_s"] is not None:
                        lats.append(r["median_latency_s"])
                agg["sensitivity"] = agg["detected"] / agg["seizures"]
                agg["fa_per_day"] = agg["false_alarms"] / agg["hours"] * 24
                agg["median_latency_s"] = float(np.median(lats)) if lats else None
                if a.raw_dir is not None:  # sensitivity per seizure type
                    by = {}
                    for test, ops in fold_ops:
                        for s in test:
                            score_events(oof[s], data[s]["y"], data[s]["seizures"], *ops[b])
                            for t, h in zip(types[s], LAST_FLAGS):
                                g = by.setdefault(type_group(t), [0, 0])
                                g[0] += h
                                g[1] += 1
                    agg["by_type"] = {g: {"detected": v[0], "seizures": v[1],
                                          "sensitivity": v[0] / v[1]} for g, v in by.items()}
                res["event"][str(b)] = agg
            results[f"{kind}/{name}"] = res
            e1 = res["event"]["1.0"]
            e5 = res["event"]["5.0"]
            log(f"{kind:6s} {name:6s} AUC={res['auc']:.3f} PR-AUC={res['pr_auc']:.3f} | "
                f"FA<=1/day: sens={e1['sensitivity']:.1%} FA/day={e1['fa_per_day']:.2f} | "
                f"FA<=5/day: sens={e5['sensitivity']:.1%} FA/day={e5['fa_per_day']:.2f} "
                f"latency={e5['median_latency_s']}s")
            for g, v in sorted(e1.get("by_type", {}).items()):
                log(f"    FA<=1/day  {g:45s} {v['detected']:3d}/{v['seizures']:3d} "
                    f"= {v['sensitivity']:.0%}   (FA<=5/day: "
                    f"{e5['by_type'][g]['sensitivity']:.0%})")
            np.savez(a.out_dir / f"oof_{kind}_{name}.npz", **oof)
            (a.out_dir / "results.json").write_text(json.dumps(results, indent=2))



def seizure_types(raw_dir, sub, n):
    """Seizure type per seizure, in the same order as timeline.build_timeline."""
    import csv
    from .timeline import WINDOW_S, _run_num
    tsvs = sorted((raw_dir / sub / "ses-01" / "eeg").glob("*_events.tsv"), key=_run_num)
    out, pos = [], 0
    for t in tsvs:
        with open(t, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        nw = int((float(rows[0]["recordingDuration"]) if rows else 0.0) // WINDOW_S)
        for r in rows:
            if r["eventType"].lower().startswith("sz"):
                on = pos + int(float(r["onset"]) // WINDOW_S)
                end = pos + int(np.ceil((float(r["onset"]) + float(r["duration"])) / WINDOW_S))
                if on < pos + nw:
                    out.append(((on, min(max(end, on + 1), pos + nw)), r["eventType"]))
        pos += nw
    out.sort(key=lambda x: x[0])
    return [t for _, t in out]


def type_group(t):
    t = t.lower()
    if "f2b" in t or "gen" in t:
        return "tonic-clonic (bilateral)"
    if "hyperkinetic" in t:
        return "focal hyperkinetic"
    if "_m" in t and "_nm" not in t and "_um" not in t:
        return "focal motor (other)"
    if "_ia" in t or "_ua" in t:
        return "focal impaired/unknown awareness, non-motor"
    return "focal aware, non-motor"


if __name__ == "__main__":
    main()

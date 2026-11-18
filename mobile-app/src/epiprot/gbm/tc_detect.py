"""Fast TONIC-CLONIC seizure detection with all wearable sensors (5 s windows).

Positives : windows inside a tonic-clonic seizure (focal-to-bilateral / generalised);
            the first 30 s get 3x training weight (we want EARLY alarms).
Ignored   : 1 window before and 5 min after every seizure; all other seizure types.
Negatives : everything else (false alarms are counted here).

Features (causal): the 5 s window itself, its difference to the mean of the previous
1 min and previous 10 min, and the mean / max of the last 15 s. NaN (missing sensor)
is handled natively by LightGBM.

Sensor sets compared: eeg+ecg, eeg+ecg+emg, eeg+ecg+mov, all.

Evaluation: 5 folds by patient (seed 42, same as the other experiments). Inside each
training fold, 3-fold inner cross-validation gives out-of-fold scores for every
training patient; the alarm rule (threshold, smoothing k) is chosen there:
maximum tonic-clonic sensitivity with false alarms/day <= budget. Then applied
unchanged to the unseen test patients.
  * detected  : alarm between onset and 30 s after the end
  * latency   : alarm time (end of its 5 s window) - exact annotated onset
  * false alarm: alarm in a negative window; 5 min refractory after each alarm

Usage: python -m epiprot.gbm.tc_detect --data-dir epiprot_results/gbm/tc5s \
           --out-dir epiprot_results/gbm/tc_detect
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np

from .context import causal_mean

W = 5.0
PRE, POST, AFTER_END, EARLY = 1, 60, 6, 6     # windows
REFRACTORY = 60
TC_W = 5.0
BUDGETS = (0.25, 0.5, 1.0, 2.0)                # false alarms per day
GROUPS = {"eeg+ecg": r"^(eeg|ecg)", "eeg+ecg+emg": r"^(eeg|ecg|emg)",
          "eeg+ecg+mov": r"^(eeg|ecg|head|body)", "all": r".",
          "ecg+mov": r"^(ecg|head|body)", "mov": r"^(head|body)", "ecg": r"^ecg",
          # EpiProt hardware: no wrist movement (only the headband's), and / or movement only as change
          # relative to the person's own recent past + rhythmicity (independent of sensor units)
          "eeg+ecg+head": r"^(eeg|ecg|head)",
          "eeg+ecg+head_rel": r"^(eeg|ecg)|^head_(acc|gyr)_rhythm|^head_.*@(d1m|d10m|mean60s-d10m)$",
          "eeg+ecg+mov_rel": r"^(eeg|ecg)|^(head|body)_(acc|gyr)_rhythm|^(head|body)_.*@(d1m|d10m|mean60s-d10m)$"}
PARAMS = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 31,
          "min_child_samples": 30, "feature_fraction": 0.7, "bagging_fraction": 0.8,
          "bagging_freq": 1, "lambda_l2": 1.0, "verbose": -1, "seed": 0}


def is_tc(t: str) -> bool:
    t = t.lower()
    return "f2b" in t or "gen" in t


def prev_mean(F, w):
    c = causal_mean(np.nan_to_num(F), w)
    return np.vstack([F[:1], c[:-1]])


def causal_max(F, w):
    out = F.copy()
    for s in range(1, w):
        out[s:] = np.fmax(out[s:], F[:-s])
    return out


def expand(F, names):
    med = np.nanmedian(F, axis=0)
    Ff = np.where(np.isnan(F), np.where(np.isfinite(med), med, 0), F).astype(np.float32)
    parts = [F, Ff - prev_mean(Ff, 12), Ff - prev_mean(Ff, 120),
             causal_mean(Ff, 3), causal_max(Ff, 3), causal_mean(Ff, 6), causal_max(Ff, 6),
             causal_mean(Ff, 12) - prev_mean(Ff, 120)]
    cols = (names + [f"{n}@d1m" for n in names] + [f"{n}@d10m" for n in names]
            + [f"{n}@mean15s" for n in names] + [f"{n}@max15s" for n in names]
            + [f"{n}@mean30s" for n in names] + [f"{n}@max30s" for n in names]
            + [f"{n}@mean60s-d10m" for n in names])
    return np.hstack(parts).astype(np.float16), cols


def load(data_dir):
    data, cols = {}, None
    for f in sorted(data_dir.glob("sub-*.npz")):
        if ".tmp" in f.name:
            continue
        z = np.load(f)
        names = [str(x) for x in z["names"]]
        X, cols = expand(z["F"], names)
        n = len(X)
        y = np.zeros(n, np.int8)
        sz = [tuple(map(int, s)) for s in z["seizures"]]
        types = [str(t) for t in z["sz_type"]]
        for on, end in sz:
            y[max(0, on - PRE):min(n, end + POST)] = -1
        tc = []
        ytr = y.copy()                      # training target: ALL seizures positive
        wpos = np.ones(n, np.float32)       # tonic-clonic windows weigh more
        for (on, end), t, o_s, d_s in zip(sz, types, z["sz_onset_s"], z["sz_dur_s"]):
            ytr[on:end] = 1
            if is_tc(t):
                y[on:end] = 1
                wpos[on:end] = TC_W
                wpos[on:min(end, on + EARLY)] = TC_W * 2
                tc.append({"on": on, "end": end, "onset_s": float(o_s), "dur_s": float(d_s)})
        data[f.stem] = {"X": X, "y": y, "ytr": ytr, "w": wpos, "tc": tc}
    return data, cols


OPTS = {"hard_neg": 0, "drop_ecg": 0.0, "ecg_local": np.array([], int)}


def _fit(X, y, w, rounds, threads):
    npos = max(1, int(y.sum()))
    p = PARAMS | {"scale_pos_weight": (len(y) - npos) / npos, "num_threads": threads}
    return lgb.train(p, lgb.Dataset(X, y, weight=w), rounds)


def _assemble(data, subs, colidx, picks):
    Xs, ys, ws = [], [], []
    for s in subs:
        idx = picks[s]
        Xs.append(data[s]["X"][idx][:, colidx].astype(np.float32))
        ys.append(data[s]["ytr"][idx])
        ws.append(data[s]["w"][idx])
    return np.vstack(Xs), np.concatenate(ys), np.concatenate(ws)


def train(data, subs, colidx, rng, neg_per=5000, rounds=400, threads=10):
    picks = {}
    for s in subs:
        d = data[s]
        pos, neg = np.flatnonzero(d["ytr"] == 1), np.flatnonzero(d["ytr"] == 0)
        if len(neg) > neg_per:
            neg = rng.choice(neg, neg_per, replace=False)
        picks[s] = np.r_[pos, neg]
    X, y, w = _assemble(data, subs, colidx, picks)
    if OPTS["hard_neg"]:
        # hard-negative mining: add the normal windows the first model finds most
        # seizure-like (training patients only)
        b0 = _fit(X, y, w, rounds // 2, threads)
        for s in subs:
            d = data[s]
            neg = np.flatnonzero(d["ytr"] == 0)
            if not len(neg):
                continue
            sc = np.concatenate([b0.predict(d["X"][neg[i:i + 50000]][:, colidx].astype(np.float32))
                                 for i in range(0, len(neg), 50000)])
            hard = neg[np.argsort(sc)[-OPTS["hard_neg"]:]]
            picks[s] = np.unique(np.r_[picks[s], hard])
        X, y, w = _assemble(data, subs, colidx, picks)
    if OPTS["drop_ecg"] > 0 and len(OPTS["ecg_local"]):
        # sensor-dropout augmentation: copies of windows with the ECG missing
        m = (y == 1) | (rng.random(len(y)) < OPTS["drop_ecg"])
        Xa = X[m].copy()
        Xa[:, OPTS["ecg_local"]] = np.nan
        X, y, w = np.vstack([X, Xa]), np.r_[y, y[m]], np.r_[w, w[m]]
    return _fit(X, y, w, rounds, threads)


def predict(b, data, subs, colidx):
    out = {}
    for s in subs:
        X = data[s]["X"]
        out[s] = np.concatenate([b.predict(X[i:i + 50000][:, colidx].astype(np.float32))
                                 for i in range(0, len(X), 50000)]).astype(np.float32)
    return out


def alarms(p, thr, k):
    s = p if k <= 1 else causal_mean(p[:, None], k)[:, 0]
    above = np.flatnonzero(s >= thr)
    out, nxt = [], -1
    for i in above:
        if i >= nxt:
            out.append(i)
            nxt = i + REFRACTORY
    return np.asarray(out, np.int64)


def evaluate(pred, data, subs, thr, k, detail=False):
    hit = n = fa = 0
    hours = 0.0
    rows = []
    for s in subs:
        d = data[s]
        a = alarms(pred[s], thr, k)
        fa += int((d["y"][a] == 0).sum()) if len(a) else 0
        hours += float((d["y"] == 0).sum() * W / 3600)
        for e in d["tc"]:
            n += 1
            aa = a[(a >= e["on"]) & (a < e["end"] + AFTER_END)]
            ok = bool(len(aa))
            hit += ok
            if detail:
                lat = (aa[0] + 1) * W - e["onset_s"] if ok else None
                rows.append({"sub": s, "detected": ok, "latency_s": lat, "dur_s": e["dur_s"]})
    r = {"detected": hit, "seizures": n, "sensitivity": hit / max(1, n), "false_alarms": fa,
         "hours": hours, "fa_per_day": fa / max(hours, 1e-9) * 24}
    if detail:
        r["per_seizure"] = rows
    return r


def choose(pred, data, subs, budget):
    allp = np.concatenate([pred[s][data[s]["y"] == 0] for s in subs])
    thrs = np.unique(np.quantile(allp, 1 - np.logspace(-2, -6.5, 70)))
    best = None
    for k in (1, 2, 3):
        for t in thrs:
            r = evaluate(pred, data, subs, t, k)
            if r["fa_per_day"] <= budget:
                key = (r["sensitivity"], -k, -t)
                if best is None or key > best[0]:
                    best = (key, t, k)
                break  # higher thresholds only lower sensitivity for this k
    return (best[1], best[2]) if best else (float(thrs[-1]), 3)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--groups", nargs="+", default=list(GROUPS))
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--inner", type=int, default=3)
    ap.add_argument("--threads", type=int, default=10)
    ap.add_argument("--hard-neg", type=int, default=0,
                    help="add the N most seizure-like normal windows per training patient")
    ap.add_argument("--drop-ecg", type=float, default=0.0,
                    help="augment: copies of positives (+ this share of negatives) without ECG")
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)  # noqa: E731
    data, cols = load(a.data_dir)
    subs = sorted(data)
    order = list(subs)
    np.random.default_rng(42).shuffle(order)
    folds = [order[i::a.folds] for i in range(a.folds)]
    ntc = sum(len(d["tc"]) for d in data.values())
    log(f"{len(subs)} patients, {ntc} tonic-clonic seizures in "
        f"{sum(bool(d['tc']) for d in data.values())} patients, {len(cols)} features")

    results = {}
    for g in a.groups:
        colidx = np.array([i for i, c in enumerate(cols) if re.search(GROUPS[g], c)])
        OPTS["hard_neg"], OPTS["drop_ecg"] = a.hard_neg, a.drop_ecg
        OPTS["ecg_local"] = np.array([j for j, i in enumerate(colidx)
                                      if cols[i].startswith("ecg")], int)
        oof, ops_by_fold = {}, []
        for fi, test in enumerate(folds):
            rng = np.random.default_rng(100 + fi)
            tr = [s for s in subs if s not in set(test)]
            inner = [tr[i::a.inner] for i in range(a.inner)]
            ip = {}
            for hold in inner:
                b = train(data, [s for s in tr if s not in set(hold)], colidx, rng,
                          threads=a.threads)
                ip |= predict(b, data, hold, colidx)
            ops = {bud: choose(ip, data, tr, bud) for bud in BUDGETS}
            b = train(data, tr, colidx, rng, threads=a.threads)
            oof |= predict(b, data, test, colidx)
            ops_by_fold.append((test, ops))
            log(f"  {g} fold {fi + 1}/{a.folds} done")
        res = {}
        for bud in BUDGETS:
            agg = {"detected": 0, "seizures": 0, "false_alarms": 0, "hours": 0.0}
            rows = []
            for test, ops in ops_by_fold:
                r = evaluate(oof, data, test, *ops[bud], detail=True)
                for kk in agg:
                    agg[kk] += r[kk]
                rows += r["per_seizure"]
            lat = np.array([x["latency_s"] for x in rows if x["detected"]])
            agg |= {"sensitivity": agg["detected"] / agg["seizures"],
                    "fa_per_day": agg["false_alarms"] / agg["hours"] * 24,
                    "latency_median_s": float(np.median(lat)) if len(lat) else None,
                    "latency_iqr_s": [float(np.percentile(lat, 25)), float(np.percentile(lat, 75))]
                    if len(lat) else None,
                    "alarm_within_15s": int((lat <= 15).sum()),
                    "alarm_within_30s": int((lat <= 30).sum()),
                    "alarm_before_end": int(sum(x["latency_s"] < x["dur_s"]
                                                for x in rows if x["detected"])),
                    "per_seizure": rows}
            res[str(bud)] = agg
            log(f"{g:12s} FA budget {bud}/day: TC detected {agg['detected']}/{agg['seizures']} "
                f"({agg['sensitivity']:.0%}), FA/day {agg['fa_per_day']:.2f}, latency median "
                f"{agg['latency_median_s']}s IQR {agg['latency_iqr_s']}, <=15s "
                f"{agg['alarm_within_15s']}, <=30s {agg['alarm_within_30s']}, "
                f"before end {agg['alarm_before_end']}")
        results[g] = res
        np.savez(a.out_dir / f"oof_{g}.npz", **oof)
        (a.out_dir / "results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

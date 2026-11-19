"""Export the final detector for the Android phone app.

Trains the two 5 s models on ALL 125 patients with the same settings as the evaluated
system (tc_detect3: hard negatives 1000, ECG dropout 0.1):
  A  = EEG + heart + movement (280 features)
  A' = EEG + heart (120 features), used while no movement data arrive
and writes, into the Android app's assets:
  model_a.txt, model_a_fb.txt   LightGBM text models
  detector.json                 feature names, alarm rule (threshold, smoothing k, refractory),
                                score scaling tables (from the out-of-fold scores), calibration
Alarm rule: "5 s only" with fallback, threshold chosen on the out-of-fold scores of all patients
for a 0.25 false alarms/day budget (cross-validated result of this rule: 52/55, 0.24/day).

and the 30 s model B on the features the phone computes itself (tc30s_features: headband EEG
spectrum + watch-like 1 Hz heart rate; no chest ECG). Final rule "max" of the scaled 5 s and
30 s scores, threshold chosen on the out-of-fold scores of all patients.

Heart-rate backup: wherever the watch sends no heart rate, the 5 s model A_nohr (EEG + headband
movement) and the 30 s model B_nohr (EEG spectrum only) take over; they never saw a heart rate, so
a heart rate that drops out (watch off, PPG lost during a convulsion) cannot fool them
(gbm/hr_robustness.py: 54/55 with the heart rate lost in every seizure, 53/55 without any).

With --fixtures it also writes test data for the Kotlin unit tests (parity with Python):
raw 5 s windows + their features, a run of base features + the expanded features,
model predictions, and an alarm-rule example.

Usage (repository root):
  python -m epiprot.app.export_model --raw-dir /raw \
      --assets mobile-app/android/app/src/main/assets/model \
      --fixtures mobile-app/android/app/src/test/resources/fixtures
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

import lightgbm as lgb

from epiprot.gbm import detect as D
from epiprot.gbm import tc_detect as T
from epiprot.gbm import tc_features as TF
from epiprot.gbm.tc_ensemble import load_labels, map30to5, qscale, run_lengths
from epiprot.gbm.hr_robustness import STUCK_WINDOWS, stuck_mask

B_SUFFIXES = ["", "@d5m", "@d60m", "@d1"]
BUDGET = 0.25
LOW_Q = 0.99           # score level used to estimate seizure start / end (as in simulate.py)
FIX_SUB = "sub-115"


def quantile_table(ref: np.ndarray) -> dict:
    """Scaling table: dense in the far tail, where the alarm threshold sits."""
    q = np.unique(np.r_[np.linspace(0, 0.99, 100), 1 - np.logspace(-2, -7, 1200), 1.0])
    return {"q": [float(x) for x in q], "v": [float(x) for x in np.quantile(ref, q)]}


def table_scale(p, t):
    return np.interp(p, t["v"], t["q"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, default=None)
    ap.add_argument("--data-dir", type=Path, default=Path("epiprot_results/gbm/tc5s"))
    ap.add_argument("--oof5", type=Path, default=Path("epiprot_results/gbm/tc_detect3/oof_eeg+ecg+mov.npz"))
    ap.add_argument("--fallback", type=Path, default=Path("epiprot_results/gbm/tc_detect3/oof_eeg+ecg.npz"))
    ap.add_argument("--group5", default="eeg+ecg+mov", help="feature group of model A (tc_detect.GROUPS)")
    ap.add_argument("--mov-cols", nargs="+", default=["head_acc_std", "body_acc_std"],
                    help="backup model A' when all of these are missing")
    ap.add_argument("--data30", type=Path, default=Path("epiprot_results/gbm/sz30_hw"))
    ap.add_argument("--oof30", type=Path, default=Path("epiprot_results/gbm/detect_hw/oof_both_lgbm.npz"))
    ap.add_argument("--nohr5", type=Path, default=None, help="OOF of the 5 s model without heart rate (eeg+head)")
    ap.add_argument("--nohr30", type=Path, default=None, help="OOF of the 30 s model without heart rate")
    ap.add_argument("--stuck-hr", type=float, default=0.0,
                    help="also use the no-heart-rate models while the heart rate varied < this many bpm over 1 min")
    ap.add_argument("--assets", type=Path, required=True)
    ap.add_argument("--fixtures", type=Path, default=None)
    ap.add_argument("--threads", type=int, default=10)
    a = ap.parse_args(argv)
    a.assets.mkdir(parents=True, exist_ok=True)

    # ---- alarm rule from the out-of-fold scores (all patients) ----
    labels = load_labels(a.data_dir)
    subs = sorted(labels)
    z5, zf = np.load(a.oof5), np.load(a.fallback)
    nomov = {}
    for s in subs:
        with np.load(a.data_dir / f"{s}.npz") as zz:
            nm = [str(x) for x in zz["names"]]
            nomov[s] = np.all([np.isnan(zz["F"][:, nm.index(c)]) for c in a.mov_cols], axis=0)
    r5 = np.sort(np.concatenate([z5[s][labels[s]["y"] == 0] for s in subs]).astype(np.float64))
    rf = np.sort(np.concatenate([zf[s][labels[s]["y"] == 0] for s in subs]).astype(np.float64))
    z30 = np.load(a.oof30)
    p30 = {}
    for s in subs:
        q = map30to5(z30[s].astype(np.float32), run_lengths(a.raw_dir, s))
        n = len(z5[s])
        p30[s] = np.pad(q, (0, max(0, n - len(q))), mode="edge")[:n] if len(q) else np.zeros(n, np.float32)
    r30 = np.sort(np.concatenate([p30[s][labels[s]["y"] == 0] for s in subs]).astype(np.float64))
    tab = {"a": quantile_table(r5), "a_fb": quantile_table(rf), "b": quantile_table(r30)}
    nohr = a.nohr5 is not None
    hrmiss = {}
    if nohr:
        zh = np.load(a.nohr5)
        zh30 = np.load(a.nohr30)
        h30 = {}
        for s in subs:
            q = map30to5(zh30[s].astype(np.float32), run_lengths(a.raw_dir, s))
            n = len(z5[s])
            h30[s] = np.pad(q, (0, max(0, n - len(q))), mode="edge")[:n] if len(q) else np.zeros(n, np.float32)
            with np.load(a.data_dir / f"{s}.npz") as zz:
                nm = [str(x) for x in zz["names"]]
                hr = zz["F"][:, nm.index("ecg_hr")]
                hrmiss[s] = np.isnan(hr) | stuck_mask(hr, a.stuck_hr)
        rh = np.sort(np.concatenate([zh[s][labels[s]["y"] == 0] for s in subs]).astype(np.float64))
        rh30 = np.sort(np.concatenate([h30[s][labels[s]["y"] == 0] for s in subs]).astype(np.float64))
        tab |= {"a_nohr": quantile_table(rh), "b_nohr": quantile_table(rh30)}

    def combine(s, sc5, scfb, sc30, sch5=None, sch30=None):
        a5 = np.where(nomov[s], scfb, sc5)
        if nohr:   # no heart rate in this window -> models that never saw one
            a5 = np.where(hrmiss[s], sch5, a5)
            sc30 = np.where(hrmiss[s], sch30, sc30)
        return np.maximum(a5, sc30).astype(np.float32)

    sc_exact = {s: combine(s, qscale(z5[s], r5), qscale(zf[s], rf), qscale(p30[s], r30),
                           *((qscale(zh[s], rh), qscale(h30[s], rh30)) if nohr else ())) for s in subs}
    sc_tab = {s: combine(s, table_scale(z5[s], tab["a"]), table_scale(zf[s], tab["a_fb"]),
                         table_scale(p30[s], tab["b"]),
                         *((table_scale(zh[s], tab["a_nohr"]), table_scale(h30[s], tab["b_nohr"])) if nohr else ()))
              for s in subs}
    thr, k = T.choose(sc_tab, labels, subs, BUDGET)
    r_tab = T.evaluate(sc_tab, labels, subs, thr, k)
    r_ex = T.evaluate(sc_exact, labels, subs, *T.choose(sc_exact, labels, subs, BUDGET))
    print(f"alarm rule: threshold {thr:.7f}, k={k}; on the OOF scores: {r_tab['detected']}/{r_tab['seizures']}, "
          f"{r_tab['fa_per_day']:.2f} FA/day (exact scaling: {r_ex['detected']}/{r_ex['seizures']}, "
          f"{r_ex['fa_per_day']:.2f}/day)", flush=True)

    # ---- final models on all patients ----
    data, cols = T.load(a.data_dir)
    base = cols[: len(cols) // 8]
    rng = np.random.default_rng(2026)
    feats, boosters = {}, {}
    groups5 = {"a": a.group5, "a_fb": "eeg+ecg"} | ({"a_nohr": "eeg+head"} if nohr else {})
    for key, g in groups5.items():
        colidx = np.array([i for i, c in enumerate(cols) if re.search(T.GROUPS[g], c)])
        T.OPTS.update(hard_neg=1000, drop_ecg=0.1,
                      ecg_local=np.array([j for j, i in enumerate(colidx) if cols[i].startswith("ecg")], int))
        b = T.train(data, subs, colidx, rng, threads=a.threads)
        (a.assets / f"model_{key}.txt").write_text(b.model_to_string(), encoding="utf-8")
        feats[key] = [cols[i] for i in colidx]
        boosters[key] = (b, colidx)
        print(f"model {key}: {len(colidx)} features, {b.num_trees()} trees", flush=True)

    # ---- final 30 s model B (same settings as detect.py; 15 % of the patients for early stopping) ----
    d30 = D.load(a.data30)
    with np.load(next(a.data30.glob("sub-*.npz"))) as zz:
        base30 = [str(x) for x in zz["names"]]
    X30 = {s_: D.make_features(d["F"], "both") for s_, d in d30.items()}

    def train_b(keep, fname):
        """keep: base-feature indices; X30 columns are [base, @d5m, @d60m, @d1] blocks"""
        nb = len(base30)
        cols_ = np.concatenate([np.asarray(keep) + j * nb for j in range(4)])
        Xk = {s_: x[:, cols_] for s_, x in X30.items()}
        rng30 = np.random.default_rng(2027)
        s30 = sorted(d30)
        rng30.shuffle(s30)
        nv = max(3, round(0.15 * len(s30)))
        Xt, yt = D.train_set(d30, Xk, s30[nv:], 2000, rng30)
        Xv, yv = D.train_set(d30, Xk, s30[:nv], 10 ** 9, rng30)
        del Xk
        pos = yt.sum()
        pb = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 31, "min_child_samples": 50,
              "feature_fraction": 0.7, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
              "metric": "average_precision", "scale_pos_weight": (len(yt) - pos) / pos, "verbose": -1,
              "seed": 0, "num_threads": a.threads}
        bb_ = lgb.train(pb, lgb.Dataset(Xt, yt), 2000, valid_sets=[lgb.Dataset(Xv, yv)],
                        callbacks=[lgb.early_stopping(100, verbose=False)])
        (a.assets / fname).write_text(bb_.model_to_string(num_iteration=bb_.best_iteration), encoding="utf-8")
        f_ = [base30[i] + suf for suf in B_SUFFIXES for i in keep]
        print(f"{fname}: {len(f_)} features, {bb_.best_iteration} trees", flush=True)
        return bb_, f_, cols_

    bb, feats_b, _ = train_b(list(range(len(base30))), "model_b.txt")
    if nohr:
        keep_h = [i for i, n_ in enumerate(base30) if not n_.startswith("hr_")]
        bbh, feats_bh, cols_bh = train_b(keep_h, "model_b_nohr.txt")

    base_used = [n for n in base if any(re.search(T.GROUPS[g], n + suf) for g in groups5.values()
                                        for suf in ("", "@d1m"))]
    det = {
        "version": 1,
        "window_s": T.W,
        "base_features": base_used,
        "models": {"a": {"file": "model_a.txt", "features": feats["a"], "scale": tab["a"]},
                   "a_fb": {"file": "model_a_fb.txt", "features": feats["a_fb"], "scale": tab["a_fb"]}},
        "model_b": {"file": "model_b.txt", "base_features": base30, "features": feats_b, "scale": tab["b"],
                    "window_s": 30.0, "rule": "max"},
        "fallback_when_missing": list(a.mov_cols),
        **({"heart_rate_backup": {
            "when_missing": "ecg_hr",
            "stuck_bpm": a.stuck_hr, "stuck_windows": STUCK_WINDOWS,
            "a": {"file": "model_a_nohr.txt", "features": feats["a_nohr"], "scale": tab["a_nohr"]},
            "b": {"file": "model_b_nohr.txt", "features": feats_bh, "scale": tab["b_nohr"]}}} if nohr else {}),
        "threshold": float(thr), "smooth_k": int(k), "refractory_windows": T.REFRACTORY,
        "low_level": LOW_Q, "end_after_low_windows": 6,
        "budget_fa_per_day": BUDGET,
        "oof_result": {"detected": r_tab["detected"], "seizures": r_tab["seizures"],
                       "fa_per_day": round(r_tab["fa_per_day"], 3)},
    }
    (a.assets / "detector.json").write_text(json.dumps(det), encoding="utf-8")

    if a.fixtures is None:
        return
    a.fixtures.mkdir(parents=True, exist_ok=True)

    # ---- fixture 1: expansion + model predictions on a real run of windows ----
    z = np.load(a.data_dir / f"{FIX_SUB}.npz")
    names = [str(x) for x in z["names"]]
    Fall = z["F"]
    on = int(z["seizures"][0][0]) if len(z["seizures"]) else 1000
    lo = max(0, on - 250)
    F = Fall[lo:lo + 400]
    keep = [names.index(n) for n in base_used]
    Fb = F[:, keep]
    med = np.nanmedian(Fall[:, keep], axis=0)
    med = np.where(np.isfinite(med), med, 0).astype(np.float32)
    # expand() with a given median (the phone keeps a running median instead of the whole recording's)
    Ff = np.where(np.isnan(Fb), med, Fb).astype(np.float32)
    parts = [Fb, Ff - T.prev_mean(Ff, 12), Ff - T.prev_mean(Ff, 120),
             T.causal_mean(Ff, 3), T.causal_max(Ff, 3), T.causal_mean(Ff, 6), T.causal_max(Ff, 6),
             T.causal_mean(Ff, 12) - T.prev_mean(Ff, 120)]
    X = np.hstack(parts).astype(np.float32)
    xcols = (base_used + [f"{n}@d1m" for n in base_used] + [f"{n}@d10m" for n in base_used]
             + [f"{n}@mean15s" for n in base_used] + [f"{n}@max15s" for n in base_used]
             + [f"{n}@mean30s" for n in base_used] + [f"{n}@max30s" for n in base_used]
             + [f"{n}@mean60s-d10m" for n in base_used])
    pred = {}
    for key, (b, _) in boosters.items():
        idx = [xcols.index(c) for c in feats[key]]
        pred[key] = b.predict(X[:, idx].astype(np.float64)).tolist()
    nan = lambda M: [[None if not np.isfinite(v) else float(v) for v in row] for row in M]  # noqa: E731
    (a.fixtures / "expand.json").write_text(json.dumps({
        "base": base_used, "median": med.tolist(), "F": nan(Fb), "X_cols": xcols, "X": nan(X),
        "pred_a": pred["a"], "pred_a_fb": pred["a_fb"], "pred_a_nohr": pred.get("a_nohr")}), encoding="utf-8")

    # ---- fixture 1b: 30 s expansion ("both", with given median / IQR) + model B ----
    F30 = d30[FIX_SUB]["F"]
    med30 = np.nanmedian(F30, axis=0)
    med30 = np.where(np.isfinite(med30), med30, 0.0).astype(np.float32)
    Ff30 = np.where(np.isfinite(F30), F30, med30).astype(np.float32)
    q75, q25 = np.percentile(Ff30, [75, 25], axis=0)
    iqr30 = np.where(q75 - q25 > 1e-6, q75 - q25, 1.0).astype(np.float32)
    lo30 = max(0, int(d30[FIX_SUB]["seizures"][0][0]) - 150) if d30[FIX_SUB]["seizures"] else 0
    Xb_full = D.make_features(F30, "both")          # whole-recording median / IQR, as in training
    Fs = F30[lo30:lo30 + 200]
    Xs = Xb_full[lo30:lo30 + 200]
    (a.fixtures / "expand30.json").write_text(json.dumps({
        "base": base30, "median": med30.tolist(), "iqr": iqr30.tolist(), "start": lo30,
        "history": nan(F30[max(0, lo30 - 120):lo30]), "F": nan(Fs), "X": nan(Xs),
        "pred_b": bb.predict(Xs.astype(np.float64), num_iteration=bb.best_iteration).tolist(),
        "pred_b_nohr": (bbh.predict(Xs[:, cols_bh].astype(np.float64), num_iteration=bbh.best_iteration).tolist()
                        if nohr else None)}), encoding="utf-8")

    # ---- fixture 2: alarm rule on the scaled OOF score of this patient ----
    s = sc_tab[FIX_SUB]
    al = T.alarms(s, thr, k)
    s, al = s[:40000], al[al < 40000]
    (a.fixtures / "alarms.json").write_text(json.dumps({
        "score": s.tolist(), "threshold": float(thr), "k": int(k), "refractory": T.REFRACTORY,
        "alarms": al.tolist(),
        "scale_check": {"raw": z5[FIX_SUB][:500].astype(float).tolist(),
                        "scaled": table_scale(z5[FIX_SUB][:500], tab["a"]).tolist()}}), encoding="utf-8")

    # ---- fixture 3: raw windows -> base features ----
    if a.raw_dir is None:
        return
    import csv
    bdir = a.raw_dir / FIX_SUB / "ses-01"
    tsv = sorted((bdir / "eeg").glob("*_events.tsv"), key=TF._run_num)[0]
    stem = tsv.name.replace("_events.tsv", "")
    with open(tsv, newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    n = int(float(rows[0]["recordingDuration"]) // T.W)
    xe, fse, _ = TF._read(bdir / "eeg" / f"{stem}_eeg.edf")
    xm, fsm, chm = TF._read(bdir / "mov" / f"{stem}_mov.edf")
    fe, ne = TF.eeg_feats(xe, fse, n)
    fm, nm_ = TF.mov_feats(xm, fsm, chm, n)
    Fr = np.stack(fe + fm, 1)
    pick = [10, 11, 500, 2000, 2001, n - 3]
    for sz in z["seizures"]:
        if sz[0] < n - 2:
            pick += [int(sz[0]), int(sz[0]) + 2]
            break
    me, mm = int(T.W * fse), int(T.W * fsm)
    order = {}
    for dev, tag in (("EEG SD", "head"), ("ECGEMG SD", "body")):
        for kind in ("ACC", "GYR"):
            order[f"{tag}_{kind.lower()}"] = [i for i, c in enumerate(chm) if c.startswith(dev + " " + kind)]
    wins = []
    for i in pick:
        wins.append({
            "index": i,
            "eeg_uv": [(xe[c, i * me:(i + 1) * me] * 1e6).astype(float).tolist() for c in range(2)],
            "mov": {k_: [xm[c, i * mm:(i + 1) * mm].astype(float).tolist() for c in ch] for k_, ch in order.items()},
            "features": {nn: (None if not np.isfinite(Fr[i, j]) else float(Fr[i, j]))
                         for j, nn in enumerate(ne + nm_)},
        })
    (a.fixtures / "windows.json").write_text(json.dumps({"eeg_fs": fse, "mov_fs": fsm, "windows": wins}),
                                             encoding="utf-8")
    print("fixtures written", flush=True)


if __name__ == "__main__":
    main()

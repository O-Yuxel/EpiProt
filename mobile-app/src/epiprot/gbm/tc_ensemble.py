"""Combine the fast 5 s tonic-clonic model with the 30 s all-seizure detector.

Both models' out-of-fold scores come from the same patient folds (seed 42), so every
score is for a patient that model never saw. The 30 s score of window j becomes
available at the end of that window, i.e. it is copied to the 5 s windows that END
within or after it (causal, no look-ahead), run by run.

Scores are put on a common scale (quantile among the negative windows of the TRAINING
patients of each fold), then combined with
  mean : average of the two quantile scores
  max  : the larger one (alarm if either model is very sure)
The alarm rule is chosen on the training patients of each fold (max sensitivity with
FA/day <= budget) and applied unchanged to the test patients.

Usage: python -m epiprot.gbm.tc_ensemble --raw-dir /raw
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np

from . import tc_detect as T

BUD = (0.25, 0.5, 1.0, 2.0)


def run_lengths(raw_dir, sub):
    tsvs = sorted((raw_dir / sub / "ses-01" / "eeg").glob("*_events.tsv"),
                  key=lambda p: int(re.search(r"run-(\d+)", p.name).group(1)))
    out = []
    for t in tsvs:
        with open(t, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        d = float(rows[0]["recordingDuration"]) if rows else 0.0
        out.append((int(d // 30), int(d // 5)))
    return out


def map30to5(p30, runs):
    out, i30 = [], 0
    for n30, n5 in runs:
        if n5 <= 0:
            continue
        seg = p30[i30:i30 + n30]
        q = np.full(n5, np.nan, np.float32)
        # 5 s window k ends at 5(k+1) s; last completed 30 s window = floor(5(k+1)/30) - 1
        j = (5 * (np.arange(n5) + 1)) // 30 - 1
        ok = (j >= 0) & (j < len(seg))
        q[ok] = seg[j[ok]]
        q[~ok & (np.arange(n5) > 0)] = np.nan
        out.append(q)
        i30 += n30
    q = np.concatenate(out) if out else np.zeros(0, np.float32)
    # fill gaps (start of runs) with the previous value
    for k in range(1, len(q)):
        if np.isnan(q[k]):
            q[k] = q[k - 1]
    return np.nan_to_num(q)


def load_labels(data_dir):
    data = {}
    for f in sorted(data_dir.glob("sub-*.npz")):
        if ".tmp" in f.name:
            continue
        z = np.load(f)
        n = len(z["F"])
        y = np.zeros(n, np.int8)
        sz = [tuple(map(int, s)) for s in z["seizures"]]
        for on, end in sz:
            y[max(0, on - T.PRE):min(n, end + T.POST)] = -1
        tc = []
        for (on, end), t, o, d in zip(sz, z["sz_type"], z["sz_onset_s"], z["sz_dur_s"]):
            if T.is_tc(str(t)):
                y[on:end] = 1
                tc.append({"on": on, "end": end, "onset_s": float(o), "dur_s": float(d)})
        data[f.stem] = {"y": y, "tc": tc}
    return data


def qscale(p, ref):
    return np.searchsorted(ref, p) / len(ref)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--data-dir", type=Path, default=Path("epiprot_results/gbm/tc5s"))
    ap.add_argument("--oof5", type=Path, default=Path("epiprot_results/gbm/tc_detect2/oof_eeg+ecg.npz"))
    ap.add_argument("--oof30", type=Path, default=Path("epiprot_results/gbm/detect_types/oof_both_lgbm.npz"))
    ap.add_argument("--out", type=Path, default=Path("epiprot_results/gbm/tc_ensemble.json"))
    ap.add_argument("--rules", nargs="+", default=["5s only", "30s only", "mean", "max"])
    ap.add_argument("--fallback", type=Path, default=None,
                    help="5 s OOF of a model WITHOUT movement, used where movement data is missing")
    ap.add_argument("--mov-cols", nargs="+", default=["head_acc_std", "body_acc_std"],
                    help="fallback where ALL of these are missing")
    ap.add_argument("--test-suffix", default=None,
                    help="score TEST patients with OOF files whose name has this suffix instead of the "
                         "given one (e.g. _clean -> _hr_none); training patients keep the given scores")
    ap.add_argument("--nohr5", type=Path, default=None,
                    help="5 s OOF of a model WITHOUT heart rate, used where the heart rate is missing")
    ap.add_argument("--nohr30", type=Path, default=None, help="same for the 30 s model")
    ap.add_argument("--stuck-hr", type=float, default=0.0,
                    help="treat the heart rate as unreliable (-> no-heart-rate models) while it varied less than this "
                         "many bpm over the last 12 windows (1 min): a stuck optical sensor; 0 = off")
    ap.add_argument("--nohr-always", action="store_true",
                    help="use the no-heart-rate models in EVERY window too (max with the main models), so a wrong "
                         "heart rate that is present cannot hide a seizure the headband sees")
    a = ap.parse_args(argv)
    data = load_labels(a.data_dir)
    subs = sorted(data)
    z5, z30 = np.load(a.oof5), np.load(a.oof30)
    p5 = {s: z5[s].astype(np.float32) for s in subs}
    alt = (lambda f: Path(str(f).replace("_clean", a.test_suffix))) if a.test_suffix else None
    fb, nomov = {}, {}
    if a.fallback is not None:
        zf = np.load(a.fallback)
        for s in subs:
            fb[s] = zf[s].astype(np.float32)
            with np.load(a.data_dir / f"{s}.npz") as zz:
                nm = [str(x) for x in zz["names"]]
                F = zz["F"]
                nomov[s] = np.all([np.isnan(F[:, nm.index(c)]) for c in a.mov_cols], axis=0)
    rl = {s: run_lengths(a.raw_dir, s) for s in subs}

    def to5(z):
        out = {}
        for s in subs:
            q = map30to5(z[s].astype(np.float32), rl[s])
            n = len(p5[s])
            out[s] = np.pad(q, (0, max(0, n - len(q))), mode="edge")[:n] if len(q) else np.zeros(n)
        return out
    p30 = to5(z30)
    # test-time inputs (default: the same scores)
    t5, t30, tfb = p5, p30, fb
    if alt is not None:
        z = np.load(alt(a.oof5))
        t5 = {s: z[s].astype(np.float32) for s in subs}
        t30 = to5(np.load(alt(a.oof30)))
        if fb:
            z = np.load(alt(a.fallback))
            tfb = {s: z[s].astype(np.float32) for s in subs}
    # heart-rate backup: windows without heart rate use models that never saw it
    nohr = a.nohr5 is not None
    if nohr:
        from .hr_robustness import WRONG, _rng, mask5, stuck_mask, wrong5
        z = np.load(a.nohr5)
        h5 = {s: z[s].astype(np.float32) for s in subs}
        h30 = to5(np.load(a.nohr30))
        hrmiss, thrmiss = {}, {}
        scen = a.test_suffix.strip("_") if a.test_suffix else "clean"
        for s in subs:
            with np.load(a.data_dir / f"{s}.npz") as zz:
                nm = [str(x) for x in zz["names"]]
                miss = np.isnan(zz["F"][:, nm.index("ecg_hr")])
                sz = [tuple(map(int, q)) for q in zz["seizures"]]
            def stuck(hr):
                return stuck_mask(hr, a.stuck_hr)
            with np.load(a.data_dir / f"{s}.npz") as zz:
                F0 = zz["F"].astype(np.float32)
            hrmiss[s] = miss | stuck(F0[:, nm.index("ecg_hr")])
            if scen in WRONG:     # wrong but present heart rate: the phone sees a value -> main models
                F2 = F0.copy()
                wrong5(F2, nm, sz, scen, _rng(a.data_dir / f"{s}.npz", scen))
                hr2 = F2[:, nm.index("ecg_hr")]
                thrmiss[s] = np.isnan(hr2) | stuck(hr2)
            else:
                thrmiss[s] = miss | mask5(len(miss), sz, scen) | stuck(F0[:, nm.index("ecg_hr")])
    order = list(subs)
    np.random.default_rng(42).shuffle(order)
    folds = [order[i::5] for i in range(5)]
    res = {}
    for rule in a.rules:
        per_bud = {b: {"detected": 0, "seizures": 0, "false_alarms": 0, "hours": 0.0, "rows": []}
                   for b in BUD}
        for test in folds:
            tr = [s for s in subs if s not in set(test)]
            r5 = np.sort(np.concatenate([p5[s][data[s]["y"] == 0] for s in tr]))
            rf = (np.sort(np.concatenate([fb[s][data[s]["y"] == 0] for s in tr])) if fb else None)
            r30 = np.sort(np.concatenate([p30[s][data[s]["y"] == 0] for s in tr]))
            if nohr:
                rh5 = np.sort(np.concatenate([h5[s][data[s]["y"] == 0] for s in tr]))
                rh30 = np.sort(np.concatenate([h30[s][data[s]["y"] == 0] for s in tr]))
            sc = {}
            for s in subs:
                q5, q30, qf = (t5, t30, tfb) if s in set(test) else (p5, p30, fb)
                a5, a30 = qscale(q5[s], r5), qscale(q30[s], r30)
                if fb:  # sensor-availability fallback
                    a5 = np.where(nomov[s], qscale(qf[s], rf), a5)
                if nohr:
                    hm = thrmiss[s] if s in set(test) else hrmiss[s]
                    if a.nohr_always:
                        a5 = np.maximum(a5, qscale(h5[s], rh5))
                        a30 = np.maximum(a30, qscale(h30[s], rh30))
                    else:
                        a5 = np.where(hm, qscale(h5[s], rh5), a5)
                        a30 = np.where(hm, qscale(h30[s], rh30), a30)
                sc[s] = {"5s only": a5, "30s only": a30, "mean": (a5 + a30) / 2,
                         "max": np.maximum(a5, a30)}[rule].astype(np.float32)
            for b in BUD:
                thr, k = T.choose(sc, data, tr, b)
                r = T.evaluate(sc, data, test, thr, k, detail=True)
                for kk in ("detected", "seizures", "false_alarms", "hours"):
                    per_bud[b][kk] += r[kk]
                per_bud[b]["rows"] += r["per_seizure"]
        res[rule] = {}
        for b in BUD:
            g = per_bud[b]
            lat = np.array([x["latency_s"] for x in g["rows"] if x["detected"]])
            out = {"sensitivity": g["detected"] / g["seizures"], "detected": g["detected"],
                   "seizures": g["seizures"], "fa_per_day": g["false_alarms"] / g["hours"] * 24,
                   "latency_median_s": float(np.median(lat)) if len(lat) else None,
                   "before_end": int(sum(x["latency_s"] < x["dur_s"] for x in g["rows"] if x["detected"]))}
            res[rule][str(b)] = out
            print(f"{rule:9s} budget {b:4}/day: {out['detected']}/{out['seizures']} "
                  f"({out['sensitivity']:.0%}) FA/day {out['fa_per_day']:.2f} "
                  f"latency {out['latency_median_s']}s before-end {out['before_end']}", flush=True)
    a.out.write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

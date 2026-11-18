"""Personal calibration of the tonic-clonic detector WITHOUT any seizure labels.

Scenario: the patient wears the device; during the first `--calib-h` hours it only
learns that patient's normal score distribution (unsupervised: no labels, seizures in
that period are not known). Afterwards the alarm threshold is relative to that personal
baseline.

Score: the combined detector of tc_ensemble ("max" rule: either the 5 s or the 30 s
model very sure), out-of-fold for every patient.

Personal transform (computed from each patient's calibration period only):
  z = (logit(score) - median_calib) / (q99.9_calib - median_calib)

Compared on exactly the same post-calibration period and seizures:
  global   : one threshold for everyone (chosen on training patients)
  personal : threshold on z (chosen on training patients, whose z also uses only their
             own first calib-h hours)

Usage: python -m epiprot.gbm.tc_personal --raw-dir /raw --calib-h 24
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from . import tc_detect as T
from .tc_ensemble import load_labels, map30to5, qscale, run_lengths

BUD = (0.25, 0.5, 1.0)


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--data-dir", type=Path, default=Path("epiprot_results/gbm/tc5s"))
    ap.add_argument("--oof5", type=Path, default=Path("epiprot_results/gbm/tc_detect2/oof_eeg+ecg.npz"))
    ap.add_argument("--oof30", type=Path, default=Path("epiprot_results/gbm/detect_types/oof_both_lgbm.npz"))
    ap.add_argument("--calib-h", type=float, default=24.0)
    ap.add_argument("--out", type=Path, default=Path("epiprot_results/gbm/tc_personal.json"))
    a = ap.parse_args(argv)
    C = int(a.calib_h * 3600 / T.W)
    full = load_labels(a.data_dir)
    subs = sorted(full)
    z5, z30 = np.load(a.oof5), np.load(a.oof30)
    p5 = {s: z5[s].astype(np.float32) for s in subs}
    p30 = {}
    for s in subs:
        q = map30to5(z30[s].astype(np.float32), run_lengths(a.raw_dir, s))
        n = len(p5[s])
        p30[s] = np.pad(q, (0, max(0, n - len(q))), mode="edge")[:n] if len(q) else np.zeros(n)

    # post-calibration evaluation data (patients with > calib + 6 h of recording)
    post = {}
    for s in subs:
        d = full[s]
        if len(d["y"]) <= C + int(6 * 3600 / T.W):
            continue
        tc = [{**e, "on": e["on"] - C, "end": e["end"] - C, "onset_s": e["onset_s"] - C * T.W}
              for e in d["tc"] if e["on"] >= C]
        post[s] = {"y": d["y"][C:], "tc": tc}
    psubs = sorted(post)
    print(f"{len(psubs)}/{len(subs)} patients have > {a.calib_h + 6:.0f} h; "
          f"tonic-clonic after calibration: {sum(len(post[s]['tc']) for s in psubs)} "
          f"(of {sum(len(full[s]['tc']) for s in subs)})", flush=True)

    order = list(subs)
    np.random.default_rng(42).shuffle(order)
    folds = [order[i::5] for i in range(5)]
    res = {}
    for mode in ("global", "personal"):
        agg = {b: {"detected": 0, "seizures": 0, "false_alarms": 0, "hours": 0.0, "lat": []}
               for b in BUD}
        for test in folds:
            tr = [s for s in subs if s not in set(test)]
            r5 = np.sort(np.concatenate([p5[s][full[s]["y"] == 0] for s in tr]))
            r30 = np.sort(np.concatenate([p30[s][full[s]["y"] == 0] for s in tr]))
            sc = {}
            for s in psubs:
                c = np.maximum(qscale(p5[s], r5), qscale(p30[s], r30)).astype(np.float32)
                if mode == "personal":
                    lc = logit(c[:C])
                    med, hi = np.median(lc), np.quantile(lc, 0.999)
                    c = (logit(c) - med) / max(hi - med, 1e-3)
                sc[s] = c[C:].astype(np.float32)
            trp = [s for s in tr if s in post]
            tep = [s for s in test if s in post]
            for b in BUD:
                thr, k = T.choose(sc, post, trp, b)
                r = T.evaluate(sc, post, tep, thr, k, detail=True)
                for kk in ("detected", "seizures", "false_alarms", "hours"):
                    agg[b][kk] += r[kk]
                agg[b]["lat"] += [x["latency_s"] for x in r["per_seizure"] if x["detected"]]
        res[mode] = {}
        for b in BUD:
            g = agg[b]
            o = {"detected": g["detected"], "seizures": g["seizures"],
                 "sensitivity": g["detected"] / max(1, g["seizures"]),
                 "fa_per_day": g["false_alarms"] / g["hours"] * 24, "hours": g["hours"],
                 "latency_median_s": float(np.median(g["lat"])) if g["lat"] else None}
            res[mode][str(b)] = o
            print(f"{mode:8s} budget {b:4}/day: {o['detected']}/{o['seizures']} "
                  f"({o['sensitivity']:.0%}) FA/day {o['fa_per_day']:.2f} "
                  f"latency {o['latency_median_s']}s  ({o['hours']:.0f} h)", flush=True)
    a.out.write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

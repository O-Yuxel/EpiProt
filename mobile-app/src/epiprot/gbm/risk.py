"""SeizeIT2 general model as a seizure-RISK FORECAST (low / medium / high).

Uses the out-of-fold probabilities of the patient-wise CV (new patients only), so every
number is for patients the model has never seen.

Per window, the score is a causal 10-min average of the OOF probability. Tier cut-offs
are global quantiles of that score (no labels used): low = bottom 50 %, medium = 50-80 %,
high = top 20 % of the time. For each seizure the tier shown `lead` minutes BEFORE onset
is recorded (the warning is at least 30 min ahead). Reported per tier: share of time,
share of seizures, seizure rate per hour, and relative risk vs the low tier.

Usage: python -m epiprot.gbm.risk --oof epiprot_results/gbm/hrv_all/oof_predictions.npz \
           --raw-dir /raw --out epiprot_results/gbm/risk_hrv_all.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .events import smooth
from .labels import WIN_PER_MIN
from .timeline import build_timeline

TIERS = ("low", "medium", "high")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--oof", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--lead-min", type=float, default=30.0)
    ap.add_argument("--smooth", type=int, default=20)
    ap.add_argument("--q", type=float, nargs=2, default=(0.5, 0.8))
    a = ap.parse_args(argv)
    z = np.load(a.oof)
    lead = int(a.lead_min * WIN_PER_MIN)
    post = 60 * WIN_PER_MIN

    scores, valid, onsets = {}, {}, {}
    for s in z.files:
        p = smooth(z[s].astype(np.float32), a.smooth)
        tl = build_timeline(a.raw_dir, s, len(p))
        sz = tl.seizures if tl else []
        v = np.ones(len(p), bool)
        for on, end in sz:
            v[on:min(len(p), end + post)] = False   # ictal + 1 h post-ictal not "forecast time"
        scores[s], valid[s] = p, v
        onsets[s] = [on - lead for on, _ in sz if on - lead >= 0]
    allv = np.concatenate([scores[s][valid[s]] for s in z.files])
    c1, c2 = np.quantile(allv, a.q)

    def tier(x):
        return np.where(x >= c2, 2, np.where(x >= c1, 1, 0))

    t_win = np.zeros(3)
    t_sz = np.zeros(3)
    for s in z.files:
        t = tier(scores[s])
        t_win += np.bincount(t[valid[s]], minlength=3)
        for i in onsets[s]:
            t_sz[t[i]] += 1
    hours = t_win / (60 * WIN_PER_MIN)
    rate = t_sz / hours
    res = {"lead_min": a.lead_min, "cutoffs": [float(c1), float(c2)],
           "seizures": int(t_sz.sum()), "hours": float(hours.sum()), "tiers": {}}
    for k, name in enumerate(TIERS):
        res["tiers"][name] = {"time_share": float(t_win[k] / t_win.sum()),
                              "seizure_share": float(t_sz[k] / t_sz.sum()),
                              "seizures_per_day": float(rate[k] * 24),
                              "relative_risk_vs_low": float(rate[k] / rate[0])}
        print(f"{name:7s} time {t_win[k] / t_win.sum():5.1%} | seizures {t_sz[k] / t_sz.sum():5.1%} "
              f"({int(t_sz[k])}) | {rate[k] * 24:.2f}/day | RR {rate[k] / rate[0]:.2f}x", flush=True)
    a.out.write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

"""Objective checks of the risk forecast (is it really useful, or an artefact?).

For a set of out-of-fold probabilities (unseen patients):
  1. high-risk tier (top `--top` share of time): share of seizures, relative risk vs rest
  2. same for a trivial rule using ONLY time since the last seizure (clustering baseline)
  3. same restricted to "isolated" seizures (no seizure in the previous `--iso-h` hours),
     where the clustering shortcut cannot help
  4. time-shift surrogate test: each patient's score series is circularly shifted by a
     random offset (destroys alignment with seizures, keeps everything else), repeated
     `--n-surr` times -> p-value of the observed relative risk
  5. per patient: share of patients whose high-risk seizure rate exceeds their rest rate

Tier is read `--lead-min` before each onset. Ictal + 1 h post-ictal are not forecast time.

Usage: python -m epiprot.gbm.risk_check --raw-dir /raw \
           --oof epiprot_results/gbm/hrv_all/oof_predictions.npz [more.npz ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .events import smooth
from .labels import WIN_PER_MIN
from .timeline import build_timeline

H = 60 * WIN_PER_MIN  # windows per hour


def load_patients(raw_dir, subs, lengths):
    out = {}
    for s in subs:
        tl = build_timeline(raw_dir, s, lengths[s])
        out[s] = tl.seizures if tl else []
    return out


def hours_since_last(n, seizures):
    t = np.full(n, 1e6, np.float32)
    ends = np.array([e for _, e in seizures])
    if len(ends):
        idx = np.arange(n)
        k = np.searchsorted(ends, idx, side="right") - 1
        ok = k >= 0
        t[ok] = (idx[ok] - ends[k[ok]]) / H
    return t


def analyse(scores, seizures, lead, top, iso_h, per_patient=False):
    valid, onsets, iso = {}, {}, {}
    for s, p in scores.items():
        v = np.ones(len(p), bool)
        for on, end in seizures[s]:
            v[on:min(len(p), end + H)] = False
        valid[s] = v
        ons = [on for on, _ in seizures[s]]
        ends = [e for _, e in seizures[s]]
        onsets[s] = [on - lead for on in ons if on - lead >= 0]
        iso[s] = [on - lead for on in ons if on - lead >= 0
                  and not any(on - iso_h * H <= e <= on for e in ends)]
    if per_patient:  # each patient spends `top` of its own time in high risk
        cuts = {s: np.quantile(p[valid[s]], 1 - top) for s, p in scores.items()}
    else:
        g = np.quantile(np.concatenate([scores[s][valid[s]] for s in scores]), 1 - top)
        cuts = {s: g for s in scores}

    def stats(which):
        th = tr = sh = sr = 0
        pat_better = pat_n = 0
        for s, p in scores.items():
            hi = p >= cuts[s]
            a = int((hi & valid[s]).sum())
            b = int((~hi & valid[s]).sum())
            k_hi = sum(bool(hi[i]) for i in which[s])
            k_lo = len(which[s]) - k_hi
            th, tr, sh, sr = th + a, tr + b, sh + k_hi, sr + k_lo
            if which[s] and a and b:
                pat_n += 1
                pat_better += (k_hi / a) > (k_lo / b)
        rr = (sh / th) / (sr / tr) if sr and th else float("nan")
        return {"time_share_high": th / (th + tr), "seizures": sh + sr,
                "seizure_share_high": sh / max(1, sh + sr), "relative_risk": rr,
                "patients_high_rate_gt_rest": f"{pat_better}/{pat_n}"}
    return stats(onsets), stats(iso)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--oof", type=Path, nargs="+", required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--lead-min", type=float, default=30.0)
    ap.add_argument("--top", type=float, default=0.10)
    ap.add_argument("--iso-h", type=float, default=4.0)
    ap.add_argument("--smooth", type=int, default=20)
    ap.add_argument("--n-surr", type=int, default=200)
    ap.add_argument("--per-patient", action="store_true",
                    help="high-risk cut-off per patient (removes between-patient offsets)")
    a = ap.parse_args(argv)
    lead = int(a.lead_min * WIN_PER_MIN)
    z0 = np.load(a.oof[0])
    subs = sorted(z0.files)
    seizures = load_patients(a.raw_dir, subs, {s: len(z0[s]) for s in subs})
    report = {}

    def show(name, r_all, r_iso, extra=""):
        print(f"{name:34s} ALL: high={r_all['time_share_high']:.0%} time -> "
              f"{r_all['seizure_share_high']:.1%} of {r_all['seizures']} seizures, "
              f"RR {r_all['relative_risk']:.2f}, pts {r_all['patients_high_rate_gt_rest']} | "
              f"ISOLATED: {r_iso['seizure_share_high']:.1%} of {r_iso['seizures']}, "
              f"RR {r_iso['relative_risk']:.2f}, pts {r_iso['patients_high_rate_gt_rest']}{extra}",
              flush=True)
        report[name] = {"all": r_all, "isolated": r_iso}

    # trivial clustering baseline: the more recent the last seizure, the higher the risk
    base = {s: -hours_since_last(len(z0[s]), seizures[s]) for s in subs}
    show("RULE: time since last seizure", *analyse(base, seizures, lead, a.top, a.iso_h, a.per_patient))

    rng = np.random.default_rng(0)
    for f in a.oof:
        z = np.load(f)
        sc = {s: smooth(z[s].astype(np.float32), a.smooth) for s in subs}
        r_all, r_iso = analyse(sc, seizures, lead, a.top, a.iso_h, a.per_patient)
        surr_all, surr_iso = [], []
        for _ in range(a.n_surr):
            sh = {s: np.roll(p, int(rng.integers(H, max(H + 1, len(p) - H)))) for s, p in sc.items()}
            x, y = analyse(sh, seizures, lead, a.top, a.iso_h, a.per_patient)
            surr_all.append(x["relative_risk"])
            surr_iso.append(y["relative_risk"])
        surr_all, surr_iso = np.array(surr_all), np.array(surr_iso)
        p_all = (1 + np.sum(surr_all >= r_all["relative_risk"])) / (1 + a.n_surr)
        p_iso = (1 + np.sum(surr_iso >= r_iso["relative_risk"])) / (1 + a.n_surr)
        name = f.parent.name
        show(f"MODEL {name}", r_all, r_iso,
             f"\n{'':34s} surrogate RR all {np.median(surr_all):.2f} "
             f"(95% {np.quantile(surr_all, 0.95):.2f}) p={p_all:.3f} | isolated "
             f"{np.nanmedian(surr_iso):.2f} (95% {np.nanquantile(surr_iso, 0.95):.2f}) p={p_iso:.3f}")
        report[f"MODEL {name}"] |= {"surrogate_p_all": float(p_all),
                                    "surrogate_p_isolated": float(p_iso),
                                    "surrogate_rr_all_median": float(np.median(surr_all)),
                                    "surrogate_rr_iso_median": float(np.nanmedian(surr_iso))}
    if a.out:
        a.out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

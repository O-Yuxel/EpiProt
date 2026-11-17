"""Error analysis of the combined tonic-clonic detector (tc_ensemble "max" rule).

Same out-of-fold scores and fold-wise thresholds as tc_ensemble. Reports
  * every tonic-clonic seizure: detected?, latency, vigilance (awake/asleep from the
    annotations), duration, sensor availability, heart-rate rise, peak scores
  * false alarms: concentration in few patients, which model triggered them, signal
    quality at the alarm (missing sensors, extreme EEG amplitude = artefact), movement
    (activity) and a sleep proxy (very little movement during the previous 10 min),
    each compared with randomly chosen normal windows of the same patients.

Usage: python -m epiprot.gbm.tc_errors --raw-dir /raw --budget 0.25
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np

from . import tc_detect as T
from .tc_ensemble import load_labels, map30to5, qscale, run_lengths


def tc_meta(raw_dir, sub):
    """(onset window, vigilance, localization) of each tonic-clonic seizure."""
    tsvs = sorted((raw_dir / sub / "ses-01" / "eeg").glob("*_events.tsv"),
                  key=lambda p: int(re.search(r"run-(\d+)", p.name).group(1)))
    out, pos = [], 0
    for t in tsvs:
        with open(t, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        n = int((float(rows[0]["recordingDuration"]) if rows else 0.0) // T.W)
        for r in rows:
            if r["eventType"].lower().startswith("sz") and T.is_tc(r["eventType"]):
                a = pos + int(float(r["onset"]) // T.W)
                if a < pos + n:
                    out.append((a, r["vigilance"], r["localization"]))
        pos += n
    return {a: (v, l) for a, v, l in out}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--data-dir", type=Path, default=Path("epiprot_results/gbm/tc5s"))
    ap.add_argument("--oof5", type=Path, default=Path("epiprot_results/gbm/tc_detect2/oof_eeg+ecg.npz"))
    ap.add_argument("--oof30", type=Path, default=Path("epiprot_results/gbm/detect_types/oof_both_lgbm.npz"))
    ap.add_argument("--budget", type=float, default=0.25)
    ap.add_argument("--fallback", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("epiprot_results/gbm/tc_errors.json"))
    a = ap.parse_args(argv)
    data = load_labels(a.data_dir)
    subs = sorted(data)
    z5, z30 = np.load(a.oof5), np.load(a.oof30)
    p5 = {s: z5[s].astype(np.float32) for s in subs}
    fb, nomov = {}, {}
    if a.fallback is not None:
        zf = np.load(a.fallback)
        for s in subs:
            fb[s] = zf[s].astype(np.float32)
            with np.load(a.data_dir / f"{s}.npz") as zz:
                nm = [str(x) for x in zz["names"]]
                nomov[s] = (np.isnan(zz["F"][:, nm.index("head_acc_std")])
                            & np.isnan(zz["F"][:, nm.index("body_acc_std")]))
    p30 = {}
    for s in subs:
        q = map30to5(z30[s].astype(np.float32), run_lengths(a.raw_dir, s))
        n = len(p5[s])
        p30[s] = np.pad(q, (0, max(0, n - len(q))), mode="edge")[:n] if len(q) else np.zeros(n)
    order = list(subs)
    np.random.default_rng(42).shuffle(order)
    folds = [order[i::5] for i in range(5)]

    sz_rows, fa_rows, ctrl_rows = [], [], []
    rng = np.random.default_rng(0)
    for test in folds:
        tr = [s for s in subs if s not in set(test)]
        r5 = np.sort(np.concatenate([p5[s][data[s]["y"] == 0] for s in tr]))
        r30 = np.sort(np.concatenate([p30[s][data[s]["y"] == 0] for s in tr]))
        q5 = {s: qscale(p5[s], r5).astype(np.float32) for s in subs}
        if fb:
            rf = np.sort(np.concatenate([fb[s][data[s]["y"] == 0] for s in tr]))
            q5 = {s: np.where(nomov[s], qscale(fb[s], rf), q5[s]).astype(np.float32) for s in subs}
        q30 = {s: qscale(p30[s], r30).astype(np.float32) for s in subs}
        sc = {s: np.maximum(q5[s], q30[s]) for s in subs}
        thr, k = T.choose(sc, data, tr, a.budget)
        for s in test:
            z = np.load(a.data_dir / f"{s}.npz")
            F, names = z["F"], [str(x) for x in z["names"]]
            col = {n: i for i, n in enumerate(names)}
            eeg_rms = F[:, col["eegL_rms"]]
            med_rms = np.nanmedian(eeg_rms)
            iqr_rms = np.subtract(*np.nanpercentile(eeg_rms, [75, 25])) or 1.0
            mov = F[:, col["head_acc_std"]]
            mov_f = np.where(np.isnan(mov), np.nanmedian(mov), mov)
            mov10 = np.convolve(mov_f, np.ones(120) / 120)[: len(mov_f)]  # previous 10 min
            sleep_cut = np.nanpercentile(mov10, 25)
            act_cut = np.nanpercentile(mov_f, 90)
            hr = F[:, col["ecg_hr"]]

            def ctx(i):
                return {"eeg_missing": bool(np.isnan(F[i, col["eegL_ll"]])),
                        "ecg_missing": bool(np.isnan(hr[i])),
                        "emg_missing": bool(np.isnan(F[i, col["emg_rms"]])),
                        "mov_missing": bool(np.isnan(mov[i])),
                        "eeg_artefact": bool(abs(eeg_rms[i] - med_rms) / iqr_rms > 5),
                        "active": bool(mov_f[i] > act_cut),
                        "sleep_proxy": bool(mov10[i] < sleep_cut)}

            al = T.alarms(sc[s], thr, k)
            y = data[s]["y"]
            meta = tc_meta(a.raw_dir, s)
            for e in data[s]["tc"]:
                aa = al[(al >= e["on"]) & (al < e["end"] + T.AFTER_END)]
                seg = slice(e["on"], e["end"] + T.AFTER_END)
                pre = slice(max(0, e["on"] - 60), e["on"])
                vig, loc = meta.get(e["on"], ("?", "?"))
                hr_rise = (np.nanmax(hr[seg]) - np.nanmedian(hr[pre])
                           if np.isfinite(hr[seg]).any() and np.isfinite(hr[pre]).any() else None)
                sz_rows.append({
                    "sub": s, "detected": bool(len(aa)),
                    "latency_s": float((aa[0] + 1) * T.W - e["onset_s"]) if len(aa) else None,
                    "dur_s": e["dur_s"], "vigilance": vig, "localization": loc,
                    "peak_q5": float(q5[s][seg].max()), "peak_q30": float(q30[s][seg].max()),
                    "thr": float(thr), "k": int(k),
                    "hr_rise_bpm": None if hr_rise is None else float(hr_rise),
                    "eeg_missing_frac": float(np.isnan(F[seg, col["eegL_ll"]]).mean()),
                    "ecg_missing_frac": float(np.isnan(hr[seg]).mean()),
                    "mov_missing_frac": float(np.isnan(mov[seg]).mean())})
            for i in al:
                if y[i] == 0:
                    fa_rows.append({"sub": s, "idx": int(i),
                                    "by_5s": bool(q5[s][i] >= q30[s][i])} | ctx(i))
            neg = np.flatnonzero(y == 0)
            for i in rng.choice(neg, min(len(neg), 200), replace=False):
                ctrl_rows.append({"sub": s} | ctx(int(i)))

    # ---- report ----
    det = [r for r in sz_rows if r["detected"]]
    lat_all = np.array([r["latency_s"] for r in sz_rows if r["detected"]])
    hours = sum(float((data[s]["y"] == 0).sum() * T.W / 3600) for s in subs)
    print(f"latency median {np.median(lat_all):.1f}s IQR {np.percentile(lat_all,25):.1f}-{np.percentile(lat_all,75):.1f} min {lat_all.min():.1f} max {lat_all.max():.1f}; "
          f"<=30s {(lat_all<=30).sum()} <=60s {(lat_all<=60).sum()}; before end {sum(r['latency_s'] < r['dur_s'] for r in sz_rows if r['detected'])}; "
          f"non-seizure hours {hours:.0f}; seizure dur median {np.median([r['dur_s'] for r in sz_rows]):.0f}s")
    miss = [r for r in sz_rows if not r["detected"]]
    print(f"\nTONIC-CLONIC: detected {len(det)}/{len(sz_rows)}  (budget {a.budget}/day)")
    for v in ("awake", "asleep", "un"):
        g = [r for r in sz_rows if r["vigilance"] == v]
        if g:
            print(f"  {v:7s}: {sum(r['detected'] for r in g)}/{len(g)}")
    print("\nMISSED seizures:")
    for r in miss:
        print(f"  {r['sub']} {r['vigilance']:6s} dur {r['dur_s']:5.0f}s  peak5s {r['peak_q5']:.5f} "
              f"peak30s {r['peak_q30']:.5f} (thr {r['thr']:.5f}, k={r['k']})  HR rise "
              f"{r['hr_rise_bpm'] if r['hr_rise_bpm'] is None else round(r['hr_rise_bpm'])} bpm  "
              f"missing eeg/ecg/mov {r['eeg_missing_frac']:.0%}/{r['ecg_missing_frac']:.0%}/"
              f"{r['mov_missing_frac']:.0%}")
    hrs = [r["hr_rise_bpm"] for r in det if r["hr_rise_bpm"] is not None]
    print(f"  (detected seizures: median HR rise {np.median(hrs):.0f} bpm, median dur "
          f"{np.median([r['dur_s'] for r in det]):.0f}s)")

    print(f"\nFALSE ALARMS: {len(fa_rows)}")
    from collections import Counter
    c = Counter(r["sub"] for r in fa_rows)
    tot = len(fa_rows)
    top = c.most_common()
    cum = np.cumsum([n for _, n in top])
    print(f"  patients with >=1 false alarm: {len(c)}/{len(subs)}")
    for q in (1, 3, 5, 10):
        if len(cum) >= q:
            print(f"  top {q:2d} patients cause {cum[q - 1] / tot:.0%} of false alarms")
    print(f"  top patients: {top[:8]}")
    print(f"  triggered by 5 s model: {np.mean([r['by_5s'] for r in fa_rows]):.0%} "
          f"(else 30 s model)")
    print("\n  condition at alarm        false alarms   normal windows")
    for key in ("eeg_missing", "ecg_missing", "emg_missing", "mov_missing", "eeg_artefact",
                "active", "sleep_proxy"):
        fa_m = np.mean([r[key] for r in fa_rows]) if fa_rows else float("nan")
        ct_m = np.mean([r[key] for r in ctrl_rows])
        print(f"  {key:22s}   {fa_m:8.0%}       {ct_m:8.0%}")
    a.out.write_text(json.dumps({"seizures": sz_rows, "false_alarms": fa_rows,
                                 "fa_by_patient": top}, indent=2))


if __name__ == "__main__":
    main()

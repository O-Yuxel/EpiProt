"""Replay one SeizeIT2 patient through the final EpiProt system on a simulated phone.

Uses the final model's real out-of-fold alarms (5 s model with movement fallback + 30 s
model, "max" rule, threshold chosen on the training patients of that patient's fold,
0.25 false alarms/day budget). Each alarm goes through the alarm / recovery flow
(flow.py), missed big seizures are entered by hand, raw signals are attached, then the
phone builds the doctor report and queues it until it is online.

Assumptions (demo only): monitoring starts on 10.11.2026 08:00 (SeizeIT2 clock times are
anonymised); patient behaviour as in flow.BEHAVIOUR.

Usage: python -m epiprot.app.simulate --raw-dir /raw --sub sub-115 \
           --out-dir epiprot_results/app_demo/sub-115
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
from pathlib import Path

import numpy as np

from epiprot.gbm import tc_detect as T
from epiprot.gbm.tc_ensemble import load_labels, map30to5, qscale, run_lengths

from . import report
from .eventlog import EventLog
from . import health
from .flow import Truth, handle_alarm, manual_entry
from .signals import snippet

LOW = 0.99  # score level used by the device to estimate seizure start / end


def system_scores(raw_dir, data_dir, oof5, fallback, oof30, sub, budget):
    data = load_labels(data_dir)
    subs = sorted(data)
    z5, zf, z30 = np.load(oof5), np.load(fallback), np.load(oof30)
    order = list(subs)
    np.random.default_rng(42).shuffle(order)
    test = next(f for f in [order[i::5] for i in range(5)] if sub in f)
    tr = [s for s in subs if s not in set(test)]
    need = tr + [sub]
    p5, fb, p30, nomov = {}, {}, {}, {}
    for s in need:
        p5[s], fb[s] = z5[s].astype(np.float32), zf[s].astype(np.float32)
        q = map30to5(z30[s].astype(np.float32), run_lengths(raw_dir, s))
        n = len(p5[s])
        p30[s] = np.pad(q, (0, max(0, n - len(q))), mode="edge")[:n]
        with np.load(data_dir / f"{s}.npz") as zz:
            nm = [str(x) for x in zz["names"]]
            nomov[s] = np.isnan(zz["F"][:, nm.index("head_acc_std")]) & np.isnan(zz["F"][:, nm.index("body_acc_std")])
    r5 = np.sort(np.concatenate([p5[s][data[s]["y"] == 0] for s in tr]))
    rf = np.sort(np.concatenate([fb[s][data[s]["y"] == 0] for s in tr]))
    r30 = np.sort(np.concatenate([p30[s][data[s]["y"] == 0] for s in tr]))
    sc = {}
    for s in need:
        a5 = np.where(nomov[s], qscale(fb[s], rf), qscale(p5[s], r5))
        sc[s] = np.maximum(a5, qscale(p30[s], r30)).astype(np.float32)
    thr, k = T.choose(sc, data, tr, budget)
    return sc[sub], thr, k


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--sub", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--data-dir", type=Path, default=Path("epiprot_results/gbm/tc5s"))
    ap.add_argument("--oof5", type=Path, default=Path("epiprot_results/gbm/tc_detect3/oof_eeg+ecg+mov.npz"))
    ap.add_argument("--fallback", type=Path, default=Path("epiprot_results/gbm/tc_detect3/oof_eeg+ecg.npz"))
    ap.add_argument("--oof30", type=Path, default=Path("epiprot_results/gbm/detect_types/oof_both_lgbm.npz"))
    ap.add_argument("--budget", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    if a.out_dir.exists():
        shutil.rmtree(a.out_dir)
    log = EventLog(a.out_dir)
    rng = np.random.default_rng(a.seed)

    score, thr, k = system_scores(a.raw_dir, a.data_dir, a.oof5, a.fallback, a.oof30, a.sub, a.budget)
    z = np.load(a.data_dir / f"{a.sub}.npz")
    F, names = z["F"], [str(x) for x in z["names"]]
    col = {n: i for i, n in enumerate(names)}
    hr = F[:, col["ecg_hr"]]
    mov = F[:, col["head_acc_std"]]
    mov_f = np.where(np.isnan(mov), np.nanmedian(mov), mov)
    mov10 = np.convolve(mov_f, np.ones(120) / 120)[: len(mov_f)]
    sleep_cut = np.nanpercentile(mov10, 25)
    seizures = [(int(s[0]), int(s[1]), str(t), float(o), float(d))
                for s, t, o, d in zip(z["seizures"], z["sz_type"], z["sz_onset_s"], z["sz_dur_s"])]
    n = len(F)

    def extra(on_i, end_i):
        pre = hr[max(0, on_i - 60):on_i]
        seg = hr[on_i:min(n, end_i + 6)]
        return {"hr_before": float(np.nanmedian(pre)) if np.isfinite(pre).any() else None,
                "hr_peak": float(np.nanmax(seg)) if np.isfinite(seg).any() else None}

    alarm_idx = T.alarms(score, thr, k)
    print(f"{a.sub}: {n * T.W / 3600:.1f} h, threshold {thr:.6f} (k={k}), {len(alarm_idx)} alarms, "
          f"{sum(T.is_tc(s[2]) for s in seizures)} tonic-clonic seizures")
    detected = set()
    for i in alarm_idx:
        truth = Truth("none")
        for j, (on, end, t, o_s, d_s) in enumerate(seizures):
            if on <= i < end + T.AFTER_END:
                truth = Truth("tonic_clonic" if T.is_tc(t) else "other_seizure", o_s, o_s + d_s)
                if T.is_tc(t):
                    detected.add(j)
                break
        s0 = i
        while s0 > 0 and score[s0 - 1] >= LOW:
            s0 -= 1
        e0, below = i, 0
        while e0 < n - 1 and below < 6:
            e0 += 1
            below = below + 1 if score[e0] < LOW else 0
        e0 -= below
        ex = extra(s0, e0)
        eid = handle_alarm(log, (i + 1) * T.W, s0 * T.W, (e0 + 1) * T.W, truth,
                           asleep=bool(mov10[i] < sleep_cut), rng=rng, extra=ex)
        p = log.signal_path(eid)
        status = snippet(a.raw_dir, a.sub, s0 * T.W, p)
        log.update(eid, signal_file=str(p), sensor_status=status)

    for j, (on, end, t, o_s, d_s) in enumerate(seizures):
        if T.is_tc(t) and j not in detected:
            ex = extra(on, end) | {"vigilance": "asleep" if mov10[on] < sleep_cut else "awake"}
            eid = manual_entry(log, o_s + d_s + rng.uniform(2, 8) * 3600, o_s,
                               float(np.round(d_s / 30) * 30), ex)
            p = log.signal_path(eid)
            log.update(eid, signal_file=str(p), sensor_status=snippet(a.raw_dir, a.sub, o_s, p))

    # sensor-health monitor: warnings to the watch, never during an alarm / recovery monitoring
    busy = []
    for e in log.events():
        if e["source"] == "device":
            steps = log.flow(e["id"])
            end = max([r["t_s"] for r in steps if r["step"] != "confirmed"] or [e["alarm_s"]])
            busy.append((e["alarm_s"], end))
    q = health.window_quality(F, names)
    eps = health.monitor(q, busy)
    for ep in eps:
        log.add_sensor_alert(ep)
    usable = health.usable_share(q)
    print(f"sensor warnings to the watch: {len(eps)} ({len(eps) / (n * T.W / 86400):.2f}/day), "
          f"reminders {sum(len(e.reminders) for e in eps)}, usable "
          + ", ".join(f"{k} {v:.1%}" for k, v in usable.items()))

    now = n * T.W
    start = dt.datetime(2026, 11, 10, 8, 0)
    pdf = report.build(log, a.sub, start, n * T.W / 3600, now, quality=q)
    pkg = report.package(log, pdf, a.sub, now)
    print(f"report: {pdf}\npackage queued: {pkg}")
    print(f"phone offline -> sent: {log.flush_outbox(now, online=False)}")
    print(f"phone online  -> sent: {log.flush_outbox(now + 600, online=True)}")
    for e in log.events():
        print(f"  {e['kind']:13s} {e['source']:6s} onset {e['onset_s'] / 3600:7.2f} h  dur {e['duration_s'] or 0:5.0f}s  "
              f"pin {e['cancelled_with_pin']}  caregiver {e['caregiver_notified_s'] is not None}  "
              f"emergency {e['emergency_s'] is not None}  answered {e['recovery_response_s']}")


if __name__ == "__main__":
    main()

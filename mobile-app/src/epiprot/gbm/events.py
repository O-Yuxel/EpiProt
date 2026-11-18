"""Event-level (alarm) evaluation — what a wearable actually does.

Per patient, a causal moving average of the window probabilities is thresholded.
When it crosses the threshold an alarm fires ("seizure expected in 5-30 min") and a
refractory period follows (no new alarm for `refractory` windows).

- An event (lead seizure) is predicted if an alarm fires inside its pre-ictal period.
- A false alarm is an alarm fired in a clean interictal window (y_clean == 0).
- FA/h = false alarms per hour of clean interictal recording.
- Chance sensitivity: a random Poisson alarm generator with the same FA/h hits a
  pre-ictal window of SOP minutes with probability 1 - exp(-FA/h * SOP/60).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .context import causal_mean
from .labels import Event

HOURS_PER_WINDOW = 30.0 / 3600.0


@dataclass
class PatientSeries:
    sub: str
    prob: np.ndarray
    y: np.ndarray            # cleaned labels
    events: list[Event]


def smooth(prob: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return prob
    return causal_mean(prob[:, None].astype(np.float32), k)[:, 0]


def alarms(score: np.ndarray, thr: float, refractory: int) -> np.ndarray:
    above = np.flatnonzero(score >= thr)
    out, nxt = [], -1
    for i in above:
        if i >= nxt:
            out.append(i)
            nxt = i + refractory
    return np.asarray(out, dtype=np.int64)


def evaluate(series: list[PatientSeries], thr: float, k: int,
             refractory: int = 60, sop_min: float = 25.0) -> dict:
    n_ev = hit = fa = 0
    inter_windows = 0
    per_patient = {}
    for ps in series:
        a = alarms(smooth(ps.prob, k), thr, refractory)
        inter = ps.y == 0
        inter_windows += int(inter.sum())
        p_fa = int(inter[a].sum()) if len(a) else 0
        p_hit = sum(bool(((a >= ev.pos_start) & (a < ev.pos_end)).any()) for ev in ps.events)
        fa += p_fa
        hit += p_hit
        n_ev += len(ps.events)
        per_patient[ps.sub] = {"events": len(ps.events), "hit": p_hit, "fa": p_fa,
                               "inter_h": float(inter.sum() * HOURS_PER_WINDOW)}
    hours = inter_windows * HOURS_PER_WINDOW
    fah = fa / hours if hours else float("nan")
    sens = hit / n_ev if n_ev else float("nan")
    return {
        "thr": float(thr), "k": int(k), "events": n_ev, "predicted": hit,
        "sensitivity": sens, "false_alarms": fa, "interictal_hours": hours,
        "fa_per_hour": fah, "fa_per_day": fah * 24,
        "chance_sensitivity": float(1 - np.exp(-fah * sop_min / 60)),
        "per_patient": per_patient,
    }


def pick_operating_point(series: list[PatientSeries], max_fah: float,
                         ks=(1, 4, 8, 12), n_thr: int = 60, refractory: int = 60,
                         sop_min: float = 25.0) -> dict:
    """On validation series: maximise sensitivity subject to FA/h <= max_fah."""
    allp = np.concatenate([s.prob for s in series])
    thrs = np.unique(np.quantile(allp, np.linspace(0.80, 0.9999, n_thr)))
    best = None
    for k in ks:
        for t in thrs:
            r = evaluate(series, t, k, refractory, sop_min)
            if r["fa_per_hour"] <= max_fah:
                key = (r["sensitivity"], -r["fa_per_hour"])
                if best is None or key > best[0]:
                    best = (key, r)
    if best is None:  # cannot meet the FA budget: take the strictest threshold
        return evaluate(series, float(thrs[-1]), ks[-1], refractory, sop_min)
    return best[1]

"""Sensor-health monitor: the phone checks every 5 s window it receives and, when data from
the headband or the watch stays missing or bad, sends a warning to the watch.

Per 5 s window and signal (computed on the phone from the same window features the model
uses, so it costs nothing extra):
  brain signal (headband) : missing, flat (std < 1 uV: electrode off / lead broken) or
                            saturated (std > 2000 uV: loose electrode, cable moving)
  head movement (headband): missing
  heart rate (watch)      : missing or no heartbeat found in the window
  body movement (watch)   : missing

Rules (per device):
  - Short gaps are ignored: a warning is sent only when >= 75 % of the windows in the last
    2 min are bad (so short artefacts while chewing or scratching do not vibrate).
    Tested on all 125 SeizeIT2 patients: ~1 warning per day (60 s: 4.5 per day, too many).
  - Warning on the watch says which device, which signal and what to do, and what it means
    for detection.
  - Reminders while the problem continues after 15, 30 and 60 min, then every hour.
  - "Fixed" message when the last 30 s are all good again.
  - Never during an active seizure alarm or recovery monitoring (the alarm has priority);
    a warning that is due then is sent right after.
  - Also at night: an unworn headband at night is exactly when a seizure would be missed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

W = 5.0
BAD_WIN = 24            # 2 min
BAD_FRAC = 0.75
GOOD_WIN = 6            # 30 s all good -> fixed
REMIND_S = (900, 1800, 3600)   # gaps between reminders, last one repeats
FLAT_LOG, SAT_LOG = 0.0, 3.3     # log10(std in uV): 1 uV and 2000 uV

DEVICES = {
    "headband": [("brain", "Brain signal (EEG)"), ("head_mov", "Head movement")],
    "watch": [("heart", "Heart rate"), ("body_mov", "Body movement")],
}
OK, MISSING, POOR = 0, 1, 2


def window_quality(F: np.ndarray, names: list[str]) -> dict[str, np.ndarray]:
    c = {n: F[:, i] for i, n in enumerate(names)}
    q = {}
    eeg = np.zeros(len(F), np.int8)
    for ch in ("eegL", "eegX"):
        rms = c[f"{ch}_rms"]
        eeg = np.maximum(eeg, np.where((rms < FLAT_LOG) | (rms > SAT_LOG), POOR, OK).astype(np.int8))
        eeg[np.isnan(rms)] = MISSING
    q["brain"] = eeg
    q["head_mov"] = np.where(np.isnan(c["head_acc_std"]), MISSING, OK).astype(np.int8)
    q["heart"] = np.where(np.isnan(c["ecg_hr"]), MISSING, OK).astype(np.int8)
    q["body_mov"] = np.where(np.isnan(c["body_acc_std"]), MISSING, OK).astype(np.int8)
    return q


# Codes sent to the watch app (watch-app/.../core/Warnings.kt); the watch shows the text in its own language.
IMPACT_TEXT = {
    "limited": "Seizure detection is LIMITED until this is fixed.",
    "weaker": "Seizure detection may be weaker until this is fixed.",
    "backup": "Detection continues without movement (backup model).",
    "none": "Detection continues.",
}
WARNING_TEXT = {
    "headband_missing": "Headband is not sending data. Check that it is on, worn and charged.",
    "brain_weak": "Brain signal is weak. Adjust the headband so the sensors touch the skin.",
    "head_mov_missing": "Headband movement sensor is not sending data. Restart the headband.",
    "watch_missing": "Watch is not sending data. Check that it is worn and charged.",
    "heart_missing": "Heart rate is not measured. Tighten the watch strap.",
    "body_mov_missing": "Watch movement sensor is not sending data. Restart the watch.",
}


def impact_code(signals: set[str], other_bad: set[str]) -> str:
    bad = signals | other_bad
    if "brain" in bad:
        return "limited"
    if "heart" in bad:
        return "weaker"
    if {"head_mov", "body_mov"} <= bad:
        return "backup"
    return "none"


def warning_code(device: str, signals: set[str], problem: str) -> str:
    if device == "headband":
        if problem == "missing" and signals == {"brain", "head_mov"}:
            return "headband_missing"
        return "brain_weak" if "brain" in signals else "head_mov_missing"
    if problem == "missing" and signals == {"heart", "body_mov"}:
        return "watch_missing"
    return "heart_missing" if "heart" in signals else "body_mov_missing"


def impact(signals: set[str], other_bad: set[str]) -> str:
    return IMPACT_TEXT[impact_code(signals, other_bad)]


def advice(device: str, signals: set[str], problem: str) -> str:
    return WARNING_TEXT[warning_code(device, signals, problem)]


@dataclass
class Episode:
    device: str
    bad_from_s: float
    warned_s: float
    signals: set[str]
    problem: str               # missing | poor
    message: str
    impact: str
    reminders: list[float] = field(default_factory=list)
    fixed_s: float | None = None
    code: str = ""             # warning code sent to the watch
    impact_code: str = "none"


def _busy_mask(n: int, busy: list[tuple[float, float]]) -> np.ndarray:
    m = np.zeros(n, bool)
    for a, b in busy:
        m[max(0, int(a // W)):min(n, int(np.ceil(b / W)))] = True
    return m


def monitor(q: dict[str, np.ndarray], busy: list[tuple[float, float]] = ()) -> list[Episode]:
    """Replay the windows in time order as the phone would. busy = alarm/recovery intervals."""
    n = len(next(iter(q.values())))
    busy_m = _busy_mask(n, list(busy))
    out: list[Episode] = []
    for dev, sigs in DEVICES.items():
        keys = [k for k, _ in sigs]
        others = [k for d, s in DEVICES.items() if d != dev for k, _ in s]
        bad = np.zeros(n, bool)
        for k in keys:
            bad |= q[k] != OK
        csum = np.concatenate([[0], np.cumsum(bad)])
        ep: Episode | None = None
        pending = False
        good_run = 0
        i = BAD_WIN - 1
        while i < n:
            frac = (csum[i + 1] - csum[i + 1 - BAD_WIN]) / BAD_WIN
            t = (i + 1) * W
            if ep is None:
                if frac >= BAD_FRAC or pending:
                    if busy_m[i]:
                        pending = True
                    else:
                        pending = False
                        lo = i + 1 - BAD_WIN
                        sig = {k for k in keys if (q[k][lo:i + 1] != OK).mean() >= 0.5} or \
                              {k for k in keys if (q[k][lo:i + 1] != OK).any()}
                        if not sig:      # pending warning but the problem is already gone
                            i += 1
                            continue
                        miss = all((q[k][lo:i + 1] == MISSING).mean() >= 0.5 for k in sig)
                        problem = "missing" if miss else "poor"
                        other_bad = {k for k in others if (q[k][lo:i + 1] != OK).mean() >= 0.5}
                        ep = Episode(dev, lo * W, t, sig, problem, advice(dev, sig, problem),
                                     impact(sig, other_bad), code=warning_code(dev, sig, problem),
                                     impact_code=impact_code(sig, other_bad))
                        good_run = 0
            else:
                good_run = 0 if bad[i] else good_run + 1
                if good_run >= GOOD_WIN:
                    ep.fixed_s = t
                    out.append(ep)
                    ep = None
                elif not busy_m[i] and t - (ep.reminders[-1] if ep.reminders else ep.warned_s) >= \
                        REMIND_S[min(len(ep.reminders), len(REMIND_S) - 1)]:
                    ep.reminders.append(t)
            i += 1
        if ep is not None:
            out.append(ep)
    return sorted(out, key=lambda e: e.warned_s)


def usable_share(q: dict[str, np.ndarray]) -> dict[str, float]:
    return {k: float(np.mean(v == OK)) for k, v in q.items()}


def main(argv=None):
    """Warning statistics over all SeizeIT2 patients (how often would the watch vibrate?)."""
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path("epiprot_results/gbm/tc5s"))
    ap.add_argument("--out", type=Path, default=Path("epiprot_results/app_demo/sensor_health_all.json"))
    a = ap.parse_args(argv)
    rows, hours = [], 0.0
    for p in sorted(a.data_dir.glob("sub-*.npz")):
        z = np.load(p)
        q = window_quality(z["F"], [str(x) for x in z["names"]])
        h = len(z["F"]) * W / 3600
        hours += h
        eps = monitor(q)
        rows.append({"sub": p.stem, "hours": h, "usable": usable_share(q),
                     "warnings": len(eps), "reminders": sum(len(e.reminders) for e in eps),
                     "by_device": {d: sum(e.device == d for e in eps) for d in DEVICES},
                     "by_problem": {k: sum(e.problem == k for e in eps) for k in ("missing", "poor")},
                     "minutes_to_fix": [((e.fixed_s or len(z["F"]) * W) - e.bad_from_s) / 60 for e in eps]})
    w = np.array([r["warnings"] for r in rows])
    per_day = w / np.array([r["hours"] for r in rows]) * 24
    fix = np.concatenate([r["minutes_to_fix"] for r in rows]) if w.sum() else np.array([0.0])
    summ = {"patients": len(rows), "hours": hours, "warnings": int(w.sum()),
            "warnings_per_day_overall": float(w.sum() / hours * 24),
            "warnings_per_day_median_patient": float(np.median(per_day)),
            "patients_with_no_warning": int((w == 0).sum()),
            "reminders": int(sum(r["reminders"] for r in rows)),
            "by_device": {d: int(sum(r["by_device"][d] for r in rows)) for d in DEVICES},
            "by_problem": {k: int(sum(r["by_problem"][k] for r in rows)) for k in ("missing", "poor")},
            "problem_minutes_median": float(np.median(fix)), "problem_minutes_iqr": np.percentile(fix, [25, 75]).tolist(),
            "usable_mean": {k: float(np.average([r["usable"][k] for r in rows], weights=[r["hours"] for r in rows]))
                            for k in rows[0]["usable"]}}
    print(json.dumps(summ, indent=1))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"summary": summ, "patients": rows}, indent=1))


if __name__ == "__main__":
    main()

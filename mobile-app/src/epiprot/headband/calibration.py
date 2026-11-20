"""Movement units of SeizeIT2 vs. real units, measured from the data itself.

SeizeIT2 labels the "EEG SD" (back of the neck) accelerometer and gyroscope as "g", but the values
are scaled. Two device settings exist, a factor 3 apart for BOTH sensors:

  group A: 1 g = 0.50 units,  1 unit = ~365 °/s   (29 patients,  5 of the 55 tonic-clonic seizures)
  group B: 1 g = 0.167 units, 1 unit = ~1016 °/s  (75 patients, 43 of the 55 tonic-clonic seizures)
  10 patients have broken accelerometer data (4 seizures), 11 have no movement file (3 seizures).
  Gyroscope values: median over patients (IQR A 349-388, B 954-1052 °/s per unit).

The accelerometer scale comes from gravity (median |acc| at rest = 1 g). The gyroscope scale comes
from comparing how fast the gravity direction turns (seen by the accelerometer, in rad/s) with the
gyroscope reading perpendicular to gravity, during slow head movements.

The headband feeds the model in group-B units: that is where the model saw almost all of the
tonic-clonic seizures it learned from.

Usage: python -m epiprot.headband.calibration --raw-dir C:/Veri/SeizeIT2 [--out table.csv]
"""
from __future__ import annotations

import argparse
import glob
import os
from dataclasses import dataclass

import numpy as np

from .edf import read_edf


@dataclass(frozen=True)
class Seizeit2Scale:
    units_per_g: float
    units_per_dps: float


GROUP_A = Seizeit2Scale(units_per_g=0.5, units_per_dps=1 / 365)
GROUP_B = Seizeit2Scale(units_per_g=1 / 6, units_per_dps=1 / 1016)
TRAINING = GROUP_B


def group_of(acc_units: np.ndarray) -> Seizeit2Scale | None:
    """Scale group from the accelerometer magnitude at rest (acc_units: 3 x n). None = broken."""
    m = float(np.median(np.sqrt((acc_units ** 2).sum(0))))
    if 0.4 < m < 0.6:
        return GROUP_A
    if 0.13 < m < 0.2:
        return GROUP_B
    return None


def _smooth(x: np.ndarray, k: int) -> np.ndarray:
    c = np.cumsum(np.insert(x, 0, 0.0))
    y = (c[k:] - c[:-k]) / k
    pad = len(x) - len(y)
    return np.concatenate([np.full(pad // 2, y[0]), y, np.full(pad - pad // 2, y[-1])])


def gyro_units_per_rad_s(acc: np.ndarray, gyr: np.ndarray, fs: float = 25.0) -> tuple[float, int]:
    """Gyroscope units per rad/s from gravity-direction rotation. Returns (scale, samples used)."""
    k = max(1, int(fs / 2))
    a = np.stack([_smooth(v, k) for v in acc])
    g = np.stack([_smooth(v, k) for v in gyr])
    g = g - np.median(g, 1, keepdims=True)
    n = np.linalg.norm(a, axis=0)
    u = a / np.maximum(n, 1e-9)
    du = np.gradient(u, axis=1) * fs
    w_acc = np.linalg.norm(np.cross(u.T, du.T), axis=1)
    w_gyr = np.linalg.norm(g - (g * u).sum(0) * u, axis=0)
    ok = (np.abs(n - np.median(n)) < 0.03 * np.median(n)) & (w_acc > 0.2) & (w_acc < 3)
    if ok.sum() < 200:
        return float("nan"), int(ok.sum())
    return float(np.median(w_gyr[ok] / w_acc[ok])), int(ok.sum())


def survey(raw_dir: str, max_runs: int = 3) -> list[dict]:
    rows = []
    for sub in sorted(glob.glob(os.path.join(raw_dir, "sub-*"))):
        movs = sorted(glob.glob(os.path.join(sub, "ses-01", "mov", "*_mov.edf")))[:max_runs]
        acc_mag, scales = [], []
        for p in movs:
            e = read_edf(p)
            L = e["labels"]
            ai = [i for i, l in enumerate(L) if l.startswith("EEG SD ACC")]
            gi = [i for i, l in enumerate(L) if l.startswith("EEG SD GYR")]
            if len(ai) != 3:
                continue
            acc = np.stack([e["signals"][i] for i in ai])
            acc_mag.append(float(np.median(np.sqrt((acc ** 2).sum(0)))))
            if len(gi) == 3:
                s, used = gyro_units_per_rad_s(acc, np.stack([e["signals"][i] for i in gi]))
                if np.isfinite(s):
                    scales.append(s)
        if not acc_mag:
            continue
        m = float(np.median(acc_mag))
        grp = "A" if 0.4 < m < 0.6 else ("B" if 0.13 < m < 0.2 else "broken")
        dps = 57.2958 / float(np.median(scales)) if scales else float("nan")
        rows.append({"sub": os.path.basename(sub), "acc_units_per_g": m, "group": grp, "deg_s_per_unit": dps})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rows = survey(a.raw_dir)
    for grp in ("A", "B", "broken"):
        r = [x for x in rows if x["group"] == grp]
        d = [x["deg_s_per_unit"] for x in r if np.isfinite(x["deg_s_per_unit"])]
        acc = [x["acc_units_per_g"] for x in r]
        print(f"group {grp}: {len(r)} patients, 1 g = {np.median(acc):.3f} units"
              + (f", 1 unit = {np.median(d):.0f} °/s (IQR {np.percentile(d, 25):.0f}-{np.percentile(d, 75):.0f}, n={len(d)})" if d else ""))
    if a.out:
        with open(a.out, "w") as f:
            f.write("sub,group,acc_units_per_g,deg_s_per_unit\n")
            for x in rows:
                f.write(f"{x['sub']},{x['group']},{x['acc_units_per_g']:.4f},{x['deg_s_per_unit']:.1f}\n")


if __name__ == "__main__":
    main()

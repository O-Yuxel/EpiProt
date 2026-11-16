"""CHB-MIT: 30 s window feature matrices on a continuous per-patient timeline.

The raw CHB-MIT EDFs are no longer on disk, but the old pipeline left per-patient
10 s x channel feature tables (epiprot_results/per_patient/chbXX/feature_table.csv) for
8 patients (chb01, 02, 03, 05, 08, 09, 10, 13) plus seizure annotations.

Per patient:
  * files ordered chronologically (chbXX_NN, then chbXX_NN+), concatenated back-to-back
    (the clock gaps between files are unknown without the summary files -> small
    timeline approximation)
  * three 10 s windows -> one 30 s window (mean), per channel:
    log band powers, relative band powers, line length, Hjorth, entropy, centroid...
  * seizures converted to (onset_idx, end_idx) 30 s window indices

Output: epiprot_results/gbm/chb/chbXX.npz with F (N, D) float32 (NaN = missing), names,
seizures (k, 2).

Usage: python -m epiprot.gbm.chb_features --in-dir epiprot_results/per_patient \
           --out-dir epiprot_results/gbm/chb
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

WIN = 30.0
LOG_COLS = ["time_std_uv", "time_line_length_uv", "freq_total_uv2", "freq_delta_abs_uv2",
            "freq_theta_abs_uv2", "freq_alpha_abs_uv2", "freq_beta_abs_uv2",
            "freq_gamma_abs_uv2"]
LIN_COLS = ["time_zero_crossing_rate", "freq_delta_rel", "freq_theta_rel", "freq_alpha_rel",
            "freq_beta_rel", "freq_gamma_rel", "freq_spectral_centroid_hz",
            "complex_shannon_entropy_bits", "complex_hjorth_mobility",
            "complex_hjorth_complexity"]

# annotation-parser errors in the old pipeline, corrected from the CHB-MIT summary files
FIXES = {"chb09": [("chb09_06.edf", 12231, 12295), ("chb09_08.edf", 2951, 3030),
                   ("chb09_08.edf", 9196, 9267), ("chb09_19.edf", 5299, 5361)]}


def _file_key(name: str):
    m = re.search(r"_(\d+)(\+?)\.edf$", name)
    return int(m.group(1)), m.group(2) == "+"


def build(pdir: Path) -> dict:
    pid = pdir.name
    audit = pd.read_csv(pdir / "data_audit.csv")
    audit["file"] = audit["edf_path"].map(lambda p: Path(p).name)
    audit = audit[audit["edf_ok"].astype(str) == "True"]
    files = sorted(audit["file"], key=_file_key)
    dur = dict(zip(audit["file"], audit["duration_s"]))
    offset, start = 0, {}
    for f in files:
        start[f] = offset
        offset += int(dur[f] // WIN)
    n = offset

    cols = ["edf_path", "channel", "window_start_s"] + LOG_COLS + LIN_COLS
    df = pd.read_csv(pdir / "feature_table.csv", usecols=cols)
    df["file"] = df["edf_path"].map(lambda p: Path(p).name)
    df = df[df["file"].isin(start)]
    for c in LOG_COLS:
        df[c] = np.log10(np.maximum(df[c].astype(float), 1e-6))
    df["w"] = df["file"].map(start) + (df["window_start_s"] // WIN).astype(int)
    df = df[df["w"] < n]
    # channels present in >= 90 % of files
    ch_files = df.groupby("channel")["file"].nunique()
    chans = sorted(ch_files[ch_files >= 0.9 * len(files)].index)
    df = df[df["channel"].isin(chans)]
    g = df.groupby(["w", "channel"])[LOG_COLS + LIN_COLS].mean().unstack("channel")
    feats = LOG_COLS + LIN_COLS
    F = np.full((n, len(feats) * len(chans)), np.nan, np.float32)
    names = []
    j = 0
    for c in feats:
        for ch in chans:
            if (c, ch) in g.columns:
                F[g.index.values, j] = g[(c, ch)].values
            names.append(f"{c}|{ch}")
            j += 1
    # channel-averaged versions (robust to single bad channels)
    avg = np.stack([np.nanmean(F[:, i * len(chans):(i + 1) * len(chans)], axis=1)
                    for i in range(len(feats))], axis=1)
    F = np.hstack([F, avg.astype(np.float32)])
    names += [f"{c}|mean" for c in feats]

    if pid in FIXES:
        sz_rows = FIXES[pid]
    else:
        ann = pd.read_csv(pdir / "seizure_annotations.csv")
        sz_rows = list(zip(ann["edf_filename"], ann["seizure_start_s"], ann["seizure_end_s"]))
    seizures = []
    for f, s0, s1 in sz_rows:
        if f not in start:
            continue
        on = start[f] + int(s0 // WIN)
        end = start[f] + int(np.ceil(s1 / WIN))
        seizures.append((on, max(end, on + 1)))
    seizures.sort()
    return {"pid": pid, "F": F, "names": np.array(names), "seizures": np.array(seizures),
            "n_files": len(files), "channels": chans}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    for pdir in sorted(a.in_dir.glob("chb*")):
        d = build(pdir)
        np.savez(a.out_dir / f"{d['pid']}.npz", F=d["F"], names=d["names"],
                 seizures=d["seizures"])
        miss = float(np.isnan(d["F"][:, -1]).mean())
        print(f"{d['pid']}: {d['n_files']} files, {len(d['F'])} windows "
              f"({len(d['F']) / 120:.1f} h), {d['F'].shape[1]} features, "
              f"{len(d['channels'])} channels, {len(d['seizures'])} seizures, "
              f"missing {miss:.1%}", flush=True)


if __name__ == "__main__":
    main()

"""Run a SeizeIT2 recording through the virtual headband and back through the phone receiver,
and check that the model sees the same data.

  SeizeIT2 signal -> headband hardware model -> Bluetooth packets -> stream file (.ehb)
                  -> phone receiver -> µV / SeizeIT2 movement units -> model features

Usage (default: 10 min before to 5 min after the patient's first tonic-clonic seizure):
  python -m epiprot.headband.simulate --raw-dir C:/Veri/SeizeIT2 --sub sub-115 \
      --out epiprot_results/headband/sub-115
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from . import protocol as P
from .device import EEG_FS, MOV_FS, HardwareConfig, load_source, read_stream, seizure_runs, simulate, write_stream
from .phone import Receiver

W = 5.0


def _window_mean_removed(x: np.ndarray, m: int) -> np.ndarray:
    n = len(x) // m
    s = x[: n * m].reshape(n, m)
    return s - np.nanmean(s, 1, keepdims=True)


def compare_features(src, eeg_uv, first, mov, pair, n_win):
    """Model features (tc_features) from the original SeizeIT2 data and from what the phone received."""
    from epiprot.gbm import tc_features as TF
    labels = list(src.eeg_uv)
    x_src = np.stack([src.eeg_uv[labels[0]], src.eeg_uv[labels[1]]]) / 1e6           # SeizeIT2 order
    x_hb = np.stack([eeg_uv[pair[0] - 1], eeg_uv[pair[1] - 1]]) / 1e6                  # headband channels
    f_src, names = TF.eeg_feats(x_src, EEG_FS, n_win)
    f_hb, _ = TF.eeg_feats(x_hb, EEG_FS, n_win)
    out = {}
    if src.acc is not None:
        chs = [f"EEG SD ACC {c}" for c in "XYZ"] + [f"EEG SD GYR {c}" for c in "ABC"]
        ms, mnames = TF.mov_feats(np.vstack([src.acc, src.gyr]), MOV_FS, chs, n_win)
        mh, _ = TF.mov_feats(mov, MOV_FS, chs, n_win)
        keep = [i for i, n in enumerate(mnames) if n.startswith("head")]
        f_src += [ms[i] for i in keep]; f_hb += [mh[i] for i in keep]; names += [mnames[i] for i in keep]
    for n, a, b in zip(names, f_src, f_hb):
        a, b = np.asarray(a, float), np.asarray(b, float)
        ok = np.isfinite(a) & np.isfinite(b)
        spread = float(np.nanstd(a)) or 1.0
        d = np.abs(a[ok] - b[ok])
        out[n] = {"max_abs_diff": float(d.max()) if d.size else None,
                  "median_abs_diff": float(np.median(d)) if d.size else None,
                  "max_diff_vs_feature_spread": float(d.max() / spread) if d.size else None}
    return out


def run(raw_dir, sub, out_dir, run_no=None, start_s=None, dur_s=None, cfg=HardwareConfig()):
    if run_no is None:
        sz = seizure_runs(raw_dir, sub)
        if not sz:
            raise SystemExit(f"{sub}: no tonic-clonic seizure")
        run_no, onset, _ = sz[0]
        start_s = max(0.0, onset - 600) if start_s is None else start_s
        dur_s = 900.0 if dur_s is None else dur_s
    src = load_source(raw_dir, sub, run_no, start_s, dur_s)
    records, meta = simulate(src, cfg)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stream = out_dir / f"{sub}_run-{run_no:02d}.ehb"
    write_stream(stream, records, meta)

    # ---- phone side: read the file back as the app would receive it
    recs, meta = read_stream(stream)
    rx = Receiver(bytes.fromhex(meta["device_info"]))
    for ms, b in recs:
        rx.feed(ms, b)
    first, eeg = rx.eeg_uv()
    n = eeg.shape[1]
    n_mov = int(n / EEG_FS * MOV_FS)
    mov = rx.movement(n_mov, first)
    span_s = (recs[-1][0] - recs[0][0]) / 1000

    # ---- checks
    rep = {"stream": str(stream), "packets": len(recs), "bytes_per_s": sum(len(b) for _, b in recs) / span_s,
           "missing_packets": len(rx.missing_seq()), "source_map": meta["source_map"],
           "training_pair": meta["training_pair"], "movement_scale": meta["movement"]}
    m = int(W * EEG_FS)
    for ch, lab in zip(meta["training_pair"], list(src.eeg_uv)[:2]):
        a = _window_mean_removed(src.eeg_uv[lab][:n], m)
        b = _window_mean_removed(eeg[ch - 1], m)
        d = (b - a)[np.isfinite(b - a)]
        rep[f"eeg_ch{ch}_vs_{lab}"] = {"rms_error_uV": float(np.sqrt(np.mean(d ** 2))),
                                       "max_error_uV": float(np.abs(d).max()),
                                       "signal_rms_uV": float(np.nanstd(a))}
    if src.acc is not None:
        ref = np.vstack([src.acc, src.gyr])[:, :n_mov] / np.array(
            [meta["movement"]["units_per_g"]] * 3 + [meta["movement"]["units_per_dps"]] * 3)[:, None]
        from .calibration import TRAINING
        got = mov / np.array([TRAINING.units_per_g] * 3 + [TRAINING.units_per_dps] * 3)[:, None]
        ok = np.isfinite(got).all(0)
        d = got[:, ok] - ref[:, ok]
        rep["movement"] = {"acc_rms_error_g": float(np.sqrt(np.mean(d[:3] ** 2))),
                           "acc_signal_rms_g": float(np.std(ref[:3, ok])),
                           "gyr_rms_error_dps": float(np.sqrt(np.mean(d[3:] ** 2))),
                           "gyr_signal_rms_dps": float(np.std(ref[3:, ok])),
                           "covered_fraction": float(ok.mean())}
    a, b = rx.phone_clock()
    rep["phone_clock"] = {"drift_ppm": (a / 1000 - 1) * 1e6}
    # truth: packet ready time -> its arrival can only be later; check the fitted line never sits above it
    td = np.array([rx.t_dev[s] for s in sorted(rx.arrival)], float) / P.TICKS_PER_S
    lag = np.array([rx.arrival[s] for s in sorted(rx.arrival)]) - (a * td + b)
    rep["phone_clock"]["arrival_minus_fit_ms"] = {"min": float(lag.min()), "median": float(np.median(lag)),
                                                  "max": float(lag.max())}
    try:
        src.eeg_uv = {k: v[:n] for k, v in src.eeg_uv.items()}
        rep["features"] = compare_features(src, eeg, first, mov, meta["training_pair"], int(n // m))
    except ImportError as e:
        rep["features"] = f"skipped ({e})"
    (out_dir / f"{sub}_run-{run_no:02d}_check.json").write_text(json.dumps(rep, indent=1))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--sub", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run", type=int)
    ap.add_argument("--start-s", type=float)
    ap.add_argument("--dur-s", type=float)
    a = ap.parse_args(argv)
    rep = run(a.raw_dir, a.sub, a.out, a.run, a.start_s, a.dur_s)
    feats = rep.pop("features")
    print(json.dumps(rep, indent=1))
    if isinstance(feats, dict):
        worst = sorted(feats.items(), key=lambda kv: -(kv[1]["max_diff_vs_feature_spread"] or 0))[:8]
        print("largest feature differences (max |diff| / feature spread):")
        for k, v in worst:
            print(f"  {k:22s} {v['max_diff_vs_feature_spread']:.4f}  (median |diff| {v['median_abs_diff']:.2e})")
    else:
        print("features:", feats)


if __name__ == "__main__":
    main()

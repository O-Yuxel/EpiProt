"""5-second window features from ALL SeizeIT2 wearable sensors, for fast tonic-clonic
(big convulsive seizure) detection.

Sensors per run (numeric run order = chronological):
  eeg : BTEleft, CROSStop (256 Hz)  -> line length, RMS, band powers
  ecg : 256 Hz                       -> heart rate from R-peaks
  emg : 256 Hz                       -> RMS, high-frequency power, line length, ZCR
  mov : 25 Hz, two devices (head = "EEG SD", body patch = "ECGEMG SD"), ACC xyz + GYR xyz
        -> movement intensity, power in the 3-8 Hz "clonic jerk" band, rhythmicity

Windows: non-overlapping 5 s, floor(recordingDuration / 5) per run, runs back-to-back.
Missing sensors / files -> NaN.

Output epiprot_results/gbm/tc5s/sub-XXX.npz: F (N, D) float32, names, seizures (k, 2)
window indices [onset, end), sz_type (k,), sz_onset_s (k,) exact onset seconds on the
concatenated timeline, sz_dur_s (k,).

Usage: python -m epiprot.gbm.tc_features --raw-dir /raw --out-dir epiprot_results/gbm/tc5s
"""
from __future__ import annotations

import argparse
import csv
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from .hrv import r_peaks

W = 5.0
EEG_BANDS = {"delta": (1, 4), "theta": (4, 8), "alpha": (8, 13), "beta": (13, 30),
             "gamma": (30, 60)}


def _run_num(p: Path) -> int:
    return int(re.search(r"run-(\d+)", p.name).group(1))


def _read(path: Path):
    import mne
    if not path.exists():
        return None, None, None
    try:
        r = mne.io.read_raw_edf(str(path), preload=True, verbose="ERROR")
        x = r.get_data().astype(np.float32)
        fs = r.info["sfreq"]
        names = r.ch_names
        r.close()
        return x, fs, names
    except Exception as e:  # corrupt file
        print(f"  {path.name}: {e}", flush=True)
        return None, None, None


def _windows(x, fs, n):
    m = int(round(W * fs))
    x = x[: n * m]
    if len(x) < n * m:
        x = np.pad(x, (0, n * m - len(x)), constant_values=np.nan)
    return x.reshape(n, m)


def _bandpow(seg, fs, lo, hi):
    f = np.fft.rfftfreq(seg.shape[1], 1 / fs)
    p = np.abs(np.fft.rfft(np.nan_to_num(seg - np.nanmean(seg, 1, keepdims=True)), axis=1)) ** 2
    sel = (f >= lo) & (f < hi)
    return np.log10(p[:, sel].sum(1) / seg.shape[1] + 1e-12)


def eeg_feats(x, fs, n):
    out, names = [], []
    for ci, ch in enumerate(["L", "X"]):
        seg = _windows(x[ci] * 1e6, fs, n)
        out += [np.log10(np.nanmean(np.abs(np.diff(seg, axis=1)), 1) + 1e-6),
                np.log10(np.nanstd(seg, 1) + 1e-6)]
        names += [f"eeg{ch}_ll", f"eeg{ch}_rms"]
        for b, (lo, hi) in EEG_BANDS.items():
            out.append(_bandpow(seg, fs, lo, hi))
            names.append(f"eeg{ch}_{b}")
    return out, names


def ecg_feats(x, fs, n):
    hr = np.full(n, np.nan, np.float32)
    try:
        pk = r_peaks(x[0].astype(np.float64), fs)
    except Exception:
        pk = np.array([], int)
    if len(pk) > 2:
        t = pk / fs
        rr = np.diff(t)
        ok = (rr > 0.3) & (rr < 2.0)
        w = (t[1:] // W).astype(int)
        for i in range(n):
            lo, hi = np.searchsorted(w, [i, i + 1])
            r = rr[lo:hi][ok[lo:hi]]
            if len(r) >= 2:
                hr[i] = 60.0 / np.median(r)
    return [hr], ["ecg_hr"]


def emg_feats(x, fs, n):
    seg = _windows(x[0] * 1e6, fs, n)
    zc = np.nanmean(np.abs(np.diff(np.sign(seg - np.nanmean(seg, 1, keepdims=True)), axis=1)) > 0, 1)
    return ([np.log10(np.nanstd(seg, 1) + 1e-6),
             np.log10(np.nanmean(np.abs(np.diff(seg, axis=1)), 1) + 1e-6),
             _bandpow(seg, fs, 20, 60), _bandpow(seg, fs, 60, min(120, fs / 2 - 1)), zc],
            ["emg_rms", "emg_ll", "emg_p20_60", "emg_p60_120", "emg_zcr"])


def mov_feats(x, fs, chs, n):
    out, names = [], []
    for dev, tag in (("EEG SD", "head"), ("ECGEMG SD", "body")):
        for kind in ("ACC", "GYR"):
            idx = [i for i, c in enumerate(chs) if c.startswith(dev + " " + kind)]
            pre = f"{tag}_{kind.lower()}"
            cols = [f"{pre}_std", f"{pre}_p0_3", f"{pre}_p3_8", f"{pre}_p8_12", f"{pre}_rhythm"]
            if len(idx) != 3:
                out += [np.full(n, np.nan, np.float32)] * len(cols)
                names += cols
                continue
            mag = np.sqrt((x[idx].astype(np.float64) ** 2).sum(0))
            seg = _windows(mag, fs, n)
            d = seg - np.nanmean(seg, 1, keepdims=True)
            d = np.nan_to_num(d)
            spec = np.fft.rfft(d, n=2 * d.shape[1], axis=1)
            ac = np.fft.irfft(np.abs(spec) ** 2, axis=1)[:, : d.shape[1]]
            lo, hi = int(fs / 8), int(fs / 2)  # lags for 2-8 Hz rhythms
            rhythm = ac[:, lo:hi + 1].max(1) / (ac[:, 0] + 1e-12)
            out += [np.log10(np.nanstd(seg, 1) + 1e-6), _bandpow(seg, fs, 0.3, 3),
                    _bandpow(seg, fs, 3, 8), _bandpow(seg, fs, 8, 12.4), rhythm]
            names += cols
    return out, names


def process(raw_dir: Path, sub: str, out_dir: Path):
    t0 = time.time()
    dst = out_dir / f"{sub}.npz"
    if dst.exists():
        return sub, -1, 0.0
    base = raw_dir / sub / "ses-01"
    tsvs = sorted((base / "eeg").glob("*_events.tsv"), key=_run_num)
    blocks, names, sz, types, on_s, dur_s = [], None, [], [], [], []
    pos = 0
    for tsv in tsvs:
        with open(tsv, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        n = int((float(rows[0]["recordingDuration"]) if rows else 0.0) // W)
        if n <= 0:
            continue
        stem = tsv.name.replace("_events.tsv", "")
        feats, fn = [], []
        x, fs, _ = _read(base / "eeg" / f"{stem}_eeg.edf")
        if x is not None and x.shape[0] >= 2:
            f, nm = eeg_feats(x, fs, n)
        else:
            f, nm = eeg_feats(np.full((2, int(n * W * 256)), np.nan, np.float32), 256.0, n)
        feats += f; fn += nm
        del x
        x, fs, _ = _read(base / "ecg" / f"{stem}_ecg.edf")
        f, nm = ecg_feats(x, fs, n) if x is not None else ([np.full(n, np.nan, np.float32)], ["ecg_hr"])
        feats += f; fn += nm
        del x
        x, fs, _ = _read(base / "emg" / f"{stem}_emg.edf")
        if x is not None:
            f, nm = emg_feats(x, fs, n)
        else:
            f, nm = emg_feats(np.full((1, int(n * W * 256)), np.nan, np.float32), 256.0, n)
        feats += f; fn += nm
        del x
        x, fs, chs = _read(base / "mov" / f"{stem}_mov.edf")
        f, nm = mov_feats(x, fs, chs, n) if x is not None else mov_feats(
            np.full((0, int(n * W * 25)), np.nan, np.float32), 25.0, [], n)
        feats += f; fn += nm
        del x
        blocks.append(np.stack([np.asarray(v, np.float32)[:n] for v in feats], 1))
        names = fn
        for r in rows:
            if r["eventType"].lower().startswith("sz"):
                o, d = float(r["onset"]), float(r["duration"])
                a = pos + int(o // W)
                b = pos + int(np.ceil((o + d) / W))
                if a < pos + n:
                    sz.append((a, min(max(b, a + 1), pos + n)))
                    types.append(r["eventType"])
                    on_s.append(pos * W + o)
                    dur_s.append(d)
        pos += n
    F = np.vstack(blocks).astype(np.float32)
    order = np.argsort([s[0] for s in sz], kind="stable")
    tmp = out_dir / f"{sub}.tmp.npz"
    np.savez(tmp, F=F, names=np.array(names),
             seizures=np.array([sz[i] for i in order], np.int64).reshape(-1, 2),
             sz_type=np.array([types[i] for i in order]),
             sz_onset_s=np.array([on_s[i] for i in order]),
             sz_dur_s=np.array([dur_s[i] for i in order]))
    tmp.replace(dst)
    return sub, len(F), time.time() - t0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--subs", nargs="*", default=None)
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    subs = a.subs or sorted(p.name for p in a.raw_dir.glob("sub-*") if p.is_dir())
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(process, a.raw_dir, s, a.out_dir) for s in subs]
        for i, f in enumerate(as_completed(futs), 1):
            s, n, dt = f.result()
            print(f"[{i}/{len(subs)}] {s}: {'skip' if n < 0 else f'{n} windows in {dt:.0f}s'} "
                  f"| {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

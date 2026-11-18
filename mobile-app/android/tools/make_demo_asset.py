"""Demo recording for the phone app: raw signals of one real tonic-clonic seizure from SeizeIT2.

The app replays it as if it came from the headband and the watch (no hardware needed):
  EEG (2 channels, 256 Hz, uV) and back movement  -> as from the headband
  chest movement and heart rate (from the ECG)    -> as from the watch
From 10 min before to 5 min after the onset, inside one recording run.

Binary layout (little endian):
  u32 header length | header JSON (utf-8)
  per window: 2 x 1280 f32 EEG, then 12 x 125 f32 movement
              (head_acc x,y,z, head_gyr a,b,c, body_acc x,y,z, body_gyr a,b,c)

Usage: python mobile-app/android/tools/make_demo_asset.py --raw-dir /raw --sub sub-115 \
           --out mobile-app/android/app/src/main/assets/demo/demo_seizure.bin
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
from pathlib import Path

import numpy as np

from epiprot.gbm import tc_detect as T
from epiprot.gbm import tc_features as TF

BEFORE, AFTER = 120, 60      # windows (10 min, 5 min)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--sub", default="sub-115")
    ap.add_argument("--data-dir", type=Path, default=Path("epiprot_results/gbm/tc5s"))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    z = np.load(a.data_dir / f"{a.sub}.npz")
    names = [str(x) for x in z["names"]]
    hr_all = z["F"][:, names.index("ecg_hr")]

    base = a.raw_dir / a.sub / "ses-01"
    tsvs = sorted((base / "eeg").glob("*_events.tsv"), key=TF._run_num)
    pos = 0
    for tsv in tsvs:
        with open(tsv, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        n = int((float(rows[0]["recordingDuration"]) if rows else 0.0) // T.W)
        if n <= 0:
            continue
        for r in rows:
            if not (r["eventType"].lower().startswith("sz") and T.is_tc(r["eventType"])):
                continue
            onset = float(r["onset"])
            on_w = int(onset // T.W)
            if on_w - BEFORE < 0 or on_w + AFTER > n:
                continue
            stem = tsv.name.replace("_events.tsv", "")
            xe, fse, _ = TF._read(base / "eeg" / f"{stem}_eeg.edf")
            xm, fsm, chm = TF._read(base / "mov" / f"{stem}_mov.edf")
            if xe is None or xm is None:
                continue
            order = []
            for dev in ("EEG SD", "ECGEMG SD"):
                for kind in ("ACC", "GYR"):
                    order += [i for i, c in enumerate(chm) if c.startswith(dev + " " + kind)]
            assert len(order) == 12, chm
            w0, w1 = on_w - BEFORE, on_w + AFTER
            me, mm = int(T.W * fse), int(T.W * fsm)
            hdr = {"sub": a.sub, "type": r["eventType"], "windows": w1 - w0,
                   "onset_s": onset - w0 * T.W, "duration_s": float(r["duration"]),
                   "eeg_fs": fse, "mov_fs": fsm,
                   "heart_rate": [None if not np.isfinite(v) else float(v) for v in hr_all[pos + w0:pos + w1]],
                   "source": "SeizeIT2 (EEG behind the ear; movement from the back and chest devices)"}
            hb = json.dumps(hdr).encode()
            a.out.parent.mkdir(parents=True, exist_ok=True)
            with open(a.out, "wb") as fh:
                fh.write(struct.pack("<I", len(hb)))
                fh.write(hb)
                for i in range(w0, w1):
                    fh.write((xe[:2, i * me:(i + 1) * me] * 1e6).astype("<f4").tobytes())
                    fh.write(xm[order, i * mm:(i + 1) * mm].astype("<f4").tobytes())
            print(f"{a.sub} {r['eventType']} onset {onset:.0f}s in {stem}: windows {w0}-{w1}, "
                  f"{a.out.stat().st_size / 1e6:.1f} MB")
            return
        pos += n
    raise SystemExit("no tonic-clonic seizure with 10 min before / 5 min after inside one run")


if __name__ == "__main__":
    main()

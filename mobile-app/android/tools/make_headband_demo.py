"""Virtual-headband demo for the phone app: a real tonic-clonic seizure from SeizeIT2 played through
the software copy of the designed headband (mobile-app/src/epiprot/headband).

sub-058 is used because its EEG montage (left behind-the-ear + cross-head) matches the headband's
standard channels 1 + 2 exactly. 10 min before to 5 min after the seizure onset. To show the status
screen working, the pad behind the right ear (lower) dries out during the demo (it is only used by
the backup channels, so detection is not affected) and contact checks run every 2 min instead of 10.

Writes app/src/main/assets/demo/headband_demo.ehb.
Usage (from mobile-app/android): PYTHONPATH=../src python tools/make_headband_demo.py --raw-dir C:/Veri/SeizeIT2
"""
from __future__ import annotations

import argparse
from pathlib import Path

from epiprot.headband import faults as F
from epiprot.headband.device import HardwareConfig, load_source, seizure_runs, simulate, write_stream

OUT = Path(__file__).resolve().parents[1] / "app" / "src" / "main" / "assets" / "demo" / "headband_demo.ehb"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--sub", default="sub-058")
    a = ap.parse_args()
    run, onset, dur = seizure_runs(a.raw_dir, a.sub)[0]
    src = load_source(a.raw_dir, a.sub, run, onset - 600, 900)
    src.meta.update({"onset_s": 600.0, "duration_s": dur, "demo": "virtual headband"})
    cfg = HardwareConfig(contact_check_every_s=120, start_battery_pct=64, seed=58)
    rec, meta = simulate(src, cfg, faults=[F.PadDrying("R-bottom", 60, 420, 840)])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_stream(OUT, rec, meta)
    print(f"{a.sub} run {run}: onset {onset:.0f} s, duration {dur:.0f} s; channels {meta['source_map']}; "
          f"{len(rec)} packets, {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

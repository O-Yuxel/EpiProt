"""Why the motion sensor clock is locked to the crystal (HARDWARE.md, D13): model features from the
original SeizeIT2 movement vs. what the phone receives, for a free-running sensor clock
(resampled or slotted on the phone) and a locked one.

Usage: python -m epiprot.headband.imu_clock_study --raw-dir /raw sub-115 sub-058
"""
import argparse

import numpy as np

from .device import HardwareConfig, load_source, seizure_runs, simulate
from .phone import Receiver
from .simulate import compare_features

CASES = [("free sensor clock + resampling", HardwareConfig(imu_locked=False), "interp"),
         ("free sensor clock + slots", HardwareConfig(imu_locked=False), "slot"),
         ("locked sensor clock + slots", HardwareConfig(imu_locked=True), "slot")]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("subs", nargs="+")
    a = ap.parse_args(argv)
    for sub in a.subs:
        r, on, _ = seizure_runs(a.raw_dir, sub)[0]
        for name, cfg, mode in CASES:
            src = load_source(a.raw_dir, sub, r, on - 600, 900)
            if src.acc is None:
                print(sub, "no movement data")
                break
            rec, meta = simulate(src, cfg)
            rx = Receiver(bytes.fromhex(meta["device_info"]))
            for ms, b in rec:
                rx.feed(ms, b)
            first, eeg = rx.eeg_uv()
            n = eeg.shape[1]
            mov = rx.movement(int(n / 256 * 25), first, mode=mode)
            src.eeg_uv = {k: v[:n] for k, v in src.eeg_uv.items()}
            f = compare_features(src, eeg, first, mov, meta["training_pair"], int(n // 1280))
            head = {k: v for k, v in f.items() if k.startswith("head")}
            worst = max((v["median_abs_diff"], k) for k, v in head.items())
            mx = max(v["max_diff_vs_feature_spread"] for v in head.values())
            print(f"{sub} {name:32s} movement features: worst median |diff| {worst[0]:.3f} ({worst[1]}), "
                  f"worst max/spread {mx:.3f}")


if __name__ == "__main__":
    main()

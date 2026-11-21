"""Headband stream fixture for the Android unit tests (cross-language parity with the Python simulator).

Makes app/src/test/resources/fixtures/headband.ehb (40 s of a synthetic headband stream with a short
disconnect, a pad falling off and contact checks) and headband_expected.json (what the Python reference
receiver, epiprot.headband.phone, reads from it).

Usage (from mobile-app/android): PYTHONPATH=../src python tools/make_headband_fixture.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from epiprot.headband import faults as F
from epiprot.headband import protocol as P
from epiprot.headband.calibration import GROUP_B
from epiprot.headband.device import HardwareConfig, Source, simulate, write_stream
from epiprot.headband.phone import Receiver

OUT = Path(__file__).resolve().parents[1] / "app" / "src" / "test" / "resources" / "fixtures"


def source(seconds=40, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * 256)) / 256
    eeg = {"BTEleft SD": 40 * np.sin(2 * np.pi * 7 * t) + rng.normal(0, 10, t.size),
           "CROSStop SD": 25 * np.sin(2 * np.pi * 3 * t + 1) + rng.normal(0, 10, t.size)}
    tm = np.arange(int(seconds * 25)) / 25
    acc_g = np.stack([0.1 * np.sin(2 * np.pi * 1 * tm), 0.3 * np.sin(2 * np.pi * 4 * tm), np.ones_like(tm)])
    gyr_dps = np.stack([50 * np.sin(2 * np.pi * 5 * tm), 20 * np.cos(2 * np.pi * 2 * tm), 5 + 0 * tm])
    return Source(eeg, acc_g * GROUP_B.units_per_g, gyr_dps * GROUP_B.units_per_dps, GROUP_B, meta={"sub": "fixture"})


def main():
    cfg = HardwareConfig(contact_check_every_s=20, seed=7)
    faults = [F.Disconnect(12, 4), F.ElectrodeOff("L-top", 25, 6)]
    rec, meta = simulate(source(), cfg, faults=faults)
    OUT.mkdir(parents=True, exist_ok=True)
    write_stream(OUT / "headband.ehb", rec, meta)

    rx = Receiver(bytes.fromhex(meta["device_info"]))
    for ms, b in rec:
        rx.feed(round(ms), b)
    first, eeg = rx.eeg_uv()
    raw = np.vstack([p.raw for p in sorted(rx.mov, key=lambda p: p.seq)]).astype(float)
    exp = {
        "packets": len(rec),
        "eeg_packets": len(rx.eeg), "mov_packets": len(rx.mov), "status_packets": len(rx.status),
        "contact_packets": len(rx.contact), "catch_up": rx.catchup, "duplicates": rx.duplicates,
        "missing_seq": rx.missing_seq(),
        "eeg_first_index": first, "eeg_samples": int(eeg.shape[1]),
        "eeg_nan": [int(np.isnan(c).sum()) for c in eeg],
        "eeg_sum_uv": [float(np.nansum(c)) for c in eeg],
        "eeg_abs_sum_uv": [float(np.nansum(np.abs(c))) for c in eeg],
        "acc_sum_g": (raw[:, :3] / P.DeviceInfo().acc_lsb_per_g).sum(0).tolist(),
        "gyr_sum_dps": (raw[:, 3:] / P.DeviceInfo().gyr_lsb_per_dps).sum(0).tolist(),
        "contact_kohm": [list(p.impedance_kohm) for p in rx.contact],
        "lead_off_packets": int(sum(1 for p in rx.eeg if p.lead_off)),
        "contact_check_packets": int(sum(1 for p in rx.eeg if p.flags & P.FLAG_CONTACT_CHECK)),
        "status_battery_pct_first_last": [rx.status[0].battery_pct, rx.status[-1].battery_pct],
        "info": {"eeg_lsb_nv": P.DeviceInfo().eeg_lsb_nv, "acc_lsb_per_g": P.DeviceInfo().acc_lsb_per_g,
                 "gyr_lsb_per_dps": P.DeviceInfo().gyr_lsb_per_dps, "minor": P.PROTOCOL_MINOR},
    }
    (OUT / "headband_expected.json").write_text(json.dumps(exp, indent=1))
    print(f"{len(rec)} packets, {(OUT / 'headband.ehb').stat().st_size / 1e3:.0f} kB; catch-up {rx.catchup}, "
          f"lead-off packets {exp['lead_off_packets']}, contact checks {len(rx.contact)}")


if __name__ == "__main__":
    main()

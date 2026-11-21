"""Virtual headband: packets match device-firmware/PROTOCOL.md, and data survive the trip
headband -> Bluetooth packets -> phone receiver."""
from __future__ import annotations

import numpy as np
import pytest

from epiprot.headband import protocol as P
from epiprot.headband.calibration import GROUP_B, gyro_units_per_rad_s
from epiprot.headband.device import HardwareConfig, Source, simulate
from epiprot.headband.phone import Receiver, lower_envelope_fit


def test_packet_sizes_match_spec():
    assert (P.EEG_SIZE, P.MOV_SIZE, P.STATUS_SIZE, P.INFO_SIZE) == (208, 71, 26, 28)


def test_eeg_packet_round_trip_including_24bit_limits():
    codes = np.arange(-32, 32, dtype=np.int32).reshape(16, 4) * 100_000
    codes[0] = [P.INT24_MIN, P.INT24_MAX, -1, 0]
    b = P.encode(P.EegPacket(seq=7, sample_index=2 ** 32 - 3, t_dev=123, codes=codes, lead_off=P.LEAD_RTOP))
    assert len(b) == P.EEG_SIZE
    p = P.decode(b)
    assert (p.seq, p.sample_index, p.t_dev, p.lead_off) == (7, 2 ** 32 - 3, 123, P.LEAD_RTOP)
    assert np.array_equal(p.codes, np.clip(codes, P.INT24_MIN, P.INT24_MAX))


def test_movement_and_status_round_trip():
    raw = np.array([[1, -2, 3, -32768, 32767, 0]] * 5, np.int16)
    p = P.decode(P.encode(P.MovPacket(9, 456, raw, flags=P.FLAG_CATCHUP)))
    assert np.array_equal(p.raw, raw) and p.flags == P.FLAG_CATCHUP and p.t_dev == 456
    s = P.StatusPacket(10, 789, 3950, 61, P.ST_STREAMING | P.ST_LOW_BATTERY, P.LEAD_BIAS, -5, 1234,
                       P.ERR_FLASH_FULL, 86400)
    assert P.decode(P.encode(s)) == s


def test_unknown_protocol_major_is_refused():
    b = bytearray(P.DeviceInfo().encode())
    b[0] = 2
    with pytest.raises(ValueError):
        P.DeviceInfo.decode(bytes(b))


def _synthetic_source(seconds=60, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * 256)) / 256
    eeg = {"BTEleft SD": 40 * np.sin(2 * np.pi * 7 * t) + rng.normal(0, 10, t.size),
           "CROSStop SD": 25 * np.sin(2 * np.pi * 3 * t + 1) + rng.normal(0, 10, t.size)}
    tm = np.arange(int(seconds * 25)) / 25
    acc_g = np.stack([np.zeros_like(tm), 0.3 * np.sin(2 * np.pi * 4 * tm), np.ones_like(tm)])
    gyr_dps = np.stack([50 * np.sin(2 * np.pi * 5 * tm), 20 * np.cos(2 * np.pi * 2 * tm), np.zeros_like(tm)])
    return Source(eeg, acc_g * GROUP_B.units_per_g, gyr_dps * GROUP_B.units_per_dps, GROUP_B,
                  meta={"sub": "synthetic"})


def _receive(records, meta):
    rx = Receiver(bytes.fromhex(meta["device_info"]))
    for ms, b in records:
        rx.feed(ms, b)
    return rx


def test_eeg_reaches_phone_unchanged_except_amplifier_noise():
    src = _synthetic_source()
    rec, meta = simulate(src, HardwareConfig(adc_noise_uv=0.2))
    rx = _receive(rec, meta)
    assert rx.missing_seq() == []
    first, eeg = rx.eeg_uv()
    n = eeg.shape[1]
    flagged = np.isnan(eeg[0])                           # contact check (D15): 2 s every 10 min, not for the model
    assert abs(flagged.sum() / 256 - 2.0) < 0.1          # one check in 60 s, ~2 s (whole packets)
    for ch, lab in zip(meta["training_pair"], ["BTEleft SD", "CROSStop SD"]):
        d = (eeg[ch - 1] - src.eeg_uv[lab][:n])[~flagged]
        d -= d.mean()                                    # electrode DC offset (constant)
        assert np.sqrt(np.mean(d ** 2)) < 0.25           # 0.2 µV noise + 0.05 µV steps


def test_locked_motion_sensor_reaches_phone_without_resampling():
    src = _synthetic_source()
    rec, meta = simulate(src, HardwareConfig(imu_locked=True, imu_noise_lsb=0))
    rx = _receive(rec, meta)
    first, eeg = rx.eeg_uv()
    n = int(eeg.shape[1] / 256 * 25)
    mov = rx.movement(n, first, GROUP_B)
    ref = np.vstack([src.acc, src.gyr])[:, :n]
    ok = np.isfinite(mov).all(0)
    assert ok.mean() > 0.99
    rel = np.sqrt(np.mean((mov[:, ok] - ref[:, ok]) ** 2, 1)) / (ref.std(1) + 1e-9)
    assert rel[ref.std(1) > 0].max() < 0.01              # only 16-bit rounding left


def test_phone_clock_fit_sits_on_the_lower_edge():
    rng = np.random.default_rng(0)
    x = np.arange(2000) * 0.05
    y = 1000 * (1 + 30e-6) * x + 5000 + rng.exponential(30, x.size)
    a, b = lower_envelope_fit(x, y)
    assert abs(a / 1000 - 1 - 30e-6) < 5e-6
    assert (y - (a * x + b)).min() >= -1e-6


def test_gyro_scale_is_recovered_from_gravity_rotation():
    fs, n = 25.0, 25 * 600
    t = np.arange(n) / fs
    ang = 0.6 * np.sin(2 * np.pi * 0.2 * t)              # slow nodding (max 0.75 rad/s)
    w = np.gradient(ang) * fs                            # rad/s about x
    acc = np.stack([np.zeros(n), np.sin(ang), np.cos(ang)]) * GROUP_B.units_per_g
    gyr = np.stack([w * 57.2958 * GROUP_B.units_per_dps, np.zeros(n), np.zeros(n)])
    k, used = gyro_units_per_rad_s(acc, gyr, fs)
    assert used > 200
    assert abs(k / (57.2958 * GROUP_B.units_per_dps) - 1) < 0.05


# ---- faults -------------------------------------------------------------------------------------
from epiprot.headband import faults as F


def _decoded(records):
    return [(ms, P.decode(b)) for ms, b in records]


def test_disconnect_loses_nothing_and_marks_catch_up_data():
    src = _synthetic_source(seconds=120)
    rec, meta = simulate(src, HardwareConfig(), faults=[F.Disconnect(30, 20)])
    rx = _receive(rec, meta)
    assert rx.missing_seq() == [] and meta["dropped_when_store_full"] == 0
    assert rx.catchup > 0
    late = [p for ms, p in _decoded(rec) if p.flags & P.FLAG_CATCHUP]
    assert all(ms >= 50_000 for ms, p in _decoded(rec) if p.flags & P.FLAG_CATCHUP)
    assert min(p.seq for p in late) < max(p.seq for p in late)


def test_full_store_drops_only_the_oldest_and_reports_it():
    src = _synthetic_source(seconds=120)
    cfg = HardwareConfig(store_bytes=20 * 3800)          # ~20 s of data
    rec, meta = simulate(src, cfg, faults=[F.Disconnect(30, 40)])
    rx = _receive(rec, meta)
    lost = rx.missing_seq()
    assert len(lost) == meta["dropped_when_store_full"] > 0
    assert lost == list(range(lost[0], lost[0] + len(lost)))          # one block: the oldest
    assert any(p.errors & P.ERR_FLASH_FULL for _, p in _decoded(rec) if isinstance(p, P.StatusPacket))


def test_electrode_off_saturates_its_channels_and_sets_contact_bits():
    src = _synthetic_source(seconds=60)
    rec, meta = simulate(src, HardwareConfig(), faults=[F.ElectrodeOff("L-top", 20, 10)])
    rx = _receive(rec, meta)
    first, eeg = rx.eeg_uv()
    m = slice(int(21 * 256), int(29 * 256))
    assert np.isnan(eeg[0, m]).all() and np.isnan(eeg[1, m]).all()   # channels 1, 2 use L-top
    assert np.isfinite(eeg[2, m]).all() and np.isfinite(eeg[3, m]).all()
    assert any(p.lead_off & P.LEAD_LTOP for p in rx.eeg)


def test_charging_stops_measuring_but_status_continues():
    src = _synthetic_source(seconds=60)
    rec, meta = simulate(src, HardwareConfig(), faults=[F.Charging(20, 20)])
    rx = _receive(rec, meta)
    t = np.array([p.sample_index / 256 for p in rx.eeg])
    assert not ((t > 20.1) & (t < 39.9)).any()
    assert any(s.state & P.ST_CHARGER for s in rx.status if 20 <= s.uptime_s < 40)


def test_contact_packet_round_trip():
    c = P.ContactPacket(11, 999, (20, 35, P.Z_UNKNOWN, 140, 18))
    b = P.encode(c)
    assert len(b) == P.CONTACT_SIZE == 20 and P.decode(b) == c


def test_drying_pad_is_reported_before_contact_is_lost():
    src = _synthetic_source(seconds=1300)
    cfg = HardwareConfig(contact_check_every_s=120)
    rec, meta = simulate(src, cfg, faults=[F.PadDrying("R-bottom", 100, 1000, 1200)])
    rx = _receive(rec, meta)
    warn = rx.pad_warnings()
    assert warn and all(name == "R-bottom" for _, name, _ in warn)
    assert warn[0][0] < 1100                                          # before contact is lost
    fresh = [p for p in rx.contact if p.t_dev / P.TICKS_PER_S < 100]
    assert fresh and max(fresh[0].impedance_kohm) < 30

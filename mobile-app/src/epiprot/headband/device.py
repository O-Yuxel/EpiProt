"""Virtual headband: turns a SeizeIT2 recording into the Bluetooth packets the designed headband
(device-firmware/HARDWARE.md) would send.

What the model adds on top of the SeizeIT2 signal (SeizeIT2 already contains its own electrode
and amplifier noise, so only what OUR hardware does differently is added):
  * electrode layout -> 4 channels (L-top, L-bottom, R-top, R-bottom), see HARDWARE.md
  * DC offset of every electrode (the ADS1299 is DC-coupled)
  * ADS1299 input noise, 24-bit quantisation at gain 12, saturation at ±375 mV
  * EEG crystal clock error, headband RTC crystal error
  * BMI270: its own sample clock (ODR error), conversion to raw 16-bit values (±8 g, ±2000 °/s), noise
  * packet timing: 16 EEG samples per packet, 5 movement samples, 1 status per second,
    Bluetooth connection events
SeizeIT2 has only two of our channels per patient; the missing ones are filled with copies and
marked in the metadata ("source_map"), so nothing downstream mistakes them for real data.
"""
from __future__ import annotations

import csv
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Sequence
from pathlib import Path

import numpy as np

from . import faults as F
from . import protocol as P
from .calibration import Seizeit2Scale, group_of
from .edf import read_edf

EEG_FS, MOV_FS = 256.0, 25.0
FULL_SCALE_UV = 4.5e6 / 12          # ±375 mV at gain 12


@dataclass
class HardwareConfig:
    adc_noise_uv: float = 0.2            # ADS1299 input noise, RMS, gain 12 [EST from 1 µVpp @ gain 24]
    electrode_offset_mv: float = 20.0    # spread of electrode DC offsets [EST]
    eeg_clock_ppm: float = 20.0          # EEG chip crystal error
    rtc_ppm: float = -15.0               # 32.768 kHz crystal error
    imu_locked: bool = True              # ICM-42688-P clocked by 32.000 kHz from the radio crystal (D13)
    hfxo_ppm: float = 20.0               # radio crystal error (sets the locked movement clock)
    imu_odr_error: float = 0.004         # free-running sensor clock error (BMI270-style), fraction [EST]
    imu_noise_lsb: float = 2.0           # motion sensor noise, raw LSB RMS [EST]
    conn_interval_ms: float = 45.0       # Bluetooth connection interval
    reconnect_s: float = 1.5             # advertising + phone scan + encrypted reconnect [EST]
    in_flight_s: float = 0.3             # packets sent but not yet confirmed when the link drops [EST]
    catchup_bytes_per_s: float = 40_000  # spare Bluetooth throughput for stored data [EST]
    store_bytes: int = 8 * 1024 * 1024 + 96 * 1024   # 8 MB flash + RAM buffer
    start_battery_pct: float = 80.0
    bias_off_mains_uv: float = 300.0     # mains hum reaching the channels without bias drive [EST]
    contact_check_every_s: float = 600.0 # contact check (D15): every 10 min ...
    contact_check_s: float = 2.0         # ... for 2 s
    contact_current_na: float = 6.0      # ADS1299 lead-off excitation current [DS option]
    fresh_pad_kohm: float = 20.0         # semi-dry pad on skin [EST]
    lost_contact_kohm: float = 1000.0    # above this the lead-off comparator reports no contact [EST]
    seed: int = 0


@dataclass
class Source:
    """A piece of one SeizeIT2 recording: EEG in µV (256 Hz), back-of-neck movement in SeizeIT2 units (25 Hz)."""
    eeg_uv: dict[str, np.ndarray]
    acc: np.ndarray | None = None        # 3 x n
    gyr: np.ndarray | None = None        # 3 x n
    scale: Seizeit2Scale | None = None
    meta: dict = field(default_factory=dict)


def seizure_runs(raw_dir: str | Path, sub: str) -> list[tuple[int, float, float]]:
    """(run, onset_s, duration_s) of the tonic-clonic seizures of a patient."""
    out = []
    for tsv in sorted((Path(raw_dir) / sub / "ses-01" / "eeg").glob("*_events.tsv")):
        run = int(tsv.name.split("run-")[1].split("_")[0])
        with open(tsv, newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                if r["eventType"] == "sz_foc_f2b":
                    out.append((run, float(r["onset"]), float(r["duration"])))
    return out


def load_source(raw_dir: str | Path, sub: str, run: int, start_s: float, dur_s: float) -> Source:
    base = Path(raw_dir) / sub / "ses-01"
    stem = f"{sub}_ses-01_task-szMonitoring_run-{run:02d}"
    e = read_edf(base / "eeg" / f"{stem}_eeg.edf")
    a, b = int(start_s * EEG_FS), int((start_s + dur_s) * EEG_FS)
    eeg = {l: s[a:b].astype(np.float64) for l, s, fs in zip(e["labels"], e["signals"], e["fs"])
           if fs == EEG_FS and "Annot" not in l}
    src = Source(eeg, meta={"sub": sub, "run": run, "start_s": start_s, "dur_s": dur_s})
    mp = base / "mov" / f"{stem}_mov.edf"
    if mp.exists():
        m = read_edf(mp)
        L = m["labels"]
        ai = [L.index(f"EEG SD ACC {c}") for c in "XYZ" if f"EEG SD ACC {c}" in L]
        gi = [i for i, l in enumerate(L) if l.startswith("EEG SD GYR")]
        if len(ai) == 3 and len(gi) == 3:
            ma, mb = int(start_s * MOV_FS), int((start_s + dur_s) * MOV_FS)
            acc = np.stack([m["signals"][i][ma:mb] for i in ai])
            scale = group_of(np.stack([m["signals"][i] for i in ai]))
            if scale is not None:
                src.acc, src.gyr, src.scale = acc, np.stack([m["signals"][i][ma:mb] for i in gi]), scale
    return src


def channel_map(eeg: dict[str, np.ndarray]):
    """SeizeIT2 channels -> the base signals c1 (L same-side), c2 (cross), c3 (R same-side).
    Returns c1, c2, c3, source_map and the headband channels that match SeizeIT2's two channels."""
    L, R, X = eeg.get("BTEleft SD"), eeg.get("BTEright SD"), eeg.get("CROSStop SD")
    if L is not None and X is not None:
        return L, X, L, {"1": "BTEleft SD", "2": "CROSStop SD", "3": "copy of BTEleft SD",
                         "4": "derived (ch2 - ch1 + ch3)"}, [1, 2]
    if R is not None and X is not None:
        return R, X, R, {"1": "copy of BTEright SD", "2": "CROSStop SD", "3": "BTEright SD",
                         "4": "derived (ch2 - ch1 + ch3)"}, [3, 2]
    if L is not None and R is not None:
        return L, L, R, {"1": "BTEleft SD", "2": "copy of BTEleft SD", "3": "BTEright SD",
                         "4": "derived (ch2 - ch1 + ch3)"}, [1, 3]
    raise ValueError(f"unknown EEG montage {sorted(eeg)}")


def simulate(src: Source, cfg: HardwareConfig = HardwareConfig(), info: P.DeviceInfo = P.DeviceInfo(),
             faults: Sequence = ()):
    """Returns (records, meta): records = [(arrival_ms on the phone clock, packet bytes)], in arrival order.
    faults: see faults.py."""
    rng = np.random.default_rng(cfg.seed)
    c1, c2, c3, source_map, pair = channel_map(src.eeg_uv)
    n_eeg = (len(c1) // P.EEG_N) * P.EEG_N
    eeg_dt = 1.0 / (EEG_FS * (1 + cfg.eeg_clock_ppm * 1e-6))                 # true seconds per sample
    t_eeg = np.arange(n_eeg) * eeg_dt

    # electrode potentials (L-bottom as 0 V reference) + DC offsets; index as faults.ELECTRODES
    el = np.zeros((5, n_eeg))
    el[0] = c1[:n_eeg]
    el[2] = el[0] - c2[:n_eeg]
    el[3] = el[2] - c3[:n_eeg]
    off = rng.normal(0, cfg.electrode_offset_mv * 1000, 4)                    # µV
    el[:4] += off[:, None]
    lead = np.zeros(n_eeg, np.uint8)
    mains = np.zeros(n_eeg)
    z = np.full((5, n_eeg), cfg.fresh_pad_kohm)                               # contact impedance, kOhm

    def span(a, d):
        return (t_eeg >= a) & (t_eeg < a + d)

    def lose_contact(i, m):
        lead[m] |= 1 << i
        z[i, m] = np.inf
        if i == 4:                    # bias lost: mains hum is no longer cancelled
            mains[m] = cfg.bias_off_mains_uv
        else:                         # lead-off current drives the input to the rail
            el[i, m] = 2 * FULL_SCALE_UV

    for f in faults:
        if isinstance(f, F.ElectrodeOff):
            lose_contact(F.electrode_index(f.electrode), span(f.start_s, f.dur_s))
        elif isinstance(f, F.PadDrying):
            i = F.electrode_index(f.electrode)
            m = span(f.start_s, f.ramp_s)
            frac = (t_eeg[m] - f.start_s) / f.ramp_s
            z[i, m] = cfg.fresh_pad_kohm + (cfg.lost_contact_kohm - cfg.fresh_pad_kohm) * frac
            if i < 4:
                el[i, m] += rng.normal(0, 1, m.sum()) * f.max_noise_uv * frac
            lose_contact(i, span(f.start_s + f.ramp_s, f.dur_s - f.ramp_s))
        elif isinstance(f, F.LooseCable):
            i = F.electrode_index(f.electrode)
            for b0 in rng.uniform(f.start_s, f.start_s + f.dur_s, rng.poisson(f.bursts_per_s * f.dur_s)):
                lose_contact(i, span(b0, f.burst_s))

    # contact checks: the EEG chip drives a small 64 Hz current (fDR/4) through every electrode and
    # measures the voltage; the EEG of those 2 s is flagged and not used by the model
    checks = [t for t in np.arange(5.0, n_eeg * eeg_dt - cfg.contact_check_s, cfg.contact_check_every_s)]
    in_check = np.zeros(n_eeg, bool)
    for t0 in checks:
        m = span(t0, cfg.contact_check_s)
        in_check |= m
        tone = np.sin(2 * np.pi * EEG_FS / 4 * t_eeg[m])
        for i in range(4):
            zi = np.where(np.isfinite(z[i, m]), z[i, m], 0.0)
            el[i, m] += cfg.contact_current_na * 1e-9 * zi * 1e3 * 1e6 * tone          # nA x kOhm -> µV
    ch = np.stack([el[0] - el[1], el[0] - el[2], el[2] - el[3], el[1] - el[3]], 1)
    if mains.any():
        ph = rng.uniform(0, 2 * np.pi, 4)
        k = rng.uniform(0.5, 1.5, 4)
        ch += mains[:, None] * k * np.sin(2 * np.pi * 50 * t_eeg[:, None] + ph)
    ch += rng.normal(0, cfg.adc_noise_uv, ch.shape)
    ch = np.clip(ch, -FULL_SCALE_UV, FULL_SCALE_UV)
    codes = np.clip(np.round(ch * 1000 / info.eeg_lsb_nv), P.INT24_MIN, P.INT24_MAX).astype(np.int32)
    sat = (np.abs(codes) >= P.INT24_MAX).any(1)

    # device state over time
    charging = [(f.start_s, f.start_s + f.dur_s) for f in faults if isinstance(f, F.Charging)]
    empty = min([f.empty_s for f in faults if isinstance(f, F.BatteryRunsOut)], default=np.inf)
    imu_dead = min([f.start_s for f in faults if isinstance(f, F.MotionSensorFailure)], default=np.inf)
    batt = next((f for f in faults if isinstance(f, F.BatteryRunsOut)), None)

    def is_charging(t):
        return any(a <= t < b for a, b in charging)

    def eeg_on(t):
        return not is_charging(t) and t < empty

    def pct(t):
        if batt is not None:
            return max(0.0, batt.start_pct * (1 - t / batt.empty_s))
        return max(0.0, cfg.start_battery_pct - t / 3600 * 100 / 48)

    rtc = lambda t: np.round(np.asarray(t) * (1 + cfg.rtc_ppm * 1e-6) * P.TICKS_PER_S).astype(np.int64)
    events = []                                                               # (ready time s, order, what)
    for k in range(0, n_eeg, P.EEG_N):
        if eeg_on(t_eeg[k]):
            events.append(((k + P.EEG_N) * eeg_dt, 0, ("eeg", k)))
    mov = None
    if src.acc is not None:
        dur = len(src.acc[0]) / MOV_FS
        err = cfg.hfxo_ppm * 1e-6 if cfg.imu_locked else cfg.imu_odr_error
        imu_dt = 1.0 / (MOV_FS * (1 + err))
        t_imu = np.arange(0, dur - 1 / MOV_FS, imu_dt)
        t_imu = t_imu[: (len(t_imu) // P.MOV_N) * P.MOV_N]
        # one world timeline: SeizeIT2 EEG sample k happens when the EEG chip takes sample k, so the
        # SeizeIT2 movement samples are placed on that same (slightly fast) timeline
        grid = np.arange(len(src.acc[0])) / MOV_FS * (EEG_FS * eeg_dt)
        acc_g = np.stack([np.interp(t_imu, grid, a) for a in src.acc]) / src.scale.units_per_g
        gyr_d = np.stack([np.interp(t_imu, grid, g) for g in src.gyr]) / src.scale.units_per_dps
        raw = np.vstack([acc_g * info.acc_lsb_per_g, gyr_d * info.gyr_lsb_per_dps]).T
        raw = np.clip(np.round(raw + rng.normal(0, cfg.imu_noise_lsb, raw.shape)), -32768, 32767).astype(np.int16)
        mov = (t_imu, raw)
        for j in range(0, len(t_imu), P.MOV_N):
            if eeg_on(t_imu[j]) and t_imu[j] < imu_dead:
                events.append((t_imu[j + P.MOV_N - 1] + 1e-3, 1, ("mov", j)))
    for s in range(int(min(n_eeg * eeg_dt, empty))):
        events.append((float(s) + 1e-4, 2, ("status", s)))
    for t0 in checks:
        if eeg_on(t0):
            events.append((t0 + cfg.contact_check_s + 1e-3, 3, ("contact", t0)))
    events.sort(key=lambda e: (e[0], e[1]))

    # Bluetooth link: live packets leave at the next connection event. While disconnected the headband
    # stores everything not confirmed by the phone (RAM + flash, oldest overwritten when full) and,
    # after reconnecting, sends the store with the catch-up flag next to the live packets.
    downs = sorted((f.start_s, f.start_s + f.dur_s + cfg.reconnect_s) for f in faults if isinstance(f, F.Disconnect))
    phase = rng.uniform(0, cfg.conn_interval_ms)
    records = []                                                              # (arrival ms, ready s, bytes)
    store = deque()
    store_bytes, flash_full, dropped, catchup, last = 0, False, 0, 0, 0.0
    cur_down = None

    def live(t_ready, b):
        nonlocal last
        ms = t_ready * 1000
        ev = phase + np.ceil((ms - phase) / cfg.conn_interval_ms) * cfg.conn_interval_ms
        last = max(last, ev + rng.uniform(2, 12))
        records.append((last, t_ready, b))

    for seq, (t_ready, _, (kind, k)) in enumerate(events):
        down = next(((a, b) for a, b in downs if a <= t_ready < b), None)
        if down is not None and cur_down is None:
            # link lost: packets still in flight were never confirmed, so they stay in the store
            cut = down[0] - cfg.in_flight_s
            moved = [r for r in records if r[1] is not None and r[1] >= cut]
            records = [r for r in records if not (r[1] is not None and r[1] >= cut)]
            for r in moved:
                store.append(P.decode(r[2]))
                store_bytes += len(r[2])
        if down is None and cur_down is not None:
            # reconnected: send the store at the catch-up rate, live packets keep flowing in between
            t = cur_down[1] * 1000
            while store:
                p = store.popleft()
                p.flags |= P.FLAG_CATCHUP
                b = P.encode(p)
                t += len(b) / cfg.catchup_bytes_per_s * 1000
                records.append((t + rng.uniform(2, 12), None, b))
                catchup += 1
            store_bytes, flash_full = 0, False
        cur_down = down

        if kind == "eeg":
            pkt = P.EegPacket(seq, k, int(rtc(k * eeg_dt)), codes[k:k + P.EEG_N],
                              int(np.bitwise_or.reduce(lead[k:k + P.EEG_N])),
                              P.FLAG_CONTACT_CHECK if in_check[k:k + P.EEG_N].any() else 0)
        elif kind == "contact":
            j = min(n_eeg - 1, int((k + cfg.contact_check_s / 2) / eeg_dt))
            zz = z[:, j] * (1 + rng.normal(0, 0.05, 5))                       # measurement error [EST]
            vals = tuple(P.Z_UNKNOWN if not np.isfinite(v) or v >= cfg.lost_contact_kohm
                         else int(round(max(v, 0))) for v in zz)
            pkt = P.ContactPacket(seq, int(rtc(k + cfg.contact_check_s)), vals)
        elif kind == "mov":
            t_imu, raw = mov
            pkt = P.MovPacket(seq, int(rtc(t_imu[k])), raw[k:k + P.MOV_N])
        else:
            m = (t_eeg >= k - 1) & (t_eeg < k)
            pc = pct(k)
            state = ((P.ST_STREAMING if eeg_on(k) else 0) | (P.ST_CHARGER | P.ST_CHARGING if is_charging(k) else 0)
                     | (P.ST_LOW_BATTERY if pc < 15 else 0))
            err = ((P.ERR_EEG_SATURATION if sat[m].any() else 0) | (P.ERR_IMU_CHIP if k >= imu_dead else 0)
                   | (P.ERR_FLASH_FULL if flash_full else 0))
            pkt = P.StatusPacket(seq, int(rtc(k)), int(3500 + 7 * pc), int(round(pc)), state,
                                 int(np.bitwise_or.reduce(lead[m])) if m.any() else 0, 30, len(store), err, k)
        b = P.encode(pkt)
        if down is None:
            live(t_ready, b)
        else:
            store.append(pkt)
            store_bytes += len(b)
            while store_bytes > cfg.store_bytes:
                x = store.popleft()
                store_bytes -= len(P.encode(x))
                dropped += 1
                flash_full = True

    records.sort(key=lambda r: r[0])
    meta = {**src.meta, "source_map": source_map, "training_pair": pair,
            "movement": None if src.scale is None else {"units_per_g": src.scale.units_per_g,
                                                       "units_per_dps": src.scale.units_per_dps},
            "config": asdict(cfg), "electrode_offsets_uv": off.tolist(),
            "faults": [{"type": type(f).__name__, **asdict(f)} for f in faults],
            "dropped_when_store_full": dropped, "catchup_packets": catchup, "never_sent": len(store),
            "eeg_samples": int(n_eeg), "device_info": info.encode().hex()}
    return [(r[0], r[2]) for r in records], meta


def write_stream(path: str | Path, records, meta) -> None:
    """Stream file: b'EHB1', u32 JSON length, JSON metadata, then (u32 arrival ms, u16 length, packet)."""
    import json
    import struct
    js = json.dumps(meta).encode()
    with open(path, "wb") as f:
        f.write(b"EHB1" + struct.pack("<I", len(js)) + js)
        for ms, b in records:
            f.write(struct.pack("<IH", int(round(ms)), len(b)) + b)


def read_stream(path: str | Path):
    import json
    import struct
    data = Path(path).read_bytes()
    assert data[:4] == b"EHB1", "not a headband stream file"
    n = struct.unpack_from("<I", data, 4)[0]
    meta = json.loads(data[8:8 + n])
    recs, o = [], 8 + n
    while o < len(data):
        ms, ln = struct.unpack_from("<IH", data, o)
        recs.append((ms, data[o + 6:o + 6 + ln]))
        o += 6 + ln
    return recs, meta

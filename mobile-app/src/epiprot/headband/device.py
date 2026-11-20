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
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

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


def simulate(src: Source, cfg: HardwareConfig = HardwareConfig(), info: P.DeviceInfo = P.DeviceInfo()):
    """Returns (records, meta): records = [(arrival_ms on the phone clock, packet bytes)], in arrival order."""
    rng = np.random.default_rng(cfg.seed)
    c1, c2, c3, source_map, pair = channel_map(src.eeg_uv)
    n_eeg = (len(c1) // P.EEG_N) * P.EEG_N

    # electrode potentials (L-bottom as 0 V reference), DC offsets, the 4 differential channels
    ltop, lbot = c1[:n_eeg], np.zeros(n_eeg)
    rtop = ltop - c2[:n_eeg]
    rbot = rtop - c3[:n_eeg]
    off = rng.normal(0, cfg.electrode_offset_mv * 1000, 4)                    # µV
    ltop, lbot, rtop, rbot = ltop + off[0], lbot + off[1], rtop + off[2], rbot + off[3]
    ch = np.stack([ltop - lbot, ltop - rtop, rtop - rbot, lbot - rbot], 1)
    ch += rng.normal(0, cfg.adc_noise_uv, ch.shape)
    ch = np.clip(ch, -FULL_SCALE_UV, FULL_SCALE_UV)
    codes = np.clip(np.round(ch * 1000 / info.eeg_lsb_nv), P.INT24_MIN, P.INT24_MAX).astype(np.int32)

    eeg_dt = 1.0 / (EEG_FS * (1 + cfg.eeg_clock_ppm * 1e-6))                 # true seconds per sample
    rtc = lambda t: np.round(np.asarray(t) * (1 + cfg.rtc_ppm * 1e-6) * P.TICKS_PER_S).astype(np.int64)
    events = []                                                               # (ready time s, order, builder)
    for p in range(n_eeg // P.EEG_N):
        k = p * P.EEG_N
        events.append((( k + P.EEG_N) * eeg_dt, 0, ("eeg", k)))

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
            events.append((t_imu[j + P.MOV_N - 1] + 1e-3, 1, ("mov", j)))
    dur_s = n_eeg * eeg_dt
    for s in range(int(dur_s)):
        events.append((float(s) + 1e-4, 2, ("status", s)))
    events.sort(key=lambda e: (e[0], e[1]))

    # Bluetooth: a packet leaves at the next connection event, plus radio / stack delay
    phase = rng.uniform(0, cfg.conn_interval_ms)
    records, last = [], 0.0
    for seq, (t_ready, _, (kind, k)) in enumerate(events):
        if kind == "eeg":
            pkt = P.EegPacket(seq, k, int(rtc(k * eeg_dt)), codes[k:k + P.EEG_N])
        elif kind == "mov":
            t_imu, raw = mov
            pkt = P.MovPacket(seq, int(rtc(t_imu[k])), raw[k:k + P.MOV_N])
        else:
            pct = max(0, 100 - k // 1728)                                     # ~2 days for 100 %
            pkt = P.StatusPacket(seq, int(rtc(k)), 3700 + 4 * pct, pct, uptime_s=k)
        ms = t_ready * 1000
        ev = phase + np.ceil((ms - phase) / cfg.conn_interval_ms) * cfg.conn_interval_ms
        arr = max(last, ev + rng.uniform(2, 12))
        last = arr
        records.append((arr, P.encode(pkt)))

    meta = {**src.meta, "source_map": source_map, "training_pair": pair,
            "movement": None if src.scale is None else {"units_per_g": src.scale.units_per_g,
                                                       "units_per_dps": src.scale.units_per_dps},
            "config": asdict(cfg), "electrode_offsets_uv": off.tolist(),
            "eeg_samples": int(n_eeg), "device_info": info.encode().hex()}
    return records, meta


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

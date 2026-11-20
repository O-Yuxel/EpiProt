"""Reference phone-side receiver for the headband packets (what the Android app will do in step 4).

Rules from PROTOCOL.md: raw values are converted with the constants the headband reports (P1),
missing samples stay NaN and are never guessed (P2), an unknown protocol major version is refused (P6).
"""
from __future__ import annotations

import numpy as np

from . import protocol as P
from .calibration import TRAINING, Seizeit2Scale

WRAP = 1 << 32


def _unwrap(t: np.ndarray) -> np.ndarray:
    t = np.asarray(t, np.int64)
    d = np.diff(t)
    jumps = np.concatenate([[0], np.cumsum((d < -WRAP // 2).astype(np.int64) - (d > WRAP // 2).astype(np.int64))])
    return t + jumps * WRAP


def lower_envelope_fit(x: np.ndarray, y: np.ndarray, rounds: int = 4) -> tuple[float, float]:
    """Line y = a*x + b along the lower edge of the points (delays only ever add time)."""
    a, b = np.polyfit(x, y, 1)
    keep = np.ones(len(x), bool)
    for _ in range(rounds):
        r = y - (a * x + b)
        keep = r <= np.percentile(r[keep], 20)
        a, b = np.polyfit(x[keep], y[keep], 1)
    r = y - (a * x + b)
    return float(a), float(b + r.min())


class Receiver:
    def __init__(self, info_bytes: bytes):
        self.info = P.DeviceInfo.decode(info_bytes)
        self.eeg: list[P.EegPacket] = []
        self.mov: list[P.MovPacket] = []
        self.status: list[P.StatusPacket] = []
        self.arrival: dict[int, float] = {}
        self.t_dev: dict[int, int] = {}

    def feed(self, arrival_ms: float, data: bytes) -> None:
        p = P.decode(data)
        self.arrival[p.seq], self.t_dev[p.seq] = arrival_ms, p.t_dev
        (self.eeg if isinstance(p, P.EegPacket) else self.mov if isinstance(p, P.MovPacket) else self.status).append(p)

    def missing_seq(self) -> list[int]:
        s = np.array(sorted(self.arrival))
        if len(s) == 0:
            return []
        return sorted(set(range(int(s[0]), int(s[-1]) + 1)) - set(s.tolist()))

    # ---- EEG -------------------------------------------------------------------------------
    def eeg_uv(self) -> tuple[int, np.ndarray]:
        """(first sample index, 4 x N µV). Missing or saturated samples are NaN."""
        idx = _unwrap([p.sample_index for p in self.eeg])
        first, end = int(idx.min()), int(max(i + len(p.codes) for i, p in zip(idx, self.eeg)))
        out = np.full((P.EEG_CH, end - first), np.nan)
        for i, p in zip(idx, self.eeg):
            c = p.codes.astype(np.float64)
            c[(p.codes <= P.INT24_MIN) | (p.codes >= P.INT24_MAX)] = np.nan
            out[:, i - first:i - first + len(c)] = c.T * self.info.eeg_lsb_nv / 1000
        return first, out

    def rtc_to_eeg_s(self) -> tuple[float, float]:
        """Headband RTC (seconds) -> EEG sample time (seconds), from the EEG packets' (sample_index, t_dev)."""
        td = _unwrap([p.t_dev for p in self.eeg]) / P.TICKS_PER_S
        te = _unwrap([p.sample_index for p in self.eeg]) / self.info.eeg_rate
        a, b = np.polyfit(td, te, 1)
        return float(a), float(b)

    def phone_clock(self) -> tuple[float, float]:
        """Headband RTC seconds -> phone milliseconds (lower edge of arrival times)."""
        seqs = sorted(self.arrival)
        td = _unwrap([self.t_dev[s] for s in seqs]) / P.TICKS_PER_S
        return lower_envelope_fit(td, np.array([self.arrival[s] for s in seqs]))

    # ---- movement ----------------------------------------------------------------------------
    def movement(self, n_out: int, first_eeg_index: int = 0, scale: Seizeit2Scale = TRAINING,
                 mode: str = "slot") -> np.ndarray:
        """6 x n_out movement (acc xyz, gyro xyz) in SeizeIT2 units on the 25 Hz grid of the EEG timeline
        (grid sample 0 = EEG sample first_eeg_index). NaN where no movement data cover the time.

        mode "slot": every sample goes to its nearest grid slot, values untouched (what the app's
        WindowAssembler does). Exact when the sensor clock is locked to the crystal; a free-running
        clock makes slots repeat or stay empty. mode "interp": linear resampling onto the grid."""
        out = np.full((6, n_out), np.nan)
        if not self.mov:
            return out
        a, b = self.rtc_to_eeg_s()
        td = _unwrap([p.t_dev for p in self.mov]) / P.TICKS_PER_S
        n = np.array([len(p.raw) for p in self.mov])
        dt = np.median(np.diff(td) / n[:-1]) if len(td) > 1 else 1 / self.info.mov_rate
        t = np.concatenate([t0 + np.arange(k) * dt for t0, k in zip(td, n)])
        t = a * t + b - first_eeg_index / self.info.eeg_rate
        raw = np.vstack([p.raw for p in self.mov]).astype(np.float64)
        val = np.vstack([raw[:, :3].T / self.info.acc_lsb_per_g * scale.units_per_g,
                         raw[:, 3:].T / self.info.gyr_lsb_per_dps * scale.units_per_dps])
        if mode == "slot":
            k = np.round(t * self.info.mov_rate).astype(np.int64)
            ok = (k >= 0) & (k < n_out)
            out[:, k[ok]] = val[:, ok]
            return out
        grid = np.arange(n_out) / self.info.mov_rate
        ok = (grid >= t[0]) & (grid <= t[-1])
        gap = np.concatenate([[False], np.diff(t) > 3 * dt])          # do not interpolate across gaps
        for i in range(6):
            out[i, ok] = np.interp(grid[ok], t, val[i])
        if gap.any():
            for g in np.flatnonzero(gap):
                out[:, (grid > t[g - 1]) & (grid < t[g])] = np.nan
        return out

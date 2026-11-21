"""Faults the virtual headband can be given (times in seconds from the start of the recording).

Electrodes: "L-top", "L-bottom", "R-top", "R-bottom", "bias" (HARDWARE.md).
"""
from __future__ import annotations

from dataclasses import dataclass

ELECTRODES = ["L-top", "L-bottom", "R-top", "R-bottom", "bias"]


@dataclass
class Disconnect:
    """Phone out of range / Bluetooth off. The headband keeps measuring and stores the data."""
    start_s: float
    dur_s: float


@dataclass
class ElectrodeOff:
    """A pad loses contact (falls off, band pushed away). Its input runs to the rail."""
    electrode: str
    start_s: float
    dur_s: float


@dataclass
class PadDrying:
    """A semi-dry pad dries out: noise grows over ramp_s, then contact is lost until start+dur."""
    electrode: str
    start_s: float
    ramp_s: float
    dur_s: float
    max_noise_uv: float = 40.0          # [EST]


@dataclass
class LooseCable:
    """Broken / loose wire: short contact losses at random."""
    electrode: str
    start_s: float
    dur_s: float
    bursts_per_s: float = 0.5
    burst_s: float = 0.3


@dataclass
class Charging:
    """Charger attached: band off the head, EEG chip and motion sensor off, status keeps going."""
    start_s: float
    dur_s: float


@dataclass
class MotionSensorFailure:
    start_s: float


@dataclass
class BatteryRunsOut:
    """Battery goes from start_pct to 0 at empty_s; the headband switches itself off."""
    empty_s: float
    start_pct: float = 20.0


def electrode_index(name: str) -> int:
    return ELECTRODES.index(name)

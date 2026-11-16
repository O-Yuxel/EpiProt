"""Alarm kuralları yapılandırması."""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class AlarmConfig:
    """Alarm eşiği ve birleştirme kuralları.

    Bu değerler test seti görülmeden (eğitim/validation üzerinde) seçilmelidir.
    """
    threshold: float = 0.5
    min_alarm_duration_s: float = 60.0
    merge_gap_s: float = 300.0
    min_lead_minutes: float = 5.0
    max_lead_minutes: float = 60.0

    def __post_init__(self) -> None:
        if not 0.0 < self.threshold < 1.0:
            raise ValueError(f"threshold (0,1) içinde olmalı: {self.threshold}")
        if self.min_alarm_duration_s <= 0:
            raise ValueError("min_alarm_duration_s > 0 olmalı")
        if self.merge_gap_s < 0:
            raise ValueError("merge_gap_s >= 0 olmalı")
        if self.min_lead_minutes < 0:
            raise ValueError("min_lead_minutes >= 0 olmalı")
        if self.max_lead_minutes <= self.min_lead_minutes:
            raise ValueError(
                f"max_lead_minutes ({self.max_lead_minutes}) > "
                f"min_lead_minutes ({self.min_lead_minutes}) olmalı"
            )

    def as_dict(self) -> dict:
        return asdict(self)
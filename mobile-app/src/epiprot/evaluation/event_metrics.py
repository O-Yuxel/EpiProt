"""Nöbet düzeyinde metrikler.

Şartname 11.1'e göre:
    - Kaç nöbet yakalandı?
    - Günlük yanlış alarm sayısı nedir?
    - Alarm başlangıcından nöbet başlangıcına kadar geçen süre nedir?
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from ..labeling.horizons import Seizure
from .alarm_config import AlarmConfig
from .alarm_events import AlarmEvent


@dataclass
class SeizureMatch:
    """Bir alarmın bir nöbetle eşleşmesi."""
    patient_id: str | None
    seizure_start_s: float
    alarm_start_s: float
    alarm_end_s: float
    lead_minutes: float


@dataclass
class UnmatchedAlarm:
    """Bir nöbetle eşleşmeyen alarm (yanlış alarm)."""
    patient_id: str | None
    alarm_start_s: float
    alarm_end_s: float
    peak_score: float


@dataclass
class PatientEventMetrics:
    patient_id: str
    n_seizures: int
    n_seizures_caught: int
    n_false_alarms: int
    total_monitoring_hours: float
    alarm_lead_minutes: List[float] = field(default_factory=list)
    matched: List[SeizureMatch] = field(default_factory=list)
    false_alarms: List[UnmatchedAlarm] = field(default_factory=list)

    @property
    def seizure_detection_rate(self) -> float:
        return (
            self.n_seizures_caught / self.n_seizures
            if self.n_seizures > 0 else float("nan")
        )

    @property
    def false_alarms_per_day(self) -> float:
        if self.total_monitoring_hours <= 0:
            return float("nan")
        return self.n_false_alarms / (self.total_monitoring_hours / 24.0)

    @property
    def median_lead_minutes(self) -> float:
        if not self.alarm_lead_minutes:
            return float("nan")
        return float(np.median(self.alarm_lead_minutes))

    @property
    def mean_lead_minutes(self) -> float:
        if not self.alarm_lead_minutes:
            return float("nan")
        return float(np.mean(self.alarm_lead_minutes))

    def to_row(self) -> dict:
        d = asdict(self)
        d.pop("matched")
        d.pop("false_alarms")
        d["seizure_detection_rate"] = self.seizure_detection_rate
        d["false_alarms_per_day"] = self.false_alarms_per_day
        d["median_lead_minutes"] = self.median_lead_minutes
        d["mean_lead_minutes"] = self.mean_lead_minutes
        return d


def _match_alarms_to_seizures(
    alarms: Sequence[AlarmEvent],
    seizures: Sequence[Seizure],
    cfg: AlarmConfig,
) -> tuple[List[SeizureMatch], List[UnmatchedAlarm]]:
    """Alarmları nöbetlerle eşleştir (greedy, zamana göre).

    Kural: bir alarm, nöbet başlangıcından **sonra** başlamalı mı? Hayır;
    alarm nöbetten ÖNCE gelmeli. `min_lead_minutes <= lead <= max_lead_minutes`.
    """
    matched: List[SeizureMatch] = []
    used_alarms: set[int] = set()

    for sz in sorted(seizures, key=lambda s: s.start_s):
        best_idx = None
        best_lead = None
        for i, alarm in enumerate(alarms):
            if i in used_alarms:
                continue
            lead_min = (sz.start_s - alarm.start_s) / 60.0
            # Alarm nöbet başlangıcından önce bitmeli
            if alarm.end_s > sz.start_s:
                continue
            if cfg.min_lead_minutes <= lead_min <= cfg.max_lead_minutes:
                if best_lead is None or abs(lead_min - (cfg.min_lead_minutes + cfg.max_lead_minutes) / 2.0) < abs(best_lead - (cfg.min_lead_minutes + cfg.max_lead_minutes) / 2.0):
                    best_idx = i
                    best_lead = lead_min
        if best_idx is not None:
            used_alarms.add(best_idx)
            a = alarms[best_idx]
            matched.append(SeizureMatch(
                patient_id=a.patient_id,
                seizure_start_s=sz.start_s,
                alarm_start_s=a.start_s,
                alarm_end_s=a.end_s,
                lead_minutes=best_lead,
            ))

    false_alarms = [
        UnmatchedAlarm(
            patient_id=a.patient_id,
            alarm_start_s=a.start_s,
            alarm_end_s=a.end_s,
            peak_score=a.peak_score,
        )
        for i, a in enumerate(alarms) if i not in used_alarms
    ]
    return matched, false_alarms


def compute_patient_event_metrics(
    patient_id: str,
    alarms: Sequence[AlarmEvent],
    seizures_by_edf: Dict[str, List[Seizure]],
    edf_durations_s: Dict[str, float],
    cfg: AlarmConfig,
) -> PatientEventMetrics:
    """Bir hasta için event-level metrikler.

    Parametreler
    ------------
    alarms : sadece bu hastaya ait alarmlar (edf_path'leri bu hastanın).
    seizures_by_edf : {edf_path: [Seizure]}
    edf_durations_s : {edf_path: saniye}
    """
    # Bu hastanın tüm nöbetleri (EDF bazında zamanlar EDF başlangıcına göre)
    all_seizures = [
        sz for edf, szs in seizures_by_edf.items() for sz in szs
    ]
    total_hours = sum(edf_durations_s.values()) / 3600.0

    matched, false_alarms = _match_alarms_to_seizures(alarms, all_seizures, cfg)

    return PatientEventMetrics(
        patient_id=patient_id,
        n_seizures=len(all_seizures),
        n_seizures_caught=len(matched),
        n_false_alarms=len(false_alarms),
        total_monitoring_hours=total_hours,
        alarm_lead_minutes=[m.lead_minutes for m in matched],
        matched=matched,
        false_alarms=false_alarms,
    )
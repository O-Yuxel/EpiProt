"""Event-level raporu tabloya çevir."""
from __future__ import annotations

from dataclasses import asdict
from typing import List

import pandas as pd

from .event_metrics import PatientEventMetrics


def event_metrics_to_dataframe(metrics: List[PatientEventMetrics]) -> pd.DataFrame:
    return pd.DataFrame([m.to_row() for m in metrics])


def matches_to_dataframe(metrics: List[PatientEventMetrics]) -> pd.DataFrame:
    rows = []
    for m in metrics:
        for match in m.matched:
            rows.append({
                "patient_id": m.patient_id,
                "seizure_start_s": match.seizure_start_s,
                "alarm_start_s": match.alarm_start_s,
                "alarm_end_s": match.alarm_end_s,
                "lead_minutes": match.lead_minutes,
            })
    return pd.DataFrame(rows)


def false_alarms_to_dataframe(metrics: List[PatientEventMetrics]) -> pd.DataFrame:
    rows = []
    for m in metrics:
        for fa in m.false_alarms:
            rows.append({
                "patient_id": m.patient_id,
                "alarm_start_s": fa.alarm_start_s,
                "alarm_end_s": fa.alarm_end_s,
                "peak_score": fa.peak_score,
            })
    return pd.DataFrame(rows)
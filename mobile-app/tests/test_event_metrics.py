"""event_metrics.py için birim testleri."""
from __future__ import annotations

import numpy as np
import pytest

from epiprot.evaluation.alarm_config import AlarmConfig
from epiprot.evaluation.alarm_events import AlarmEvent
from epiprot.evaluation.event_metrics import (
    compute_patient_event_metrics,
)
from epiprot.labeling.horizons import Seizure


def _alarm(start_min: float, dur_s: float = 60.0, edf: str = "/a/e.edf") -> AlarmEvent:
    return AlarmEvent(
        edf_path=edf,
        patient_id="chb01",
        start_s=start_min * 60.0,
        end_s=start_min * 60.0 + dur_s,
        peak_score=0.9,
        n_windows=int(dur_s // 10),
    )


def _cfg() -> AlarmConfig:
    return AlarmConfig(
        threshold=0.5,
        min_alarm_duration_s=30.0,
        merge_gap_s=300.0,
        min_lead_minutes=5.0,
        max_lead_minutes=60.0,
    )


def test_perfect_alarm_catches_seizure() -> None:
    # Alarm 30. dk, nöbet 60. dk -> lead 30 dk -> eşleşmeli
    alarms = [_alarm(start_min=30.0)]
    seizures = {"/a/e.edf": [Seizure(start_s=60 * 60.0, end_s=60 * 60.0 + 30.0)]}
    m = compute_patient_event_metrics(
        "chb01", alarms, seizures, {"/a/e.edf": 3600.0}, _cfg()
    )
    assert m.n_seizures == 1
    assert m.n_seizures_caught == 1
    assert m.n_false_alarms == 0
    assert m.alarm_lead_minutes == [30.0]


def test_alarm_too_early_is_false() -> None:
    # Alarm 10. dk, nöbet 100. dk -> lead 90 dk > max_lead_minutes=60 -> yanlış alarm
    alarms = [_alarm(start_min=10.0)]
    seizures = {"/a/e.edf": [Seizure(start_s=100 * 60.0, end_s=100 * 60.0 + 30.0)]}
    m = compute_patient_event_metrics(
        "chb01", alarms, seizures, {"/a/e.edf": 3600.0}, _cfg()
    )
    assert m.n_seizures == 1
    assert m.n_seizures_caught == 0
    assert m.n_false_alarms == 1


def test_alarm_too_late_is_false() -> None:
    # Alarm 57. dk, nöbet 60. dk -> lead 3 dk < min_lead_minutes=5 -> yanlış
    alarms = [_alarm(start_min=57.0)]
    seizures = {"/a/e.edf": [Seizure(start_s=60 * 60.0, end_s=60 * 60.0 + 30.0)]}
    m = compute_patient_event_metrics(
        "chb01", alarms, seizures, {"/a/e.edf": 3600.0}, _cfg()
    )
    assert m.n_seizures_caught == 0
    assert m.n_false_alarms == 1


def test_alarm_overlapping_seizure_start_is_false() -> None:
    # Alarm nöbet sırasında başlıyor -> yanlış
    alarms = [AlarmEvent(
        edf_path="/a/e.edf", patient_id="chb01",
        start_s=60 * 60.0 + 5.0, end_s=60 * 60.0 + 65.0,
        peak_score=0.95, n_windows=6,
    )]
    seizures = {"/a/e.edf": [Seizure(start_s=60 * 60.0, end_s=60 * 60.0 + 30.0)]}
    m = compute_patient_event_metrics(
        "chb01", alarms, seizures, {"/a/e.edf": 3600.0}, _cfg()
    )
    assert m.n_seizures_caught == 0
    assert m.n_false_alarms == 1


def test_two_alarms_one_seizure() -> None:
    # İki alarm, bir nöbet -> bir eşleşme, bir yanlış
    alarms = [_alarm(start_min=20.0), _alarm(start_min=50.0)]
    seizures = {"/a/e.edf": [Seizure(start_s=60 * 60.0, end_s=60 * 60.0 + 30.0)]}
    m = compute_patient_event_metrics(
        "chb01", alarms, seizures, {"/a/e.edf": 3600.0}, _cfg()
    )
    # 50 dk lead=10 dk (en yakın); 20 dk lead=40 dk da geçerli ama ilk seçilir
    assert m.n_seizures_caught == 1
    assert m.n_false_alarms == 1


def test_false_alarms_per_day_computed() -> None:
    # 24 saat izleme, 2 yanlış alarm -> 2/gün
    alarms = [_alarm(start_min=5.0), _alarm(start_min=10.0)]  # ikisi de nöbetsiz
    seizures = {"/a/e.edf": []}
    m = compute_patient_event_metrics(
        "chb01", alarms, seizures, {"/a/e.edf": 24 * 3600.0}, _cfg()
    )
    assert m.n_false_alarms == 2
    assert m.false_alarms_per_day == 2.0


def test_metrics_handles_zero_seizures() -> None:
    alarms = [_alarm(start_min=5.0)]
    m = compute_patient_event_metrics(
        "chb01", alarms, {}, {"/a/e.edf": 3600.0}, _cfg()
    )
    assert m.n_seizures == 0
    # Bölme sıfır -> NaN
    assert np.isnan(m.seizure_detection_rate)
    assert m.n_false_alarms == 1
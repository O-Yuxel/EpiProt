"""alarm_events.py için birim testleri."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from epiprot.evaluation.alarm_config import AlarmConfig
from epiprot.evaluation.alarm_events import (
    aggregate_scores_by_window,
    extract_alarms,
)


def _make_preds(probas, edf="/a/e.edf", channel="CH0", patient_id="chb01",
                window_len_s=10.0):
    rows = []
    for i, p in enumerate(probas):
        rows.append({
            "edf_path": edf,
            "patient_id": patient_id,
            "channel": channel,
            "window_start_s": float(i * window_len_s),
            "window_end_s": float(i * window_len_s + window_len_s),
            "y_proba": float(p),
        })
    return pd.DataFrame(rows)


def test_extract_alarms_simple_contiguous() -> None:
    # 20 dk'lık sürekli yüksek skor -> tek bir uzun alarm
    preds = _make_preds([0.1] * 5 + [0.9] * 20 + [0.1] * 5)
    cfg = AlarmConfig(threshold=0.5, min_alarm_duration_s=60.0)
    res = extract_alarms(preds, cfg)
    assert res.n_merged_events == 1
    ev = res.events[0]
    assert ev.start_s == 50.0
    assert ev.end_s == 250.0
    assert ev.peak_score == 0.9
    assert ev.n_windows == 20


def test_extract_alarms_merges_close_events() -> None:
    # İki yüksek skor bloğu arasında 100 saniye -> merge_gap_s=300 -> birleşmeli
    probas = [0.9] * 6 + [0.1] * 10 + [0.9] * 6
    preds = _make_preds(probas)  # 10 sn pencere
    cfg = AlarmConfig(threshold=0.5, min_alarm_duration_s=30.0, merge_gap_s=300.0)
    res = extract_alarms(preds, cfg)
    assert res.n_merged_events == 1


def test_extract_alarms_splits_when_far() -> None:
    # İki blok arasında 1000 saniye > merge_gap_s -> iki ayrı alarm
    probas = [0.9] * 6 + [0.1] * 100 + [0.9] * 6
    preds = _make_preds(probas)
    cfg = AlarmConfig(threshold=0.5, min_alarm_duration_s=30.0, merge_gap_s=300.0)
    res = extract_alarms(preds, cfg)
    assert res.n_merged_events == 2


def test_extract_alarms_drops_too_short() -> None:
    # Tek pencere (10 sn) < min_alarm_duration_s=60 -> atılmalı
    preds = _make_preds([0.9] + [0.1] * 20)
    cfg = AlarmConfig(threshold=0.5, min_alarm_duration_s=60.0)
    res = extract_alarms(preds, cfg)
    assert res.n_merged_events == 0
    assert res.n_dropped_too_short == 1


def test_extract_alarms_no_high_score() -> None:
    preds = _make_preds([0.1] * 30)
    cfg = AlarmConfig(threshold=0.5)
    res = extract_alarms(preds, cfg)
    assert res.n_merged_events == 0
    assert res.n_candidate_windows == 0


def test_extract_alarms_multiple_edfs() -> None:
    p1 = _make_preds([0.9] * 10, edf="/a/chb01_01.edf")
    p2 = _make_preds([0.9] * 10, edf="/a/chb01_02.edf")
    preds = pd.concat([p1, p2], ignore_index=True)
    cfg = AlarmConfig(threshold=0.5, min_alarm_duration_s=60.0)
    res = extract_alarms(preds, cfg)
    assert res.n_merged_events == 2
    edfs = {e.edf_path for e in res.events}
    assert edfs == {"/a/chb01_01.edf", "/a/chb01_02.edf"}


def test_aggregate_scores_by_window_max() -> None:
    p1 = _make_preds([0.2, 0.8], channel="CH0")
    p2 = _make_preds([0.7, 0.1], channel="CH1")
    preds = pd.concat([p1, p2], ignore_index=True)
    agg = aggregate_scores_by_window(preds, agg="max")
    assert len(agg) == 2
    assert list(agg["y_proba"]) == [0.7, 0.8]


def test_aggregate_scores_by_window_mean() -> None:
    p1 = _make_preds([0.2, 0.8], channel="CH0")
    p2 = _make_preds([0.7, 0.1], channel="CH1")
    preds = pd.concat([p1, p2], ignore_index=True)
    agg = aggregate_scores_by_window(preds, agg="mean")
    assert np.allclose(agg["y_proba"], [0.45, 0.45])


def test_alarm_config_validates() -> None:
    with pytest.raises(ValueError):
        AlarmConfig(threshold=0.0)
    with pytest.raises(ValueError):
        AlarmConfig(threshold=1.0)
    with pytest.raises(ValueError):
        AlarmConfig(min_lead_minutes=10, max_lead_minutes=5)
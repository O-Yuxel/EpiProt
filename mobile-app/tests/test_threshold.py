"""threshold.py için birim testleri."""
from __future__ import annotations

import numpy as np

from epiprot.experiments.threshold import sweep_thresholds, tune_threshold


def test_tune_threshold_returns_valid() -> None:
    rng = np.random.default_rng(0)
    # Pozitifler yüksek skora, negatifler düşük skora sahip
    y = np.r_[np.zeros(100, dtype=int), np.ones(100, dtype=int)]
    proba = np.r_[rng.uniform(0, 0.4, 100), rng.uniform(0.6, 1.0, 100)]
    res = tune_threshold(y, proba)
    assert 0.05 <= res.threshold <= 0.95
    assert res.metric == "f1"
    assert np.isfinite(res.score)
    assert res.score > 0.8  # çok ayrık veri, iyi skor beklenir


def test_tune_threshold_insufficient_data() -> None:
    y = np.array([0, 0, 0, 1])
    proba = np.array([0.1, 0.2, 0.3, 0.9])
    res = tune_threshold(y, proba, min_positive=5)
    assert res.threshold == 0.5
    assert np.isnan(res.score)
    assert "insufficient" in res.metric


def test_tune_threshold_balanced_accuracy() -> None:
    rng = np.random.default_rng(1)
    y = np.r_[np.zeros(50, dtype=int), np.ones(50, dtype=int)]
    proba = np.r_[rng.uniform(0, 0.5, 50), rng.uniform(0.5, 1.0, 50)]
    res = tune_threshold(y, proba, metric="balanced_accuracy")
    assert res.metric == "balanced_accuracy"


def test_sweep_thresholds_returns_rows() -> None:
    y = np.r_[np.zeros(20, dtype=int), np.ones(20, dtype=int)]
    proba = np.r_[np.full(20, 0.2), np.full(20, 0.8)]
    rows = sweep_thresholds(y, proba, thresholds=[0.3, 0.5, 0.7])
    assert len(rows) == 3
    for r in rows:
        assert "threshold" in r
        assert "f1" in r
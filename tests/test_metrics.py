"""metrics.py için birim testleri."""
from __future__ import annotations

import numpy as np

from epiprot.modeling.metrics import compute_metrics


def test_metrics_perfect_prediction() -> None:
    y = np.array([0, 0, 1, 1, 0, 1])
    p = y.copy()
    proba = np.array([0.1, 0.1, 0.9, 0.9, 0.1, 0.9])
    m = compute_metrics(y, p, proba, horizon_min=30)
    assert m.accuracy == 1.0
    assert m.recall == 1.0
    assert m.precision == 1.0
    assert m.f1 == 1.0
    assert m.specificity == 1.0
    assert m.balanced_accuracy == 1.0
    assert m.roc_auc == 1.0


def test_metrics_all_negative_class() -> None:
    y = np.zeros(10, dtype=int)
    p = np.zeros(10, dtype=int)
    proba = np.full(10, 0.1)
    m = compute_metrics(y, p, proba, horizon_min=30)
    assert m.n_positive == 0
    assert m.n_negative == 10
    # Tek sınıf varsa AUC tanımsız -> NaN ve status insufficient_data
    assert np.isnan(m.roc_auc)
    assert m.status == "insufficient_data"


def test_metrics_confusion_matrix_present() -> None:
    y = np.array([0, 0, 1, 1])
    p = np.array([0, 1, 0, 1])
    proba = np.array([0.1, 0.6, 0.4, 0.9])
    m = compute_metrics(y, p, proba, horizon_min=30)
    assert m.confusion_matrix is not None
    assert np.array(m.confusion_matrix).shape == (2, 2)
    # tp=1, tn=1, fp=1, fn=1
    tn, fp, fn, tp = m.confusion_matrix[0][0], m.confusion_matrix[0][1], m.confusion_matrix[1][0], m.confusion_matrix[1][1]
    assert (tn, fp, fn, tp) == (1, 1, 1, 1)
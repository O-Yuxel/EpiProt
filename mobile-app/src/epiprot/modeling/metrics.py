"""Genişletilmiş metrikler — accuracy tek başına kullanılmaz."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass
class ClassificationMetrics:
    horizon_min: int
    n_test: int
    n_positive: int
    n_negative: int
    accuracy: float = float("nan")
    balanced_accuracy: float = float("nan")
    precision: float = float("nan")
    recall: float = float("nan")
    specificity: float = float("nan")
    f1: float = float("nan")
    roc_auc: float = float("nan")
    pr_auc: float = float("nan")
    confusion_matrix: list | None = None
    status: str = "ok"  # "ok" | "insufficient_data" | ...

    def to_row(self) -> dict:
        d = asdict(self)
        if self.confusion_matrix is not None:
            d["confusion_matrix"] = str(self.confusion_matrix)
        return d


def _safe_metric(fn, *args, **kwargs) -> float:
    try:
        v = fn(*args, **kwargs)
        v = float(v)
        return v if np.isfinite(v) else float("nan")
    except Exception:  # noqa: BLE001
        return float("nan")


def compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray,
    horizon_min: int,
) -> ClassificationMetrics:
    """İkili sınıflandırma için geniş metrik seti."""
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)
    y_proba = np.asarray(y_proba).astype(float)

    n = y_true.size
    n_pos = int((y_true == 1).sum())
    n_neg = int((y_true == 0).sum())

    m = ClassificationMetrics(
        horizon_min=horizon_min,
        n_test=n,
        n_positive=n_pos,
        n_negative=n_neg,
    )

    if n == 0:
        m.status = "insufficient_data"
        return m

    # Confusion matrix her zaman hesaplanabilir
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    m.confusion_matrix = cm.tolist()
    tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, 0)

    m.accuracy = _safe_metric(accuracy_score, y_true, y_pred)
    if n_pos > 0 and n_neg > 0:
        m.balanced_accuracy = _safe_metric(balanced_accuracy_score, y_true, y_pred)
    m.precision = _safe_metric(precision_score, y_true, y_pred, zero_division=0)
    m.recall = _safe_metric(recall_score, y_true, y_pred, zero_division=0)
    m.f1 = _safe_metric(f1_score, y_true, y_pred, zero_division=0)
    if (tn + fp) > 0:
        m.specificity = float(tn / (tn + fp))

    # AUC metrikleri için her iki sınıf da gerekli
    if n_pos > 0 and n_neg > 0:
        m.roc_auc = _safe_metric(roc_auc_score, y_true, y_proba)
        m.pr_auc = _safe_metric(average_precision_score, y_true, y_proba)
    else:
        m.status = "insufficient_data"

    return m
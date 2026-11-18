"""Validation seti üzerinde alarm eşiği seçimi.

Kural: test seti asla eşik seçiminde kullanılmaz.
Yöntem: eğitim verisinin son kısmını validation olarak ayır, orada
       farklı eşikleri dene, F1 veya dengeli doğruluk kriterine göre
       en iyisini seç.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sklearn.metrics import balanced_accuracy_score, f1_score


@dataclass
class ThresholdResult:
    threshold: float
    score: float
    metric: str


def tune_threshold(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    thresholds: Sequence[float] | None = None,
    metric: str = "f1",
    min_positive: int = 5,
) -> ThresholdResult:
    """Validation verisinde en iyi eşiği seç.

    Parametreler
    ------------
    y_true, y_proba : aynı uzunlukta array
    thresholds : denenecek eşikler (None -> 0.05, 0.10, ..., 0.95)
    metric : "f1" veya "balanced_accuracy"
    min_positive : bu sayıdan az pozitif varsa metrik NaN -> atla
    """
    y_true = np.asarray(y_true).astype(int)
    y_proba = np.asarray(y_proba).astype(float)
    if y_true.size != y_proba.size:
        raise ValueError("y_true ve y_proba aynı uzunlukta olmalı")
    if thresholds is None:
        thresholds = np.arange(0.05, 0.96, 0.05)

    n_pos = int((y_true == 1).sum())
    n_neg = int((y_true == 0).sum())
    if n_pos < min_positive or n_neg < min_positive:
        # Yeterli veri yok -> varsayılan eşiği döndür, uyar
        return ThresholdResult(
            threshold=0.5, score=float("nan"),
            metric=f"{metric}_insufficient_data",
        )

    best_t, best_s = 0.5, -1.0
    for t in thresholds:
        y_pred = (y_proba >= t).astype(int)
        # Metriğe göre farklı sklearn imzaları kullanılır.
        try:
            if metric == "f1":
                s = float(f1_score(y_true, y_pred, zero_division=0))
            elif metric == "balanced_accuracy":
                # balanced_accuracy_score zero_division kabul etmez;
                # tek sınıf durumunda hata fırlatırsa atla.
                s = float(balanced_accuracy_score(y_true, y_pred))
            else:
                raise ValueError(f"Bilinmeyen metrik: {metric}")
        except Exception:  # noqa: BLE001
            continue
        if np.isfinite(s) and s > best_s:
            best_s = s
            best_t = float(t)
    if best_s < 0:
        return ThresholdResult(
            threshold=0.5, score=float("nan"),
            metric=f"{metric}_no_valid_threshold",
        )
    return ThresholdResult(threshold=best_t, score=best_s, metric=metric)


def sweep_thresholds(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    thresholds: Sequence[float] | None = None,
) -> list[dict]:
    """Tüm eşiklerde F1 / precision / recall / balanced accuracy tablosu."""
    from sklearn.metrics import precision_score, recall_score

    y_true = np.asarray(y_true).astype(int)
    y_proba = np.asarray(y_proba).astype(float)
    if thresholds is None:
        thresholds = np.arange(0.05, 0.96, 0.05)
    rows = []
    for t in thresholds:
        y_pred = (y_proba >= t).astype(int)
        rows.append({
            "threshold": float(t),
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
            "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        })
    return rows
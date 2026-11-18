"""Beş ufku sırayla koşan yardımcı."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd

from ..modeling.config import ModelConfig
from ..modeling.train import TrainResult, train_one_horizon


@dataclass
class MultiHorizonResult:
    per_horizon: Dict[int, TrainResult] = field(default_factory=dict)
    summary_rows: List[dict] = field(default_factory=list)


def run_all_horizons(
    features_df: pd.DataFrame,
    horizons: List[int],
    cfg: ModelConfig,
    logger=None,
) -> MultiHorizonResult:
    """Her ufuk için ayrı bir model eğit ve sonuçları topla.

    Her ufkun kendi eğitim seti vardır (etiketler farklı olduğundan split
    da ufuk bazlı yapılır). Modeller birbirinden bağımsızdır.
    """
    out = MultiHorizonResult()
    for h in horizons:
        try:
            result = train_one_horizon(features_df, h, cfg, logger=logger)
        except Exception as e:  # noqa: BLE001
            if logger:
                logger.error("Ufuk %d başarısız: %s", h, e)
            out.summary_rows.append({
                "horizon_min": h,
                "status": f"error:{type(e).__name__}",
                "n_train": 0, "n_test": 0,
                "f1": float("nan"), "roc_auc": float("nan"),
            })
            continue

        out.per_horizon[h] = result
        m = result.metrics_test
        out.summary_rows.append({
            "horizon_min": h,
            "status": result.status,
            "n_train": int(result.split.train.size),
            "n_test": int(result.split.test.size),
            "n_pos_test": m.n_positive,
            "n_neg_test": m.n_negative,
            "accuracy": m.accuracy,
            "balanced_accuracy": m.balanced_accuracy,
            "precision": m.precision,
            "recall": m.recall,
            "specificity": m.specificity,
            "f1": m.f1,
            "roc_auc": m.roc_auc,
            "pr_auc": m.pr_auc,
        })

    return out
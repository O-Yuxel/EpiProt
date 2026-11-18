"""Çoklu model × özellik grubu karşılaştırma.

Şartname Bölüm 12 (Deney A/B/C/D) ve Bölüm 6 (model karşılaştırma).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import List

import numpy as np
import pandas as pd

from ..modeling.config import ModelConfig
from ..modeling.train import TrainResult, train_one_horizon


FEATURE_GROUP_EXPERIMENTS = {
    "A_time": "time",
    "B_freq": "freq",
    "C_time_freq": "time+freq",
    "D_time_freq_complex": "time+freq+complex",
}

MODEL_NAMES = ("logistic", "random_forest", "hist_gb")


@dataclass
class ComparisonRow:
    feature_group_key: str
    feature_groups: str
    model_name: str
    horizon_min: int
    status: str
    n_train: int = 0
    n_test: int = 0
    n_pos_test: int = 0
    n_neg_test: int = 0
    accuracy: float = float("nan")
    balanced_accuracy: float = float("nan")
    precision: float = float("nan")
    recall: float = float("nan")
    specificity: float = float("nan")
    f1: float = float("nan")
    roc_auc: float = float("nan")
    pr_auc: float = float("nan")
    best_params: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        return {
            "feature_group_key": self.feature_group_key,
            "feature_groups": self.feature_groups,
            "model_name": self.model_name,
            "horizon_min": self.horizon_min,
            "status": self.status,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "n_pos_test": self.n_pos_test,
            "n_neg_test": self.n_neg_test,
            "accuracy": self.accuracy,
            "balanced_accuracy": self.balanced_accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "specificity": self.specificity,
            "f1": self.f1,
            "roc_auc": self.roc_auc,
            "pr_auc": self.pr_auc,
            "best_params": str(self.best_params),
        }


def run_comparison(
    features_df: pd.DataFrame,
    horizon_min: int,
    model_names: List[str] | None = None,
    feature_groups_keys: List[str] | None = None,
    random_search_n_iter: int = 10,
    cv_folds: int = 3,
    random_seed: int = 42,
    logger=None,
) -> tuple[List[TrainResult], pd.DataFrame]:
    """Verilen ufuk için tüm (model × özellik grubu) kombinasyonlarını çalıştır.

    Dönüş
    -----
    (train_results, comparison_df)
    """
    if model_names is None:
        model_names = list(MODEL_NAMES)
    if feature_groups_keys is None:
        feature_groups_keys = list(FEATURE_GROUP_EXPERIMENTS)

    results: List[TrainResult] = []
    rows: List[ComparisonRow] = []

    for fg_key, model_name in product(feature_groups_keys, model_names):
        cfg = ModelConfig(
            model_name=model_name,
            feature_groups=FEATURE_GROUP_EXPERIMENTS[fg_key],
            random_search_n_iter=random_search_n_iter,
            cv_folds=cv_folds,
            random_seed=random_seed,
        )
        try:
            result = train_one_horizon(features_df, horizon_min, cfg, logger=logger, out_dir=features_df.attrs.get("out_dir"))
        except Exception as e:  # noqa: BLE001
            if logger:
                logger.error(
                    "Hata [%s/%s/%dh]: %s", fg_key, model_name, horizon_min, e,
                )
            rows.append(ComparisonRow(
                feature_group_key=fg_key,
                feature_groups=FEATURE_GROUP_EXPERIMENTS[fg_key],
                model_name=model_name,
                horizon_min=horizon_min,
                status=f"error:{type(e).__name__}",
            ))
            continue

        m = result.metrics_test
        rows.append(ComparisonRow(
            feature_group_key=fg_key,
            feature_groups=FEATURE_GROUP_EXPERIMENTS[fg_key],
            model_name=model_name,
            horizon_min=horizon_min,
            status=result.status,
            n_train=int(result.split.train.size),
            n_test=int(result.split.test.size),
            n_pos_test=m.n_positive,
            n_neg_test=m.n_negative,
            accuracy=m.accuracy,
            balanced_accuracy=m.balanced_accuracy,
            precision=m.precision,
            recall=m.recall,
            specificity=m.specificity,
            f1=m.f1,
            roc_auc=m.roc_auc,
            pr_auc=m.pr_auc,
            best_params=result.best_params,
        ))
        results.append(result)

        if logger:
            logger.info(
                "Deney [%s/%s/%dh] | status=%s | test n=%d (pos=%d neg=%d) | f1=%s AUC=%s",
                fg_key, model_name, horizon_min, result.status,
                m.n_test, m.n_positive, m.n_negative,
                f"{m.f1:.3f}" if np.isfinite(m.f1) else "NaN",
                f"{m.roc_auc:.3f}" if np.isfinite(m.roc_auc) else "NaN",
            )

    comparison_df = pd.DataFrame([r.to_row() for r in rows])
    return results, comparison_df
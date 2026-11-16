"""Tek bir ufuk için uçtan uca eğitim."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.model_selection import RandomizedSearchCV

from .config import ModelConfig, resolve_feature_columns
from .metrics import ClassificationMetrics, compute_metrics
from .pipelines import build_pipeline, param_grid
from .save import ModelArtifact, save_artifact
from .splits import SplitIndices, assert_no_leakage, temporal_split


@dataclass
class TrainResult:
    horizon_min: int
    feature_columns: list[str]
    split: SplitIndices
    metrics_train: ClassificationMetrics
    metrics_test: ClassificationMetrics
    best_params: dict
    feature_groups: str = ""  # <-- BUNU EKLEYİN
    artifact_path: Optional[str] = None
    status: str = "ok"  # "ok" | "insufficient_data"

def train_one_horizon(
    features_df: pd.DataFrame,
    horizon_min: int,
    cfg: ModelConfig,
    out_dir=None,
    logger=None,
) -> TrainResult:
    """Verilen ufuk için pipeline eğit, validation, test, kaydet."""
    label_col = f"label_{horizon_min}min"
    if label_col not in features_df.columns:
        raise ValueError(f"'{label_col}' sütunu yok. Önce etiketleyin.")

    # Özellik sütunlarını belirle
    feat_cols = resolve_feature_columns(list(features_df.columns), cfg.feature_groups)
    if not feat_cols:
        raise ValueError(
            f"'{cfg.feature_groups}' grubunda hiç özellik bulunamadı"
        )

    # Etiketli satırları filtrele (NaN = dışlanmış)
    df = features_df[features_df[label_col].notna()].copy()
    n_pos = int((df[label_col] == 1.0).sum())
    n_neg = int((df[label_col] == 0.0).sum())
    if n_pos == 0 or n_neg == 0:
        if logger:
            logger.warning(
                "Ufuk %d: yetersiz veri (pos=%d, neg=%d)", horizon_min, n_pos, n_neg,
            )
        return TrainResult(
            horizon_min=horizon_min,
            feature_columns=feat_cols,
            split=SplitIndices(train=np.array([], dtype=int), test=np.array([], dtype=int)),
            metrics_train=ClassificationMetrics(
                horizon_min=horizon_min, n_test=0, n_positive=0, n_negative=0,
                status="insufficient_data",
            ),
            metrics_test=ClassificationMetrics(
                horizon_min=horizon_min, n_test=0, n_positive=0, n_negative=0,
                status="insufficient_data",
            ),
            best_params={},
            status="insufficient_data",
        )

    # Split
    split = temporal_split(df, label_col=label_col, test_fraction=cfg.test_fraction)
    assert_no_leakage(df, split)

    X_train = df.loc[split.train, feat_cols].to_numpy(dtype=float)
    y_train = df.loc[split.train, label_col].to_numpy(dtype=float).astype(int)
    X_test = df.loc[split.test, feat_cols].to_numpy(dtype=float)
    y_test = df.loc[split.test, label_col].to_numpy(dtype=float).astype(int)

    if y_train.min() == y_train.max():
        if logger:
            logger.warning(
                "Ufuk %d: eğitim setinde tek sınıf var (y_train unique=%s)",
                horizon_min, np.unique(y_train),
            )
        return TrainResult(
            horizon_min=horizon_min,
            feature_columns=feat_cols,
            split=split,
            metrics_train=ClassificationMetrics(
                horizon_min=horizon_min, n_test=0, n_positive=0, n_negative=0,
                status="single_class_train",
            ),
            metrics_test=ClassificationMetrics(
                horizon_min=horizon_min, n_test=0, n_positive=0, n_negative=0,
                status="single_class_train",
            ),
            best_params={},
            status="single_class_train",
        )

    # RandomizedSearchCV
    pipe = build_pipeline(cfg, n_features_hint=len(feat_cols))
    grid = param_grid(cfg.model_name)
    n_iter = min(cfg.random_search_n_iter, _grid_size(grid))
    search = RandomizedSearchCV(
        pipe, grid,
        n_iter=n_iter,
        cv=min(cfg.cv_folds, _min_class_count(y_train)),
        scoring="average_precision",
        random_state=cfg.random_seed,
        n_jobs=-1,
        refit=True,
    )
    search.fit(X_train, y_train)
    best_pipe = search.best_estimator_

    # Train metrikleri (overfit kontrolü için)
    y_train_proba = best_pipe.predict_proba(X_train)[:, 1]
    y_train_pred = best_pipe.predict(X_train)
    metrics_train = compute_metrics(y_train, y_train_pred, y_train_proba, horizon_min)

    # Test metrikleri
    y_test_proba = best_pipe.predict_proba(X_test)[:, 1]
    y_test_pred = best_pipe.predict(X_test)
    metrics_test = compute_metrics(y_test, y_test_pred, y_test_proba, horizon_min)

    # Kaydet
    artifact_path = None
    if out_dir is not None:
        training_edfs = sorted(df.loc[split.train, "edf_path"].unique().tolist())
        artifact = ModelArtifact(
            model=best_pipe,
            horizon_min=horizon_min,
            feature_columns=feat_cols,
            feature_groups=cfg.feature_groups,
            model_name=cfg.model_name,
            window_seconds=float(df["window_duration_s"].iloc[0]) if "window_duration_s" in df.columns else float("nan"),
            prediction_gap_minutes=5.0,  # çağıran doldurmalı; meta bilgi
            negative_exclusion_hours=4.0,
            training_edfs=training_edfs,
            random_seed=cfg.random_seed,
            extra={"best_params": search.best_params_},
        )
        p = save_artifact(artifact, out_dir)
        artifact_path = str(p)

    if logger:
        logger.info(
            "Ufuk %d | model=%s | train=%d test=%d | test recall=%.3f precision=%.3f AUC=%.3f",
            horizon_min, cfg.model_name, len(y_train), len(y_test),
            metrics_test.recall, metrics_test.precision, metrics_test.roc_auc,
        )

    return TrainResult(
        horizon_min=horizon_min,
        feature_columns=feat_cols,
        split=split,
        metrics_train=metrics_train,
        metrics_test=metrics_test,
        best_params=search.best_params_,
        feature_groups=cfg.feature_groups,
        artifact_path=artifact_path,
        status="ok",
    )


def _grid_size(grid: dict) -> int:
    size = 1
    for v in grid.values():
        size *= len(v)
    return size


def _min_class_count(y: np.ndarray) -> int:
    return int(min((y == 0).sum(), (y == 1).sum()))
"""pipelines.py için birim testleri."""
from __future__ import annotations

import numpy as np
import pytest
from sklearn.pipeline import Pipeline

from epiprot.modeling.config import ModelConfig, resolve_feature_columns
from epiprot.modeling.pipelines import build_pipeline, param_grid


def test_build_logistic_pipeline() -> None:
    cfg = ModelConfig(model_name="logistic")
    pipe = build_pipeline(cfg)
    assert isinstance(pipe, Pipeline)
    step_names = [s[0] for s in pipe.steps]
    assert "imputer" in step_names
    assert "model" in step_names


def test_build_random_forest_pipeline() -> None:
    cfg = ModelConfig(model_name="random_forest", scale_features=False)
    pipe = build_pipeline(cfg)
    assert "scaler" not in [s[0] for s in pipe.steps]


def test_build_hist_gb_pipeline() -> None:
    cfg = ModelConfig(model_name="hist_gb")
    pipe = build_pipeline(cfg)
    assert "model" in [s[0] for s in pipe.steps]


def test_unknown_model_raises() -> None:
    cfg = ModelConfig(model_name="svm_xyz")
    with pytest.raises(ValueError, match="Bilinmeyen model"):
        build_pipeline(cfg)


def test_pipeline_learns_imputation_on_train_only() -> None:
    # Eğitimde median 1.0; testte NaN -> 1.0 ile doldurulmalı
    X_train = np.array([[1.0], [2.0], [np.nan], [4.0], [5.0]])
    y_train = np.array([0, 0, 1, 1, 1])
    cfg = ModelConfig(model_name="logistic", scale_features=False)
    pipe = build_pipeline(cfg)
    pipe.fit(X_train, y_train)
    imputer = pipe.named_steps["imputer"]
    # Median: [1, 2, 4, 5] -> 3.0 (NaN atılınca)
    assert np.isclose(imputer.statistics_[0], 3.0)


def test_param_grid_shapes() -> None:
    for m in ("logistic", "random_forest", "hist_gb"):
        g = param_grid(m)
        assert isinstance(g, dict) and len(g) > 0


def test_resolve_feature_columns() -> None:
    cols = [
        "edf_path", "channel", "window_start_s",
        "time_mean_uv", "time_std_uv",
        "freq_alpha_abs_uv2",
        "complex_hjorth_mobility",
        "qc_std_uv",
        "label_30min", "label_reason_30min",
    ]
    assert resolve_feature_columns(cols, "time") == ["time_mean_uv", "time_std_uv"]
    assert "freq_alpha_abs_uv2" in resolve_feature_columns(cols, "freq")
    assert "complex_hjorth_mobility" in resolve_feature_columns(cols, "complex")
    # qc hiçbir grupta yok
    for g in ("time", "freq", "complex", "time+freq+complex"):
        assert "qc_std_uv" not in resolve_feature_columns(cols, g)
    with pytest.raises(ValueError):
        resolve_feature_columns(cols, "bad_group")
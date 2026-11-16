"""train.py uçtan uca testi (sentetik tablo, EDF gerekmez)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from epiprot.modeling.config import ModelConfig
from epiprot.modeling.train import train_one_horizon


def _make_feature_table(
    n_windows: int = 100,
    n_channels: int = 2,
    seed: int = 0,
) -> pd.DataFrame:
    """Sentetik özellik tablosu — etiketleme aşamasını taklit eder.

    Pozitif pencerelerin bazı özellikleri sistematik olarak yüksektir, böylece
    model öğrenebilir. Bu test sadece boru hattının çalıştığını doğrular;
    bilimsel performans kanıtı değildir.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for w in range(n_windows):
        for c in range(n_channels):
            # Etiket: her 5. pencere pozitif (sentetik)
            is_pos = 1 if w % 5 == 0 else 0
            base = 20.0 + (5.0 if is_pos else 0.0)
            rows.append({
                "edf_path": "/a/chb01_01.edf",
                "patient_id": "chb01",
                "channel": f"CH{c}",
                "window_index": w,
                "window_start_s": float(w * 10),
                "window_end_s": float(w * 10 + 10),
                "window_duration_s": 10.0,
                "sfreq_used": 128.0,
                "n_samples": 1280,
                "time_mean_uv": rng.normal(0, 1),
                "time_std_uv": rng.normal(base, 3.0),
                "time_rms_uv": rng.normal(base, 3.0),
                "time_line_length_uv": rng.normal(base * 10, 30.0),
                "freq_alpha_abs_uv2": rng.normal(base, 5.0),
                "freq_beta_abs_uv2": rng.normal(base, 5.0),
                "complex_hjorth_mobility": rng.normal(0.1, 0.02),
                "complex_shannon_entropy_bits": rng.normal(3.0, 0.3),
                "qc_std_uv": 20.0,
                "qc_ptp_uv": 100.0,
                "label_30min": float(is_pos),
                "label_45min": float(is_pos),
                "label_60min": float(is_pos),
                "label_75min": float(is_pos),
                "label_90min": float(is_pos),
            })
    return pd.DataFrame(rows)


def test_train_one_horizon_runs() -> None:
    df = _make_feature_table(n_windows=100)
    cfg = ModelConfig(model_name="logistic", random_search_n_iter=3, cv_folds=2)
    result = train_one_horizon(df, horizon_min=30, cfg=cfg)
    assert result.status == "ok"
    assert result.horizon_min == 30
    assert len(result.feature_columns) > 0
    assert result.split.train.size > 0
    assert result.split.test.size > 0
    # Test metrikleri hesaplanmış olmalı
    assert result.metrics_test.n_test > 0
    assert np.isfinite(result.metrics_test.accuracy) or result.metrics_test.status != "ok"


def test_train_insufficient_data_returns_status() -> None:
    df = _make_feature_table(n_windows=100)
    df["label_30min"] = np.nan
    cfg = ModelConfig()
    result = train_one_horizon(df, horizon_min=30, cfg=cfg)
    assert result.status == "insufficient_data"


def test_train_all_five_horizons() -> None:
    df = _make_feature_table(n_windows=100)
    cfg = ModelConfig(random_search_n_iter=2, cv_folds=2)
    for h in [30, 45, 60, 75, 90]:
        r = train_one_horizon(df, horizon_min=h, cfg=cfg)
        assert r.horizon_min == h


def test_train_saves_artifact(tmp_path) -> None:
    df = _make_feature_table(n_windows=100)
    cfg = ModelConfig(random_search_n_iter=2, cv_folds=2)
    result = train_one_horizon(df, horizon_min=30, cfg=cfg, out_dir=tmp_path)
    assert result.artifact_path is not None
    assert (tmp_path / "model_30min.joblib").exists()
    assert (tmp_path / "model_30min.json").exists()
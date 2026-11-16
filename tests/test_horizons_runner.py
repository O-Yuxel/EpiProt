"""experiments/horizons.py için birim testleri."""
from __future__ import annotations

import numpy as np
import pandas as pd

from epiprot.experiments.horizons import run_all_horizons
from epiprot.modeling.config import ModelConfig


def _make_synth_table(n_windows: int = 80, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for w in range(n_windows):
        is_pos = int(w % 4 == 0)
        base = 20.0 + (5.0 if is_pos else 0.0)
        row = {
            "edf_path": "/a/e.edf",
            "patient_id": "chb01",
            "channel": "CH0",
            "window_index": w,
            "window_start_s": float(w * 10),
            "window_end_s": float(w * 10 + 10),
            "window_duration_s": 10.0,
            "sfreq_used": 128.0,
            "n_samples": 1280,
            "time_std_uv": rng.normal(base, 3.0),
            "time_mean_uv": rng.normal(0, 1),
            "freq_alpha_abs_uv2": rng.normal(base, 5.0),
            "complex_shannon_entropy_bits": rng.normal(3.0, 0.3),
        }
        for h in (30, 45, 60, 75, 90):
            row[f"label_{h}min"] = float(is_pos)
        rows.append(row)
    return pd.DataFrame(rows)


def test_run_all_horizons_iterates() -> None:
    df = _make_synth_table()
    cfg = ModelConfig(model_name="logistic", feature_groups="time+freq",
                      random_search_n_iter=2, cv_folds=2)
    out = run_all_horizons(df, horizons=[30, 45, 60], cfg=cfg)
    assert set(out.per_horizon.keys()) == {30, 45, 60}
    assert len(out.summary_rows) == 3


def test_run_all_horizons_handles_missing_label() -> None:
    df = _make_synth_table()
    df = df.drop(columns=["label_45min"])
    cfg = ModelConfig(model_name="logistic", feature_groups="time",
                      random_search_n_iter=2, cv_folds=2)
    out = run_all_horizons(df, horizons=[30, 45], cfg=cfg)
    # 30 ok, 45 hata
    assert 30 in out.per_horizon
    status_45 = next(r for r in out.summary_rows if r["horizon_min"] == 45)
    assert status_45["status"].startswith("error")
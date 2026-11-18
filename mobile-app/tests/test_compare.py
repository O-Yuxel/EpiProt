"""compare.py için birim testleri."""
from __future__ import annotations

import numpy as np
import pandas as pd

from epiprot.experiments.compare import run_comparison


def _make_synth_table(n_windows: int = 80, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for w in range(n_windows):
        is_pos = int(w % 4 == 0)
        base = 20.0 + (5.0 if is_pos else 0.0)
        rows.append({
            "edf_path": "/a/e.edf",
            "patient_id": "chb01",
            "channel": "CH0",
            "window_index": w,
            "window_start_s": float(w * 10),
            "window_end_s": float(w * 10 + 10),
            "window_duration_s": 10.0,
            "sfreq_used": 128.0,
            "n_samples": 1280,
            "time_mean_uv": rng.normal(0, 1),
            "time_std_uv": rng.normal(base, 3.0),
            "freq_alpha_abs_uv2": rng.normal(base, 5.0),
            "complex_shannon_entropy_bits": rng.normal(3.0, 0.3),
            "label_30min": float(is_pos),
        })
    return pd.DataFrame(rows)


def test_run_comparison_returns_rows() -> None:
    df = _make_synth_table()
    results, cmp_df = run_comparison(
        df, horizon_min=30,
        model_names=["logistic"],
        feature_groups_keys=["A_time", "C_time_freq"],
        random_search_n_iter=2,
        cv_folds=2,
    )
    assert len(cmp_df) == 2  # 1 model × 2 feature group
    assert set(cmp_df["feature_group_key"]) == {"A_time", "C_time_freq"}
    assert (cmp_df["horizon_min"] == 30).all()
    # Her iki deney de "ok" dönmeli
    assert (cmp_df["status"] == "ok").all()


def test_run_comparison_handles_error_gracefully() -> None:
    df = _make_synth_table()
    # Etikette tek sınıf -> eğitim başarısız olur
    df["label_30min"] = 0.0
    _, cmp_df = run_comparison(
        df, horizon_min=30,
        model_names=["logistic"],
        feature_groups_keys=["A_time"],
        random_search_n_iter=1,
        cv_folds=2,
    )
    # status "ok" değil ama satır üretilmiş
    assert len(cmp_df) == 1
    assert cmp_df.iloc[0]["status"] != "ok"
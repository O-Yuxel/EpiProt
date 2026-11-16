"""splits.py için birim testleri."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from epiprot.modeling.splits import (
    assert_no_leakage,
    patient_split,
    temporal_split,
)


def _make_labeled(n_windows: int = 10, n_channels: int = 2, edf: str = "/a/e.edf") -> pd.DataFrame:
    rows = []
    for w in range(n_windows):
        for c in range(n_channels):
            rows.append({
                "edf_path": edf,
                "patient_id": "chb01",
                "channel": f"CH{c}",
                "window_start_s": float(w * 10),
                "window_end_s": float(w * 10 + 10),
                "label_30min": float(w % 2),  # alternatif 0/1
            })
    return pd.DataFrame(rows)


def test_temporal_split_holds_all_channels_together() -> None:
    df = _make_labeled(n_windows=10, n_channels=2)
    split = temporal_split(df, "label_30min", test_fraction=0.2)
    assert_no_leakage(df, split)
    # Aynı pencerenin tüm kanalları aynı tarafta
    train_ws = df.loc[split.train, "window_start_s"].unique()
    test_ws = df.loc[split.test, "window_start_s"].unique()
    assert set(train_ws).isdisjoint(set(test_ws))


def test_temporal_split_respects_order() -> None:
    df = _make_labeled(n_windows=10, n_channels=1)
    split = temporal_split(df, "label_30min", test_fraction=0.2)
    train_max = df.loc[split.train, "window_start_s"].max()
    test_min = df.loc[split.test, "window_start_s"].min()
    assert train_max < test_min


def test_temporal_split_rejects_bad_fraction() -> None:
    df = _make_labeled(n_windows=10)
    with pytest.raises(ValueError):
        temporal_split(df, "label_30min", test_fraction=0.0)
    with pytest.raises(ValueError):
        temporal_split(df, "label_30min", test_fraction=1.0)


def test_temporal_split_rejects_all_nan() -> None:
    df = _make_labeled(n_windows=5)
    df["label_30min"] = np.nan
    with pytest.raises(ValueError, match="hiç etiketli"):
        temporal_split(df, "label_30min")


def test_patient_split() -> None:
    df1 = _make_labeled(n_windows=5, edf="/a/chb01_01.edf")
    df1["patient_id"] = "chb01"
    df2 = _make_labeled(n_windows=5, edf="/a/chb02_01.edf")
    df2["patient_id"] = "chb02"
    df = pd.concat([df1, df2], ignore_index=True)
    split = patient_split(df, "label_30min", test_patient_ids=["chb02"])
    train_pat = set(df.loc[split.train, "patient_id"])
    test_pat = set(df.loc[split.test, "patient_id"])
    assert train_pat == {"chb01"}
    assert test_pat == {"chb02"}


def test_assert_no_leakage_detects_overlap() -> None:
    df = _make_labeled(n_windows=4, n_channels=2)
    # Kasıtlı sızıntı: aynı pencere hem train hem test
    split = type("S", (), {})()
    split.train = np.array([0, 1, 2, 3])
    split.test = np.array([0, 4, 5])  # 0 her ikisinde
    with pytest.raises(AssertionError, match="sızıntı"):
        assert_no_leakage(df, split)
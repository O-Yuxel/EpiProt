"""apply.py için birim testleri."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from epiprot.labeling.apply import (
    LabelReport,
    apply_labels,
    reports_to_dataframe,
)
from epiprot.labeling.config import LabelConfig
from epiprot.labeling.horizons import Seizure


def _make_features(n_windows: int = 10, n_channels: int = 2, edf_path: str = "/a/chb01_01.edf") -> pd.DataFrame:
    rows = []
    for w in range(n_windows):
        for c in range(n_channels):
            rows.append({
                "edf_path": edf_path,
                "channel": f"CH{c}",
                "window_index": w,
                "window_start_s": float(w * 10),
                "window_end_s": float(w * 10 + 10),
                "feature_x": float(w + c),
            })
    return pd.DataFrame(rows)


def test_apply_labels_basic() -> None:
    df = _make_features(n_windows=10)  # 100 sn
    # 60 sn sonra nöbet başlıyor -> 30 dk ufku için tüm pencereler pozitif
    # (0. pencere biter: 10, delta=50 sn = 0.83 dk -> 5 dk'dan küçük, dışla)
    # Daha temiz: nöbeti 20 dk sonra başlat
    sz = Seizure(start_s=20 * 60.0, end_s=20 * 60.0 + 30.0)
    cfg = LabelConfig(horizons_minutes=[30])
    out, reports = apply_labels(df, {"/a/chb01_01.edf": [sz]}, cfg)

    # İlk 9 pencere (0-100 sn) 20 dk sonra nöbet görmeli -> pozitif
    # 9. pencere biter: 100 sn, delta=20*60-100 = 1100 sn = 18.3 dk -> pozitif
    pos_windows = out[out["label_30min"] == 1.0]["window_index"].unique()
    assert set(pos_windows) == set(range(10))
    assert len(reports) == 1
    assert reports[0].horizon == 30
    assert reports[0].n_positive == 10 * 2

def test_apply_labels_unknown_edf_negative() -> None:
    df = _make_features(n_windows=5)
    # seizures_by_edf boş -> tüm pencereler negatif (ileride nöbet yok)
    out, reports = apply_labels(df, {}, LabelConfig(horizons_minutes=[30]))
    assert (out["label_30min"] == 0.0).all()
    assert (out["label_reason_30min"] == "negative_no_future_seizure").all()


def test_apply_labels_gap_excluded() -> None:
    df = _make_features(n_windows=5)  # pencereler: 0-10, 10-20, 20-30, 30-40, 40-50 sn
    sz = Seizure(start_s=30.0, end_s=40.0)
    out, _ = apply_labels(
        df, {"/a/chb01_01.edf": [sz]}, LabelConfig(horizons_minutes=[30])
    )
    # window_index=2 -> [20,30]: nöbetle temas yok, ama delta=0 -> gap -> NaN
    rows2 = out[out["window_index"] == 2]
    assert rows2["label_30min"].isna().all()
    assert (rows2["label_reason_30min"] == "excluded_gap").all()
    # window_index=3 -> [30,40]: nöbet içinde -> touching -> NaN
    rows3 = out[out["window_index"] == 3]
    assert rows3["label_30min"].isna().all()
    assert (rows3["label_reason_30min"] == "excluded_touching_seizure").all()
    # window_index=4 -> [40,50]: nöbet sonrası -> post_ictal (4 saat) -> NaN
    rows4 = out[out["window_index"] == 4]
    assert rows4["label_30min"].isna().all()
    assert (rows4["label_reason_30min"] == "excluded_post_ictal").all()


def test_apply_labels_missing_column_raises() -> None:
    df = pd.DataFrame({"edf_path": ["/a.edf"]})
    with pytest.raises(ValueError, match="Eksik sütunlar"):
        apply_labels(df, {}, LabelConfig())


def test_reports_to_dataframe() -> None:
    rep = LabelReport(
        horizon=30, n_positive=10, n_negative=80, n_excluded=10, n_total=100,
        exclusion_reasons={"excluded_gap": 5, "excluded_post_ictal": 5},
    )
    df = reports_to_dataframe([rep])
    assert df.shape[0] == 1
    assert df.iloc[0]["horizon_min"] == 30
    assert df.iloc[0]["n_positive"] == 10
    assert df.iloc[0]["excl_excluded_gap"] == 5


def test_all_five_horizons_columns_present() -> None:
    df = _make_features(n_windows=3)
    cfg = LabelConfig()  # varsayılan 5 ufuk
    out, reports = apply_labels(df, {}, cfg)
    for h in [30, 45, 60, 75, 90]:
        assert f"label_{h}min" in out.columns
        assert f"label_reason_{h}min" in out.columns
    assert len(reports) == 5
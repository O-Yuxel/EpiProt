"""extractor.py uçtan uca testi (sentetik EDF)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from epiprot.features.config import FeatureConfig
from epiprot.features.extractor import extract_features_from_edf, extract_many
from tests.fixtures.make_synthetic import _make_edf


def _make_one_edf(tmp_path: Path, duration_s: float = 30.0) -> Path:
    p = tmp_path / "chb01_01.edf"
    _make_edf(
        p, duration_s=duration_s, sfreq=128.0,
        eeg_channels=["FP1-F7", "C3-P3"],
        extra_channels={"ECG": "ecg"},
    )
    return p


def test_extract_features_from_edf_basic(tmp_path: Path) -> None:
    p = _make_one_edf(tmp_path, duration_s=30.0)
    cfg = FeatureConfig(window_seconds=10.0, overlap=0.0)
    rec = extract_features_from_edf(p, cfg, patient_id="chb01")

    # 3 pencere * 2 EEG kanal = 6 satır
    assert rec.n_windows == 3
    assert len(rec.channels_used) == 2
    assert len(rec.feature_df) == 6

    # ECG dışlanmalı (n_channels_excluded >= 1)
    assert rec.n_channels_excluded >= 1

    df = rec.feature_df
    # Zaman alanı sütunları
    assert (df["time_std_uv"] > 0).all()
    # Frekans alanı sütunları
    assert "freq_alpha_abs_uv2" in df.columns
    # Karmaşıklık sütunları
    assert "complex_shannon_entropy_bits" in df.columns
    # Meta veri
    assert (df["patient_id"] == "chb01").all()
    assert set(df["channel"].unique()) == {"FP1-F7", "C3-P3"}
    assert df["window_start_s"].tolist() == [0.0, 0.0, 10.0, 10.0, 20.0, 20.0]


def test_extract_features_units_uv(tmp_path: Path) -> None:
    """Zaman alanı özellikleri µV cinsinden ve sıfırdan farklı olmalı."""
    p = _make_one_edf(tmp_path, duration_s=10.0)
    cfg = FeatureConfig(window_seconds=10.0)
    rec = extract_features_from_edf(p, cfg)
    df = rec.feature_df
    # Sentetik sinyal ~20 µV std; volt cinsine düşerse std ~0.00002 olur.
    # µV'da std > 1 olmalı.
    assert (df["time_std_uv"] > 1.0).all()


def test_extract_features_channel_subset(tmp_path: Path) -> None:
    p = _make_one_edf(tmp_path, duration_s=20.0)
    cfg = FeatureConfig(window_seconds=10.0)
    rec = extract_features_from_edf(p, cfg, channel_subset=["C3-P3"])
    assert rec.channels_used == ["C3-P3"]
    assert (rec.feature_df["channel"] == "C3-P3").all()


def test_extract_many_collects_failures(tmp_path: Path) -> None:
    p_good = _make_one_edf(tmp_path, duration_s=10.0)
    p_bad = tmp_path / "corrupt.edf"
    p_bad.write_bytes(b"not edf")
    cfg = FeatureConfig(window_seconds=10.0)
    df, failures = extract_many([p_good, p_bad], cfg, patient_id_of=lambda _: "chb01")
    assert len(df) > 0
    assert len(failures) == 1
    assert "corrupt.edf" in failures[0]["edf_path"]
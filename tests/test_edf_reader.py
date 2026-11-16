"""edf_reader.py için birim testleri."""
from __future__ import annotations

from pathlib import Path

from epiprot.data.edf_reader import classify_channels, read_edf_info
from tests.fixtures.make_synthetic import _make_edf


def test_classify_channels() -> None:
    names = ["FP1-F7", "C3-P3", "ECG", "EOG-L", "EEG-REF", "XYZ123"]
    eeg, non_eeg, unmatched = classify_channels(names)
    assert "FP1-F7" in eeg
    assert "C3-P3" in eeg
    assert "EEG-REF" in eeg
    assert "ECG" in non_eeg
    assert "EOG-L" in non_eeg
    assert "XYZ123" in unmatched


def test_read_edf_info(tmp_path: Path) -> None:
    p = tmp_path / "chb01_01.edf"
    _make_edf(
        p, duration_s=10.0, sfreq=128.0,
        eeg_channels=["FP1-F7", "C3-P3"],
        extra_channels={"ECG": "ecg"},
    )
    info = read_edf_info(p)
    assert info.ok, info.error
    assert info.sampling_rate_hz == 128.0
    assert 9.9 < info.duration_s < 10.1
    assert "FP1-F7" in info.eeg_channels
    assert "C3-P3" in info.eeg_channels
    assert "ECG" in info.non_eeg_channels


def test_read_edf_info_missing(tmp_path: Path) -> None:
    info = read_edf_info(tmp_path / "does_not_exist.edf")
    assert not info.ok
    assert info.error is not None
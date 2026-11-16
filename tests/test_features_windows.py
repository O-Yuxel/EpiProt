"""windows.py için birim testleri."""
from __future__ import annotations

import pytest

from epiprot.features.windows import make_windows, window_sample_bounds


def test_make_windows_no_overlap() -> None:
    ws = make_windows(total_duration_s=100.0, window_seconds=10.0, overlap=0.0)
    assert len(ws) == 10
    assert ws[0].start_s == 0.0 and ws[0].end_s == 10.0
    assert ws[-1].start_s == 90.0 and ws[-1].end_s == 100.0


def test_make_windows_drops_incomplete_tail() -> None:
    ws = make_windows(total_duration_s=105.0, window_seconds=10.0)
    assert len(ws) == 10  # son 5 sn atılır


def test_make_windows_overlap() -> None:
    ws = make_windows(total_duration_s=30.0, window_seconds=10.0, overlap=0.5)
    # step = 5s; pencereler: 0-10, 5-15, 10-20, 15-25, 20-30
    assert len(ws) == 5
    assert ws[1].start_s == 5.0 and ws[1].end_s == 15.0


def test_make_windows_invalid_params() -> None:
    with pytest.raises(ValueError):
        make_windows(total_duration_s=10.0, window_seconds=0.0)
    with pytest.raises(ValueError):
        make_windows(total_duration_s=10.0, window_seconds=5.0, overlap=1.0)


def test_window_sample_bounds_clip() -> None:
    ws = make_windows(total_duration_s=20.0, window_seconds=10.0)
    a, b = window_sample_bounds(ws[0], sfreq=128.0, n_samples=2560)
    assert (a, b) == (0, 1280)
    # Son pencereyi hafifçe taşan sınırları klipsin
    a, b = window_sample_bounds(ws[-1], sfreq=128.0, n_samples=2500)
    assert b == 2500
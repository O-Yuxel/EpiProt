"""time_domain.py için birim testleri."""
from __future__ import annotations

import numpy as np

from epiprot.features.time_domain import (
    compute_time_domain,
    line_length_uv,
    zero_crossing_rate,
)


def test_zero_crossing_rate_alternating() -> None:
    # +1, -1, +1, -1 -> 3 geçiş / (4-1) = 1.0
    x = np.array([1.0, -1.0, 1.0, -1.0])
    assert zero_crossing_rate(x) == 1.0


def test_line_length() -> None:
    x = np.array([0.0, 1.0, 3.0, 3.0])
    assert line_length_uv(x) == 1.0 + 2.0 + 0.0


def test_time_domain_basic() -> None:
    rng = np.random.default_rng(0)
    x = rng.standard_normal(1280) * 20.0  # µV
    f = compute_time_domain(x)
    assert "time_mean_uv" in f and "time_rms_uv" in f
    assert abs(f["time_mean_uv"]) < 5.0  # ~0 ortalama
    assert f["time_std_uv"] > 0
    assert f["time_peak_to_peak_uv"] > 0
    assert 0.0 <= f["time_zero_crossing_rate"] <= 1.0


def test_time_domain_handles_empty() -> None:
    f = compute_time_domain(np.array([]))
    # Boş giriş: NaN döner, sessizce 0 değil.
    assert np.isnan(f["time_mean_uv"])
    assert np.isnan(f["time_std_uv"])
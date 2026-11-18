"""complexity.py için birim testleri."""
from __future__ import annotations

import numpy as np

from epiprot.features.complexity import (
    compute_complexity,
    hjorth_params,
    shannon_entropy_hist,
)


def test_shannon_entropy_constant_signal() -> None:
    x = np.zeros(1000)
    assert shannon_entropy_hist(x) == 0.0


def test_shannon_entropy_noise_higher_than_constant() -> None:
    rng = np.random.default_rng(0)
    const_h = shannon_entropy_hist(np.zeros(1000))
    noise_h = shannon_entropy_hist(rng.standard_normal(1000))
    assert noise_h > const_h


def test_hjorth_sinusoid_has_plausible_values() -> None:
    sfreq = 128.0
    t = np.arange(0, 10.0, 1.0 / sfreq)
    x = 20.0 * np.sin(2 * np.pi * 10.0 * t)
    act, mob, comp = hjorth_params(x, sfreq=sfreq)
    assert act > 0
    assert mob > 0
    assert comp > 0
    # Sinüs için mobility ≈ 2πf/sfreq (normalize edilmemiş tanım)
    # Sadece sıralama kontrolü yeterli.
    assert comp < 2.0


def test_hjorth_handles_constant() -> None:
    x = np.ones(1000)
    act, mob, comp = hjorth_params(x, sfreq=128.0)
    assert act == 0.0
    assert np.isnan(mob)
    assert np.isnan(comp)


def test_compute_complexity_keys() -> None:
    x = np.random.default_rng(0).standard_normal(1000) * 10.0
    f = compute_complexity(x, sfreq=128.0)
    for k in (
        "complex_shannon_entropy_bits",
        "complex_hjorth_activity_uv2",
        "complex_hjorth_mobility",
        "complex_hjorth_complexity",
    ):
        assert k in f
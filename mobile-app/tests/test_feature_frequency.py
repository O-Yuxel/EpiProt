"""frequency_domain.py için birim testleri."""
from __future__ import annotations

import numpy as np

from epiprot.features.frequency_domain import (
    band_power,
    compute_frequency_domain,
    compute_welch_psd,
)
from epiprot.features.config import DEFAULT_BANDS


def test_welch_recovers_known_frequency() -> None:
    # 10 Hz sinüs, sfreq=128 -> PSD zirvesi 10 Hz civarında olmalı
    sfreq = 128.0
    t = np.arange(0, 10.0, 1.0 / sfreq)
    x = 20.0 * np.sin(2 * np.pi * 10.0 * t)
    f, pxx = compute_welch_psd(x, sfreq=sfreq)
    peak_hz = f[np.argmax(pxx)]
    assert 9.0 <= peak_hz <= 11.0


def test_band_power_alpha_dominates_for_10hz_sinusoid() -> None:
    sfreq = 128.0
    t = np.arange(0, 10.0, 1.0 / sfreq)
    x = 20.0 * np.sin(2 * np.pi * 10.0 * t)
    feats = compute_frequency_domain(x, sfreq=sfreq, bands=DEFAULT_BANDS)
    # Alpha (8-13) gücü, delta, theta, beta ve gamma'dan büyük olmalı
    alpha = feats["freq_alpha_abs_uv2"]
    delta = feats["freq_delta_abs_uv2"]
    beta = feats["freq_beta_abs_uv2"]
    assert np.isfinite(alpha) and alpha > delta and alpha > beta
    assert feats["freq_alpha_rel"] > 0.5


def test_band_power_nyquist_clipping() -> None:
    # sfreq=60 -> Nyquist=30; gamma (30-40) etkili olmamalı
    sfreq = 60.0
    t = np.arange(0, 10.0, 1.0 / sfreq)
    x = np.random.default_rng(0).standard_normal(t.size) * 10.0
    feats = compute_frequency_domain(x, sfreq=sfreq, bands=DEFAULT_BANDS)
    assert np.isnan(feats["freq_gamma_abs_uv2"])


def test_band_power_returns_nan_when_band_outside() -> None:
    f = np.array([0.0, 1.0, 2.0])
    pxx = np.array([1.0, 1.0, 1.0])
    assert np.isnan(band_power(f, pxx, lo=50.0, hi=60.0))
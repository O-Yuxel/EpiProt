"""Frekans alanı EEG özellikleri (Welch PSD)."""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
from scipy.signal import welch


def _effective_bands(
    bands: Dict[str, Tuple[float, float]],
    sfreq: float,
    freq_resolution_ok: bool = True,
) -> Dict[str, Tuple[float, float]]:
    """Nyquist üstü bantları at; alt sınır üst sınırı geçerse bant düşer."""
    nyq = sfreq / 2.0
    out: Dict[str, Tuple[float, float]] = {}
    for name, (lo, hi) in bands.items():
        lo2 = max(lo, 0.0)
        hi2 = min(hi, nyq)
        if hi2 > lo2:
            out[name] = (lo2, hi2)
    return out


def compute_welch_psd(
    x_uv: np.ndarray,
    sfreq: float,
    nperseg: int | None = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Welch PSD döndür (f, Pxx). Pxx birimi µV²/Hz."""
    n = x_uv.size
    if n < 8:
        return np.array([np.nan]), np.array([np.nan])
    if nperseg is None:
        nperseg = int(min(n, max(64, 2 ** int(np.log2(max(64, sfreq))))))
    nperseg = int(min(nperseg, n))
    noverlap = min(nperseg // 2, nperseg - 1)
    f, pxx = welch(
        x_uv, fs=sfreq, window="hann", nperseg=nperseg,
        noverlap=noverlap, detrend="constant", scaling="density",
    )
    return f, pxx


def band_power(
    f: np.ndarray, pxx: np.ndarray, lo: float, hi: float
) -> float:
    """Bir banttaki güç (µV²). f ve pxx aynı uzunlukta olmalı."""
    if f.size < 2 or pxx.size != f.size or not np.isfinite(pxx).any():
        return float("nan")
    # Bant maskesi: lo <= f <= hi
    mask = (f >= lo) & (f <= hi)
    if not mask.any():
        return float("nan")
    # Trapez entegrasyon (µV²/Hz * Hz = µV²)
    return float(np.trapezoid(pxx[mask], f[mask]))


def compute_frequency_domain(
    x_uv: np.ndarray,
    sfreq: float,
    bands: Dict[str, Tuple[float, float]],
    nperseg: int | None = None,
) -> dict[str, float]:
    """Bir kanal için frekans alanı özellikleri.

    Mutlak güç: her banttaki µV² gücü.
    Göreli güç: bant gücü / [0.5, min(40, Nyquist)] aralığındaki toplam güç.
    """
    f, pxx = compute_welch_psd(x_uv, sfreq=sfreq, nperseg=nperseg)
    out: dict[str, float] = {}

    if f.size < 2 or not np.isfinite(pxx).any():
        for name in bands:
            out[f"freq_{name}_abs_uv2"] = float("nan")
            out[f"freq_{name}_rel"] = float("nan")
        out["freq_total_uv2"] = float("nan")
        out["freq_spectral_centroid_hz"] = float("nan")
        return out

    # Etkili bantlar (Nyquist kırpma)
    eff = _effective_bands(bands, sfreq)
    # Toplam güç için referans aralık: 0.5 Hz – min(40, Nyquist)
    nyq = sfreq / 2.0
    tot_lo, tot_hi = 0.5, min(40.0, nyq)
    total = band_power(f, pxx, tot_lo, tot_hi) if tot_hi > tot_lo else float("nan")
    out["freq_total_uv2"] = total

    for name, (lo, hi) in eff.items():
        p = band_power(f, pxx, lo, hi)
        out[f"freq_{name}_abs_uv2"] = p
        if total is not None and np.isfinite(total) and total > 0:
            out[f"freq_{name}_rel"] = float(p / total)
        else:
            out[f"freq_{name}_rel"] = float("nan")

    # Etkili olmayan bantlar için NaN (sessizce atlamıyoruz)
    for name in bands:
        if name not in eff:
            out.setdefault(f"freq_{name}_abs_uv2", float("nan"))
            out.setdefault(f"freq_{name}_rel", float("nan"))

    # Spektral merkez (Hz)
    if np.isfinite(total) and total > 0:
        mask = (f >= tot_lo) & (f <= tot_hi)
        if mask.any():
            out["freq_spectral_centroid_hz"] = float(
                np.sum(f[mask] * pxx[mask]) / max(np.sum(pxx[mask]), 1e-30)
            )
        else:
            out["freq_spectral_centroid_hz"] = float("nan")
    else:
        out["freq_spectral_centroid_hz"] = float("nan")

    return out
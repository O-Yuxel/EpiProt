"""Zaman alanı EEG özellikleri.

Girişler µV cinsindendir (extractor dönüşümü yapar).
Çıkış birimleri: `_uv` sonekli sütunlar µV, `_uv2` µV², `_unitless` birimsiz.

Kural: boş veya NaN içeren girdi hata fırlatmaz; ilgili özellik NaN döner.
Sessizce sıfır döndürmek yasak.
"""
from __future__ import annotations

import numpy as np


def _safe(x: float) -> float:
    """NaN ve inf'i NaN olarak döndür (sessizce 0 yapmıyoruz)."""
    x = float(x)
    if not np.isfinite(x):
        return float("nan")
    return x


def _is_empty(x: np.ndarray) -> bool:
    return x.size == 0


def mean_uv(x: np.ndarray) -> float:
    if _is_empty(x):
        return float("nan")
    with np.errstate(invalid="ignore"):
        return _safe(np.mean(x))


def std_uv(x: np.ndarray) -> float:
    if _is_empty(x):
        return float("nan")
    with np.errstate(invalid="ignore"):
        return _safe(np.std(x, ddof=0))


def var_uv2(x: np.ndarray) -> float:
    if _is_empty(x):
        return float("nan")
    with np.errstate(invalid="ignore"):
        return _safe(np.var(x, ddof=0))


def rms_uv(x: np.ndarray) -> float:
    if _is_empty(x):
        return float("nan")
    with np.errstate(invalid="ignore"):
        return _safe(np.sqrt(np.mean(np.square(x))))


def min_uv(x: np.ndarray) -> float:
    if _is_empty(x):
        return float("nan")
    return _safe(np.min(x))


def max_uv(x: np.ndarray) -> float:
    if _is_empty(x):
        return float("nan")
    return _safe(np.max(x))


def peak_to_peak_uv(x: np.ndarray) -> float:
    if _is_empty(x):
        return float("nan")
    return _safe(np.ptp(x))


def line_length_uv(x: np.ndarray) -> float:
    """Ardışık örnekler arası mutlak farkların toplamı (µV)."""
    if x.size < 2:
        return 0.0
    return _safe(np.sum(np.abs(np.diff(x))))


def zero_crossing_rate(x: np.ndarray) -> float:
    """Ortalaması çıkarılmış sinyalde sıfır geçiş oranı (birimsiz, [0,1])."""
    if x.size < 2:
        return float("nan")
    xc = x - np.mean(x)
    signs = np.signbit(xc)
    crossings = np.count_nonzero(signs[1:] != signs[:-1])
    return _safe(crossings / (x.size - 1))


def compute_time_domain(x_uv: np.ndarray) -> dict[str, float]:
    """Bir kanal için zaman alanı özelliklerini hesapla."""
    return {
        "time_mean_uv": mean_uv(x_uv),
        "time_std_uv": std_uv(x_uv),
        "time_var_uv2": var_uv2(x_uv),
        "time_rms_uv": rms_uv(x_uv),
        "time_min_uv": min_uv(x_uv),
        "time_max_uv": max_uv(x_uv),
        "time_peak_to_peak_uv": peak_to_peak_uv(x_uv),
        "time_line_length_uv": line_length_uv(x_uv),
        "time_zero_crossing_rate": zero_crossing_rate(x_uv),
    }
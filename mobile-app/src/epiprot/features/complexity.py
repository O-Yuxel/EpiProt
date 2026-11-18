"""Karmaşıklık özellikleri: Shannon entropisi, Hjorth parametreleri."""
from __future__ import annotations

import numpy as np


def shannon_entropy_hist(x: np.ndarray, n_bins: int = 30) -> float:
    """Genlik histogramı üzerinden Shannon entropisi (bit).

    Normalize edilmiş genlik kullanılır (birimden bağımsız).
    """
    if x.size < 4 or not np.isfinite(x).all():
        return float("nan")
    std = np.std(x)
    if std <= 0:
        return 0.0
    xn = (x - np.mean(x)) / std
    hist, _ = np.histogram(xn, bins=n_bins)
    p = hist.astype(float) / hist.sum()
    p = p[p > 0]
    return float(-np.sum(p * np.log2(p)))


def hjorth_params(x: np.ndarray, sfreq: float) -> tuple[float, float, float]:
    """Hjorth activity, mobility, complexity.

    activity  : varyans (µV²)
    mobility  : sqrt(var(dx/dt) / var(x)) (birimsiz, 1/s ile ölçekli; sinyalin
                örnekleme hızına göre normalize edilmez, literatürdeki tanım)
    complexity: mobility(dx/dt) / mobility(x)
    """
    if x.size < 2 or not np.isfinite(x).all():
        return (float("nan"), float("nan"), float("nan"))
    var_x = float(np.var(x))
    dx = np.diff(x)
    var_dx = float(np.var(dx))
    if var_x <= 0 or var_dx < 0:
        return (var_x, float("nan"), float("nan"))
    mobility = float(np.sqrt(var_dx / var_x))
    ddx = np.diff(dx)
    var_ddx = float(np.var(ddx))
    if var_dx <= 0 or var_ddx < 0:
        return (var_x, mobility, float("nan"))
    mobility_dx = float(np.sqrt(var_ddx / var_dx))
    complexity = float(mobility_dx / mobility) if mobility > 0 else float("nan")
    return (var_x, mobility, complexity)


def compute_complexity(x_uv: np.ndarray, sfreq: float, shannon_n_bins: int = 30) -> dict[str, float]:
    act, mob, comp = hjorth_params(x_uv, sfreq=sfreq)
    return {
        "complex_shannon_entropy_bits": shannon_entropy_hist(x_uv, n_bins=shannon_n_bins),
        "complex_hjorth_activity_uv2": act,
        "complex_hjorth_mobility": mob,
        "complex_hjorth_complexity": comp,
    }
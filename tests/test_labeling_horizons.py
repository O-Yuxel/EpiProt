"""horizons.py için birim testleri — şartname 3.1 kurallarını doğrular."""
from __future__ import annotations

import numpy as np
import pytest

from epiprot.labeling.config import LabelConfig
from epiprot.labeling.horizons import (
    Seizure,
    label_window,
    label_windows,
)


def _cfg(horizons=(30,)):
    return LabelConfig(horizons_minutes=list(horizons))


def _w(minute: float, dur_min: float = 10.0 / 60.0):
    """Verilen dakikada başlayan, 10 saniyelik pencere döndür (dakika cinsinden)."""
    return (minute * 60.0, minute * 60.0 + dur_min * 60.0)


# --- Temel sınır testleri (şartname 3.1 örnekleriyle aynı) ---

def test_positive_at_20min_30min_horizon() -> None:
    w = _w(0.0)
    sz = Seizure(start_s=20 * 60.0, end_s=20 * 60.0 + 30.0)
    wl = label_window(*w, [sz], _cfg())
    # 20 dk sonra nöbet, 30 dk ufku içinde ve 5 dk güvenlik aralığından uzak
    assert wl.label(30) == 1.0
    assert wl.reason(30) == "positive"


def test_positive_at_30min_boundary() -> None:
    w = _w(0.0)
    sz = Seizure(start_s=30 * 60.0, end_s=30 * 60.0 + 30.0)
    wl = label_window(*w, [sz], _cfg())
    # Tam 30 dk -> <= koşulu sağlanır, pozitif
    assert wl.label(30) == 1.0


def test_excluded_within_gap() -> None:
    w = _w(0.0)
    sz = Seizure(start_s=3 * 60.0, end_s=3 * 60.0 + 30.0)
    wl = label_window(*w, [sz], _cfg())
    # 3 dk < 5 dk güvenlik aralığı -> dışla
    assert np.isnan(wl.label(30))
    assert wl.reason(30) == "excluded_gap"


def test_negative_when_delta_exceeds_horizon() -> None:
    w = _w(0.0)
    sz = Seizure(start_s=45 * 60.0, end_s=45 * 60.0 + 30.0)
    wl = label_window(*w, [sz], _cfg())
    # 45 dk > 30 dk ufku -> negatif
    assert wl.label(30) == 0.0
    assert wl.reason(30) == "negative_delta_exceeds_horizon"


def test_negative_when_no_future_seizure() -> None:
    w = _w(0.0)
    wl = label_window(*w, [], _cfg())
    assert wl.label(30) == 0.0
    assert wl.reason(30) == "negative_no_future_seizure"


# --- Nöbet teması ---

def test_excluded_when_window_inside_seizure() -> None:
    w = _w(10.0)  # 10. dakikada 10 sn'lik pencere
    sz = Seizure(start_s=9 * 60.0, end_s=11 * 60.0)  # 9-11 dk arası nöbet
    wl = label_window(*w, [sz], _cfg())
    assert wl.touching_seizure
    assert np.isnan(wl.label(30))
    assert wl.reason(30) == "excluded_touching_seizure"


def test_excluded_when_window_crosses_seizure_boundary() -> None:
    # Pencere nöbet başlangıcını kesiyor
    w = _w(9.95)  # 9.95 dk - 10.116 dk
    sz = Seizure(start_s=10 * 60.0, end_s=12 * 60.0)
    wl = label_window(*w, [sz], _cfg())
    assert wl.touching_seizure
    assert np.isnan(wl.label(30))


# --- Post-iktal ve pre-iktal dışlama ---

def test_excluded_post_ictal() -> None:
    w = _w(60.0)  # 60. dakikada pencere
    # Önceki nöbet 59. dakikada bitti -> 1 dk önce, post-iktal 4 saat içinde
    sz = Seizure(start_s=58 * 60.0, end_s=59 * 60.0)
    wl = label_window(*w, [sz], _cfg())
    assert wl.in_post_ictal
    assert np.isnan(wl.label(30))
    assert wl.reason(30) == "excluded_post_ictal"


def test_excluded_post_ictal_dominates() -> None:
    # Pencere 300. dk'da, önceki nöbet 240. dk'da bitti -> 60 dk önce.
    # Bu, post-iktal 4 saat penceresinin içinde. Post-iktal önce kontrol
    # edilir; reason "excluded_post_ictal" olur.
    w = _w(300.0)
    sz = Seizure(start_s=239 * 60.0, end_s=240 * 60.0)
    wl = label_window(*w, [sz], _cfg())
    assert np.isnan(wl.label(30))
    assert wl.reason(30) == "excluded_post_ictal"


def test_not_excluded_pre_when_seizure_older_than_exclusion() -> None:
    # 5 saat önce biten nöbet -> pre dışlama tetiklenmemeli
    w = _w(400.0)
    sz = Seizure(start_s=99 * 60.0, end_s=100 * 60.0)  # 300 dk önce bitti = 5 saat
    wl = label_window(*w, [sz], _cfg())
    # 400 dk - 100 dk = 300 dk = 5 saat > 4 saat -> pre dışlama yok
    # Ama pencerenin gelecekte nöbet yok -> negatif
    assert wl.label(30) == 0.0


# --- Çoklu nöbet ve ufuk kombinasyonları ---

def test_multiple_seizures_next_used_for_labeling() -> None:
    # Pencerenin 20 dk sonra ve 2 saat sonra nöbet
    w = _w(0.0)
    sz1 = Seizure(start_s=20 * 60.0, end_s=20 * 60.0 + 30.0)
    sz2 = Seizure(start_s=120 * 60.0, end_s=120 * 60.0 + 30.0)
    # 30 dk ufku: next_sz=sz1, delta=20 dk -> pozitif
    wl30 = label_window(*w, [sz1, sz2], _cfg((30,)))
    assert wl30.label(30) == 1.0
    # 15 dk ufku: next_sz=sz1, delta=20 dk > 15 dk -> negatif (ama yok, cfg'de)
    wl15 = label_window(*w, [sz1, sz2], _cfg((15,)))
    assert wl15.label(15) == 0.0


def test_all_horizons_for_same_window() -> None:
    w = _w(0.0)
    # 50 dk sonra nöbet
    sz = Seizure(start_s=50 * 60.0, end_s=50 * 60.0 + 30.0)
    cfg = LabelConfig(horizons_minutes=[30, 45, 60, 75, 90])
    wl = label_window(*w, [sz], cfg)
    assert wl.label(30) == 0.0  # 50 > 30 -> negatif
    assert wl.label(45) == 0.0  # 50 > 45 -> negatif
    assert wl.label(60) == 1.0  # 50 <= 60 -> pozitif
    assert wl.label(75) == 1.0
    assert wl.label(90) == 1.0


def test_horizon_boundary_sweep() -> None:
    # delta = 30, 45, 60, 75, 90 dk için sınır testleri
    cfg = LabelConfig(horizons_minutes=[30, 45, 60, 75, 90])
    for h in cfg.horizons_minutes:
        w = (0.0, 10.0)
        sz = Seizure(start_s=h * 60.0, end_s=h * 60.0 + 30.0)
        wl = label_window(*w, [sz], cfg)
        # h dk sonra -> o ufuk için pozitif sınıra dahil
        assert wl.label(h) == 1.0, f"h={h} için sınır testi başarısız"


# --- label_windows toplu API ---

def test_label_windows_batch() -> None:
    windows = [(0.0, 10.0), (600.0, 610.0), (1200.0, 1210.0)]
    sz = Seizure(start_s=20 * 60.0, end_s=20 * 60.0 + 30.0)
    out = label_windows(windows, [sz], _cfg())
    assert len(out) == 3
    # 0. dakikada pencere: 20 dk sonra nöbet -> pozitif (30 dk ufku)
    assert out[0].label(30) == 1.0
    # 10. dakikada pencere: 10 dk sonra nöbet -> 5<delta<=30 -> pozitif
    assert out[1].label(30) == 1.0
    # 20. dakikada pencere: nöbetle temas -> dışla
    assert np.isnan(out[2].label(30))
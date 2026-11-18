"""Tahmin ufuklarına göre pencere etiketleme.

Şartname 3.1, 3.2 ve 7. bölüm kuralları:

    Her pencere için:
        1. Pencere nöbetle temas ediyorsa (içinde veya kesişiyorsa) -> dışla
        2. Her ufuk H için:
            delta = next_seizure_start - window_end
            - delta <= gap_minutes            -> dışla (güvenlik aralığı)
            - gap < delta <= H                -> POZİTİF (1)
            - delta > H                       -> bu ufuk için negatif aday
              ama post-iktal dışlama uygulanır
        3. Post-iktal dışlama: pencere, bitişinden itibaren geriye
           `post_ictal_exclusion_hours` içinde biten bir nöbet varsa -> dışla
        4. Pre-iktal dışlama (negatif için): pencere başlangıcından itibaren
           `negative_exclusion_hours` içinde nöbet varsa -> dışla
        5. Çelişki: pencere birden çok kurala uyup farklı etiket üretiyorsa
           (bu tasarımda mümkün değil çünkü `next_start` tektir) -> dışla

Not: `next_seizure_start`, pencerenin bitişinden sonra başlayan ilk nöbettir.
Bu tanım, aynı pencereyi birden çok nöbete göre değerlendirme riskini
ortadan kaldırır ve şartnamenin "çelişkili etiket yok" ilkesini sağlar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np

from .config import LabelConfig


@dataclass
class Seizure:
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if self.end_s < self.start_s:
            raise ValueError(
                f"Nöbet end < start: {self.end_s} < {self.start_s}"
            )


@dataclass
class WindowLabel:
    """Tek bir pencere için tüm ufukların etiketleri."""
    window_start_s: float
    window_end_s: float
    labels: dict[int, float] = field(default_factory=dict)   # {H: 0/1/nan}
    reasons: dict[int, str] = field(default_factory=dict)    # {H: "positive"/"excluded_..."}
    touching_seizure: bool = False
    in_post_ictal: bool = False

    def label(self, horizon_min: int) -> float:
        return self.labels.get(horizon_min, float("nan"))

    def reason(self, horizon_min: int) -> str:
        return self.reasons.get(horizon_min, "unknown")

    @property
    def any_positive(self) -> bool:
        return any(v == 1.0 for v in self.labels.values())

    @property
    def all_excluded(self) -> bool:
        return all(np.isnan(v) for v in self.labels.values())


def _touches_seizure(w_start: float, w_end: float, seizures: Sequence[Seizure]) -> bool:
    """Pencere herhangi bir nöbetle kesişiyor veya temas ediyor mu?"""
    for sz in seizures:
        # [w_start, w_end] ile [sz.start, sz.end] kesişimi
        if w_start < sz.end_s and w_end > sz.start_s:
            return True
    return False


def _next_seizure_after(t: float, seizures: Sequence[Seizure]) -> Optional[Seizure]:
    """t anından sonra başlayan ilk nöbet (başlangıç zamanı > t)."""
    candidates = [sz for sz in seizures if sz.start_s >= t]
    if not candidates:
        return None
    return min(candidates, key=lambda s: s.start_s)


def _in_post_ictal(
    w_start: float,
    w_end: float,
    seizures: Sequence[Seizure],
    window_hours: float,
) -> bool:
    """Pencere, kendisinden önce biten bir nöbetin post-iktal penceresinde mi?

    Tanım: sz.end_s <= w_start < sz.end_s + window_hours  -> evet.
    Pencere tamamen nöbetten sonra olmalı (nöbetle kesişmiyorsa).
    """
    if window_hours <= 0:
        return False
    seconds = window_hours * 3600.0
    for sz in seizures:
        if sz.end_s <= w_start < sz.end_s + seconds:
            return True
    return False


def _has_seizure_within_pre(
    w_start: float,
    w_end: float,
    seizures: Sequence[Seizure],
    window_hours: float,
) -> bool:
    """Pencereden geriye `window_hours` içinde başlayan bir nöbet var mı?"""
    if window_hours <= 0:
        return False
    seconds = window_hours * 3600.0
    for sz in seizures:
        # Nöbet pencereden önce başlamış ve bitişi pencereden en fazla
        # `window_hours` önce ise: negatif için güvenli değil.
        if sz.end_s <= w_start and sz.end_s >= w_start - seconds:
            return True
    return False


def label_window(
    w_start: float,
    w_end: float,
    seizures: Sequence[Seizure],
    cfg: LabelConfig,
) -> WindowLabel:
    """Tek bir pencereyi, her ufuk için etiketle."""
    out = WindowLabel(window_start_s=w_start, window_end_s=w_end)

    # 1) Pencere nöbete temas ediyorsa tüm ufuklar dışlanır
    if _touches_seizure(w_start, w_end, seizures):
        out.touching_seizure = True
        for h in cfg.horizons_minutes:
            out.labels[h] = float("nan")
            out.reasons[h] = "excluded_touching_seizure"
        return out

    # 2) Post-iktal dışlama
    out.in_post_ictal = _in_post_ictal(
        w_start, w_end, seizures, cfg.post_ictal_exclusion_hours
    )
    if out.in_post_ictal:
        for h in cfg.horizons_minutes:
            out.labels[h] = float("nan")
            out.reasons[h] = "excluded_post_ictal"
        return out

    # 3) Pre-iktal dışlama (geçmişte yakın nöbet)
    if _has_seizure_within_pre(
        w_start, w_end, seizures, cfg.negative_exclusion_hours
    ):
        for h in cfg.horizons_minutes:
            out.labels[h] = float("nan")
            out.reasons[h] = "excluded_pre_exclusion"
        return out

    # 4) Gelecekteki en yakın nöbet
    next_sz = _next_seizure_after(w_end, seizures)
    gap_seconds = cfg.prediction_gap_minutes * 60.0
    horizon_to_s = {h: h * 60.0 for h in cfg.horizons_minutes}

    for h in cfg.horizons_minutes:
        if next_sz is None:
            # Bu pencerenin ilerisinde hiç nöbet yok -> bu ufuk için negatif
            out.labels[h] = 0.0
            out.reasons[h] = "negative_no_future_seizure"
            continue
        delta = next_sz.start_s - w_end
        if delta <= gap_seconds:
            out.labels[h] = float("nan")
            out.reasons[h] = "excluded_gap"
        elif delta <= horizon_to_s[h]:
            out.labels[h] = 1.0
            out.reasons[h] = "positive"
        else:
            # delta > H -> bu ufuk için gelecekte nöbet yok (H kadar ileride)
            out.labels[h] = 0.0
            out.reasons[h] = "negative_delta_exceeds_horizon"

    return out


def label_windows(
    windows: Sequence[tuple[float, float]],
    seizures: Sequence[Seizure],
    cfg: LabelConfig,
) -> List[WindowLabel]:
    """Tüm pencereler için etiket üret."""
    return [label_window(a, b, seizures, cfg) for (a, b) in windows]
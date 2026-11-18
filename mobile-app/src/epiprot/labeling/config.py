"""Etiketleme yapılandırması."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class LabelConfig:
    """Şartname 3.1 ve 7. bölümüne göre etiketleme parametreleri."""
    horizons_minutes: List[int] = field(
        default_factory=lambda: [30, 45, 60, 75, 90]
    )
    prediction_gap_minutes: float = 5.0
    negative_exclusion_hours: float = 4.0
    post_ictal_exclusion_hours: float = 4.0
    # Nöbet sırasında veya kenarında pencere → dışla
    # (tolerans saniye; 0 = tam temas dışlanır)

    def __post_init__(self) -> None:
        for h in self.horizons_minutes:
            if h <= 0:
                raise ValueError(f"Tahmin ufku > 0 olmalı, alındı: {h}")
        if self.prediction_gap_minutes < 0:
            raise ValueError("prediction_gap_minutes >= 0 olmalı")
        if self.prediction_gap_minutes >= min(self.horizons_minutes):
            raise ValueError(
                f"prediction_gap_minutes ({self.prediction_gap_minutes}) "
                f"en küçük ufuktan ({min(self.horizons_minutes)}) küçük olmalı"
            )

    def as_dict(self) -> dict:
        return asdict(self)
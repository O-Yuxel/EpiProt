"""Özellik çıkarma yapılandırması."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Tuple


# EEG bant sınırları (Hz) — şartnameye göre.
DEFAULT_BANDS: Dict[str, Tuple[float, float]] = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta":  (13.0, 30.0),
    "gamma": (30.0, 40.0),
}


@dataclass
class FeatureConfig:
    """Özellik çıkarma parametreleri."""
    # Pencere
    window_seconds: float = 10.0
    overlap: float = 0.0  # 0.0 = çakışmasız

    # Yeniden örnekleme (None = dokunma)
    target_sfreq: float | None = None  # örn. 40.0 önerilebilir; ilk deneyde kapalı

    # Filtreleme
    bandpass_low_hz: float | None = 0.5
    bandpass_high_hz: float | None = 40.0
    notch_hz: float | None = None  # 50.0 veya 60.0

    # Frekans alanı
    welch_nperseg: int | None = None  # None -> örnekleme hızına göre otomatik
    bands: Dict[str, Tuple[float, float]] = field(
        default_factory=lambda: dict(DEFAULT_BANDS)
    )

    # Karmaşıklık
    permutation_order: int = 3  # kullanılmıyor (Aşama 2'de opsiyonel)
    shannon_n_bins: int = 30    # genlik histogramı için bin sayısı

    # Kalite eşikleri (µV)
    amplitude_hard_limit_uv: float = 500.0  # tepe-tepe bu eşiği aşarsa uyarı
    flat_signal_std_uv: float = 0.01        # std bunun altındaysa düz sinyal

    def as_dict(self) -> dict:
        d = asdict(self)
        d["bands"] = {k: tuple(v) for k, v in self.bands.items()}
        return d
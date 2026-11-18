"""Çakışmayan (veya kısmi çakışan) EEG pencereleri üretir."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List


@dataclass(frozen=True)
class Window:
    index: int
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def make_windows(
    total_duration_s: float,
    window_seconds: float,
    overlap: float = 0.0,
) -> List[Window]:
    """Kayıt süresini pencerelere böl.

    Kuyruktaki tamamlanmamış pencere atılır (kenar etkilerinden kaçınmak için).
    Aynı anda `total_duration_s` kadar veri olduğu varsayılır.
    """
    if window_seconds <= 0:
        raise ValueError(f"window_seconds > 0 olmalı, alındı: {window_seconds}")
    if not (0.0 <= overlap < 1.0):
        raise ValueError(f"overlap [0,1) aralığında olmalı, alındı: {overlap}")

    step = window_seconds * (1.0 - overlap)
    windows: List[Window] = []
    i = 0
    t = 0.0
    # Float birikmesini önlemek için doğrudan çarpma kullan.
    while True:
        start = i * step
        end = start + window_seconds
        if end > total_duration_s + 1e-9:
            break
        windows.append(Window(index=i, start_s=start, end_s=end))
        i += 1
        if i > 10_000_000:  # güvenlik freni
            raise RuntimeError("make_windows: aşırı döngü, parametreleri kontrol edin")
    return windows


def window_sample_bounds(
    w: Window, sfreq: float, n_samples: int
) -> tuple[int, int]:
    """Pencereyi örnek indekslerine çevir; sınırları kırp."""
    a = int(round(w.start_s * sfreq))
    b = int(round(w.end_s * sfreq))
    a = max(0, min(a, n_samples))
    b = max(0, min(b, n_samples))
    if b <= a:
        raise ValueError(
            f"Pencere örnek aralığı boş: [{a}, {b}) (sfreq={sfreq}, n={n_samples})"
        )
    return a, b
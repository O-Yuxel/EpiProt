"""EDF okuma ve kanal sınıflandırma (MNE üstünde ince sarmalayıcı)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import mne

from ..config import NON_EEG_CHANNEL_PATTERNS


@dataclass
class EdfInfo:
    path: str
    ok: bool = False
    error: str | None = None
    sampling_rate_hz: float | None = None
    duration_s: float | None = None
    n_channels_total: int | None = None
    all_channels: List[str] = field(default_factory=list)
    eeg_channels: List[str] = field(default_factory=list)
    non_eeg_channels: List[str] = field(default_factory=list)
    unmatched_channels: List[str] = field(default_factory=list)


def _is_non_eeg_name(name: str) -> bool:
    up = name.upper()
    return any(pat in up for pat in NON_EEG_CHANNEL_PATTERNS)


def _is_confident_eeg_name(name: str) -> bool:
    """Adı 'EEG' içeren kanallar kesin EEG kabul edilir.

    CHB-MIT kanal adları ('FP1-F7', 'C3-P3' vb.) 'EEG' içermez.
    Bu nedenle ikinci bir sezgisel kural: bilinen non-EEG kalıplarını içermeyen
    ve 10-20 elektrot adı içeren kanallar EEG kabul edilir.
    Kesin EEG olmayanlar `unmatched_channels` altında raporlanır.
    """
    up = name.upper()
    if "EEG" in up:
        return True
    if _is_non_eeg_name(name):
        return False
    # 10-20 elektrot adları (büyük harf, tire/boşluk ayraçlı)
    known_electrodes = ("FP1", "FP2", "F3", "F4", "C3", "C4", "P3", "P4",
                        "O1", "O2", "F7", "F8", "T3", "T4", "T5", "T6",
                        "T7", "T8", "P7", "P8", "FZ", "CZ", "PZ", "A1", "A2")
    up_nodash = up.replace("-", "").replace(" ", "")
    return any(el in up_nodash for el in known_electrodes)


def classify_channels(channel_names: List[str]) -> tuple[list[str], list[str], list[str]]:
    """Kanalları (eeg, non_eeg, unmatched) olarak ayır."""
    eeg, non_eeg, unmatched = [], [], []
    for name in channel_names:
        if _is_non_eeg_name(name):
            non_eeg.append(name)
        elif _is_confident_eeg_name(name):
            eeg.append(name)
        else:
            unmatched.append(name)
    return eeg, non_eeg, unmatched


def read_edf_info(path: str | Path, preload: bool = False) -> EdfInfo:
    """EDF dosyasını başlık düzeyinde oku, kanalları sınıflandır."""
    path = Path(path)
    info = EdfInfo(path=str(path))
    try:
        raw = mne.io.read_raw_edf(str(path), preload=preload, verbose="ERROR")
    except Exception as e:  # noqa: BLE001 - bilinçli geniş yakalama
        info.error = f"{type(e).__name__}: {e}"
        return info

    try:
        info.sampling_rate_hz = float(raw.info["sfreq"])
        info.duration_s = float(raw.n_times) / float(raw.info["sfreq"])
        info.all_channels = list(raw.ch_names)
        info.n_channels_total = len(raw.ch_names)
        info.eeg_channels, info.non_eeg_channels, info.unmatched_channels = classify_channels(
            raw.ch_names
        )
        info.ok = True
    except Exception as e:  # noqa: BLE001
        info.error = f"Meta veri çıkarma hatası: {type(e).__name__}: {e}"
        return info
    finally:
        try:
            raw.close()
        except Exception:  # noqa: BLE001
            pass

    return info
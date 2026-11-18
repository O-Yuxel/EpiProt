"""EEG pencerelerinden STFT spektrogramları çıkar.

Girdi: EDF dosyası, 4 temporal kanal, 30 sn pencereler.
Çıktı: (n_windows, 4, freq_bins, time_bins) tensör, .npz olarak kaydedilir.

STFT parametreleri 30 sn pencereye göre ayarlanmıştır:
- 30 sn × 256 Hz = 7680 örnek
- nperseg=256, noverlap=128 → frekans çözünürlüğü: 0.5 Hz/bin
- zaman binleri: (7680-128)/(256-128) = 59
- frekans binleri (0.5-40 Hz): 40/0.5 = 80 (yaklaşık)
- toplam: 4 × 80 × 59 ≈ 4×80×59
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import mne
import numpy as np
from scipy.signal import spectrogram
from tqdm import tqdm

# 4 temporal kanal
TEMPORAL_CHANNELS = ["F7-T7", "T7-P7", "F8-T8", "T8-P8"]

# 30 sn pencere için STFT parametreleri
WINDOW_SECONDS = 30.0
NPERSEG = 256
NOVERLAP = 128
FREQ_MIN = 0.5
FREQ_MAX = 40.0


def _load_edf_4ch(edf_path: Path) -> tuple[np.ndarray, float]:
    """EDF yükle, sadece 4 temporal kanalı seç, µV'ya çevir."""
    raw = mne.io.read_raw_edf(str(edf_path), preload=True, verbose="ERROR")
    
    available = [ch for ch in TEMPORAL_CHANNELS if ch in raw.ch_names]
    if len(available) < 4:
        temporal_like = [ch for ch in raw.ch_names 
                        if any(t in ch.upper() for t in ["T7", "T8", "P7", "P8", "F7", "F8"])]
        if not temporal_like:
            raise RuntimeError(f"{edf_path.name}: temporal kanal bulunamadı")
        available = temporal_like[:4]
    
    raw.pick(available)
    raw.filter(l_freq=FREQ_MIN, h_freq=min(FREQ_MAX, raw.info["sfreq"]/2 - 0.01),
               method="fir", fir_design="firwin", verbose="ERROR")
    
    data_uv = raw.get_data() * 1e6
    sfreq = float(raw.info["sfreq"])
    raw.close()
    return data_uv, sfreq


def _stft_per_channel(x_uv: np.ndarray, sfreq: float) -> np.ndarray:
    """Bir kanal için STFT spektrogramı (dB, 0.5-40 Hz)."""
    f, t, Sxx = spectrogram(
        x_uv, fs=sfreq, nperseg=NPERSEG, noverlap=NOVERLAP,
        window="hann", scaling="density",
    )
    mask = (f >= FREQ_MIN) & (f <= FREQ_MAX)
    Sxx_db = 10 * np.log10(Sxx[mask, :] + 1e-10)
    return Sxx_db.astype(np.float32)


def build_stft_tensors(
    edf_paths: List[Path],
    window_seconds: float = WINDOW_SECONDS,
    logger=None,
) -> tuple[np.ndarray, List[tuple[str, int]]]:
    """Tüm EDF'lerden STFT tensörleri oluştur.
    
    Dönüş: (n_windows, 4, freq_bins, time_bins), edf_name_list
    """
    all_specs = []
    all_edfs = []
    
    for p in tqdm(edf_paths, desc="STFT", disable=(logger is None)):
        try:
            data_uv, sfreq = _load_edf_4ch(p)
        except Exception as e:
            if logger:
                logger.warning("STFT atlandı %s: %s", p.name, e)
            continue
        
        n_samples_per_window = int(window_seconds * sfreq)
        total_samples = data_uv.shape[1]
        n_windows = total_samples // n_samples_per_window
        
        for w in range(n_windows):
            start = w * n_samples_per_window
            end = start + n_samples_per_window
            window = data_uv[:, start:end]
            
            specs = []
            for ch in range(window.shape[0]):
                spec = _stft_per_channel(window[ch, :], sfreq)
                specs.append(spec)
            
            stacked = np.stack(specs, axis=0).astype(np.float32)
            all_specs.append(stacked)
            all_edfs.append((p.name, w))
    
    if not all_specs:
        raise RuntimeError("Hiç STFT tensörü üretilemedi")
    
    # Boyutları hizala
    shapes = set(s.shape for s in all_specs)
    if len(shapes) > 1:
        min_c = min(s.shape[0] for s in all_specs)
        min_f = min(s.shape[1] for s in all_specs)
        min_t = min(s.shape[2] for s in all_specs)
        all_specs = [s[:min_c, :min_f, :min_t] for s in all_specs]
    
    X = np.stack(all_specs, axis=0)
    return X, all_edfs


def save_stft_tensors(X: np.ndarray, edf_names: List[str], out_path: Path) -> None:
    """STFT tensörlerini diske kaydet."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        X=X,
        edf_names=np.array(edf_names, dtype=object),
    )


def load_stft_tensors(path: Path) -> tuple[np.ndarray, List[str]]:
    data = np.load(path, allow_pickle=True)
    return data["X"], list(data["edf_names"])
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import mne
import numpy as np
from scipy.signal import spectrogram

WINDOW_SECONDS = 30.0
NPERSEG = 256
NOVERLAP = 128
FREQ_MIN = 0.5
FREQ_MAX = 40.0

def _stft_per_channel(x_uv: np.ndarray, sfreq: float) -> np.ndarray:

    f, t, Sxx = spectrogram(
        x_uv, fs=sfreq, nperseg=NPERSEG, noverlap=NOVERLAP,
        window="hann", scaling="density",
    )
    mask = (f >= FREQ_MIN) & (f <= FREQ_MAX)
    return (10 * np.log10(Sxx[mask, :] + 1e-10)).astype(np.float32)

def load_and_stft_multimodal(
    eeg_path: Path, 
    ecg_path: Path, 
    window_seconds: float = WINDOW_SECONDS
) -> Tuple[np.ndarray, List[float]]:

    raw_eeg = mne.io.read_raw_edf(str(eeg_path), preload=True, verbose="ERROR")
    raw_eeg.filter(l_freq=FREQ_MIN, h_freq=FREQ_MAX, fir_design="firwin", verbose="ERROR")
    eeg_data = raw_eeg.get_data() * 1e6  
    sfreq = raw_eeg.info['sfreq']
    raw_eeg.close()

    ecg_data = None
    if ecg_path.exists():
        raw_ecg = mne.io.read_raw_edf(str(ecg_path), preload=True, verbose="ERROR")
        raw_ecg.filter(l_freq=FREQ_MIN, h_freq=FREQ_MAX, fir_design="firwin", verbose="ERROR")
        ecg_data = raw_ecg.get_data() * 1e6 
        raw_ecg.close()

    eeg_data = (eeg_data - np.mean(eeg_data, axis=1, keepdims=True)) / (np.std(eeg_data, axis=1, keepdims=True) + 1e-6)
    
    n_samples = eeg_data.shape[1]
    
    if ecg_data is not None:
        ecg_data = (ecg_data - np.mean(ecg_data, axis=1, keepdims=True)) / (np.std(ecg_data, axis=1, keepdims=True) + 1e-6)

        n_samples = min(n_samples, ecg_data.shape[1])
        eeg_data = eeg_data[:, :n_samples]
        ecg_data = ecg_data[:, :n_samples]

        combined_data = np.vstack([eeg_data, ecg_data]) 
    else:

        eeg_data = eeg_data[:, :n_samples]
        combined_data = np.vstack([eeg_data, np.zeros((1, n_samples))])

    n_samples_per_window = int(window_seconds * sfreq)
    n_windows = n_samples // n_samples_per_window

    all_specs = []
    window_starts = []

    for w in range(n_windows):
        start = w * n_samples_per_window
        end = start + n_samples_per_window
        window_data = combined_data[:, start:end]
        

        specs = []
        for ch in range(combined_data.shape[0]):  
            spec = _stft_per_channel(window_data[ch, :], sfreq)
            specs.append(spec)
            
        stacked = np.stack(specs, axis=0)  
        all_specs.append(stacked)
        window_starts.append(start / sfreq)

    if not all_specs:
        raise RuntimeError(f"Hiç pencere üretilemedi: {eeg_path.name}")

    X = np.stack(all_specs, axis=0)
    return X, window_starts
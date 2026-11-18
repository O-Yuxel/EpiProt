"""SeizeIT2 (BIDS formatı) EEG ve EKG sinyallerini okur."""
from __future__ import annotations
import mne
import numpy as np
from pathlib import Path
from typing import Dict, Any

def load_seizeit_multimodal(eeg_path: Path, ecg_path: Path) -> Dict[str, Any]:
    """EEG ve EKG dosyalarını okur, ön işleme tabi tutar ve tek bir sözlükte döndürür."""
    
    # 1. EEG'yi yükle
    raw_eeg = mne.io.read_raw_edf(str(eeg_path), preload=True, verbose="ERROR")
    
    # Kulak arkası cihazlar genelde düşük örnekleme hızına sahiptir
    # Sinyali filtrele (0.5 - 40 Hz)
    raw_eeg.filter(l_freq=0.5, h_freq=40.0, fir_design="firwin", verbose="ERROR")
    eeg_data = raw_eeg.get_data() * 1e6  # Volt -> µV
    eeg_sfreq = raw_eeg.info['sfreq']
    
    # 2. EKG'yi yükle (varsa)
    ecg_data = None
    if ecg_path.exists():
        raw_ecg = mne.io.read_raw_edf(str(ecg_path), preload=True, verbose="ERROR")
        # EKG için genelde 0.5 - 40 Hz yeterlidir veya daha özel bir filtre kullanılabilir
        raw_ecg.filter(l_freq=0.5, h_freq=40.0, fir_design="firwin", verbose="ERROR")
        ecg_data = raw_ecg.get_data() * 1e6  # µV
        ecg_sfreq = raw_ecg.info['sfreq']
        
        # EKG ile EEG süreleri eşleşmeyebilir, en kısa olana göre kes
        min_len = min(eeg_data.shape[1], ecg_data.shape[1])
        eeg_data = eeg_data[:, :min_len]
        ecg_data = ecg_data[:, :min_len]
        
    raw_eeg.close()
    if ecg_data is not None:
        raw_ecg.close()
        
    return {
        "eeg": eeg_data,
        "ecg": ecg_data,
        "sfreq": eeg_sfreq,
        "ch_names": raw_eeg.ch_names,
    }
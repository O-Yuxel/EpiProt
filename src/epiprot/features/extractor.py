"""Tek bir EDF kaydından pencere×kanal bazlı özellik tablosu üretir.

Girişler: EDF yolu, FeatureConfig, istenirse kanal alt kümesi.
Çıkışlar: pandas DataFrame (her satır bir (pencere, kanal) çifti).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import mne
import numpy as np
import pandas as pd

from .complexity import compute_complexity
from .config import FeatureConfig
from .frequency_domain import compute_frequency_domain
from .time_domain import compute_time_domain
from .windows import Window, make_windows, window_sample_bounds


@dataclass
class ExtractedRecord:
    """Tek bir EDF için özellik tablosunu ve meta bilgileri taşır."""
    edf_path: str
    patient_id: str | None
    sfreq_original: float
    sfreq_used: float
    duration_s: float
    channels_used: List[str]
    n_channels_excluded: int
    n_windows: int
    n_windows_dropped: int
    feature_df: pd.DataFrame


def _select_eeg_channels(raw: mne.io.BaseRaw) -> List[str]:
    """EEG kanallarını seç (mevcut edf_reader sınıflandırmasını kullan)."""
    from ..data.edf_reader import classify_channels
    eeg, _, _ = classify_channels(raw.ch_names)
    return eeg


def _apply_filter(raw: mne.io.BaseRaw, cfg: FeatureConfig, logger=None) -> mne.io.BaseRaw:
    """Bandpass + opsiyonel notch. Kopya üzerinde çalış, orijinali koru."""
    raw = raw.copy()
    nyq = raw.info["sfreq"] / 2.0
    low = cfg.bandpass_low_hz
    high = cfg.bandpass_high_hz
    if high is not None and high >= nyq:
        if logger is not None:
            logger.warning(
                "Bandpass üst sınırı Nyquist'e kırpıldı: %.2f -> %.2f",
                high, nyq - 0.01,
            )
        high = nyq - 0.01
    if low is not None and high is not None and low < high:
        raw.filter(l_freq=low, h_freq=high, method="fir",
                   fir_design="firwin", verbose="ERROR")
    if cfg.notch_hz is not None and cfg.notch_hz < nyq:
        raw.notch_filter(freqs=[cfg.notch_hz], verbose="ERROR")
    return raw


def _quality_flags(x_uv: np.ndarray, cfg: FeatureConfig) -> dict[str, float | bool]:
    """Basit sinyal kalitesi göstergeleri."""
    if x_uv.size == 0 or not np.isfinite(x_uv).all():
        return {
            "qc_has_nan": True,
            "qc_hard_amplitude_exceeded": True,
            "qc_flat_signal": True,
            "qc_std_uv": float("nan"),
            "qc_ptp_uv": float("nan"),
        }
    std = float(np.std(x_uv))
    ptp = float(np.ptp(x_uv))
    return {
        "qc_has_nan": False,
        "qc_hard_amplitude_exceeded": bool(ptp > cfg.amplitude_hard_limit_uv),
        "qc_flat_signal": bool(std < cfg.flat_signal_std_uv),
        "qc_std_uv": std,
        "qc_ptp_uv": ptp,
    }


def extract_features_from_edf(
    edf_path: str | Path,
    cfg: FeatureConfig,
    patient_id: str | None = None,
    channel_subset: List[str] | None = None,
    logger=None,
) -> ExtractedRecord:
    """Bir EDF'yi oku, filtrele, pencerele, kanal başına özellik çıkar."""
    edf_path = Path(edf_path)
    raw = mne.io.read_raw_edf(str(edf_path), preload=True, verbose="ERROR")
    sfreq_original = float(raw.info["sfreq"])

    # Kanalları seç
    eeg_all = _select_eeg_channels(raw)
    if channel_subset is not None:
        missing = [c for c in channel_subset if c not in raw.ch_names]
        if missing and logger is not None:
            logger.warning("%s: eksik kanallar: %s", edf_path.name, missing)
        eeg = [c for c in channel_subset if c in raw.ch_names]
    else:
        eeg = eeg_all

    if not eeg:
        raw.close()
        raise RuntimeError(f"{edf_path.name}: kullanılabilir EEG kanalı yok")

    # Sadece EEG kanallarını tut
    drop = [c for c in raw.ch_names if c not in eeg]
    raw = raw.copy().pick(eeg)

    # Orijinal örnekleme hızını ve süreyi sakla
    duration_s = float(raw.n_times) / sfreq_original

    # (Opsiyonel) yeniden örnekleme — anti-aliasing MNE tarafından yapılır
    sfreq_used = sfreq_original
    if cfg.target_sfreq is not None and cfg.target_sfreq < sfreq_original:
        raw.resample(cfg.target_sfreq, npad="auto", verbose="ERROR")
        sfreq_used = float(raw.info["sfreq"])

    # Filtreleme
    raw = _apply_filter(raw, cfg, logger=logger)

    data = raw.get_data()  # (n_channels, n_samples), volt
    # µV'ya çevir — TEK dönüşüm noktası burası.
    data_uv = data * 1e6

    n_samples = data_uv.shape[1]
    windows = make_windows(duration_s, cfg.window_seconds, overlap=cfg.overlap)

    rows: list[dict] = []
    dropped = 0
    for w in windows:
        try:
            a, b = window_sample_bounds(w, sfreq=sfreq_used, n_samples=n_samples)
        except ValueError:
            dropped += 1
            continue
        for ch_idx, ch_name in enumerate(eeg):
            x = data_uv[ch_idx, a:b]
            qc = _quality_flags(x, cfg)
            # Hard-limit aşan pencereleri tamamen atma, işaretle (Aşama 3+ karar verir)
            feats: dict = {
                "edf_path": str(edf_path),
                "patient_id": patient_id,
                "channel": ch_name,
                "window_index": w.index,
                "window_start_s": w.start_s,
                "window_end_s": w.end_s,
                "window_duration_s": w.duration_s,
                "sfreq_used": sfreq_used,
                "n_samples": int(b - a),
            }
            feats.update(qc)
            feats.update(compute_time_domain(x))
            feats.update(compute_frequency_domain(
                x, sfreq=sfreq_used, bands=cfg.bands, nperseg=cfg.welch_nperseg,
            ))
            feats.update(compute_complexity(
                x, sfreq=sfreq_used, shannon_n_bins=cfg.shannon_n_bins,
            ))
            rows.append(feats)

    raw.close()

    if not rows:
        raise RuntimeError(
            f"{edf_path.name}: hiçbir pencere üretilmedi (duration={duration_s}, "
            f"window={cfg.window_seconds})"
        )

    df = pd.DataFrame(rows)
    return ExtractedRecord(
        edf_path=str(edf_path),
        patient_id=patient_id,
        sfreq_original=sfreq_original,
        sfreq_used=sfreq_used,
        duration_s=duration_s,
        channels_used=eeg,
        n_channels_excluded=len(drop),
        n_windows=len(windows),
        n_windows_dropped=dropped,
        feature_df=df,
    )


def extract_many(
    edf_paths: List[str | Path],
    cfg: FeatureConfig,
    patient_id_of=None,
    logger=None,
) -> tuple[pd.DataFrame, list[dict]]:
    """Birden çok EDF için özellik tablosu birleştir; başarısızları raporla."""
    frames: list[pd.DataFrame] = []
    failures: list[dict] = []
    for p in edf_paths:
        pid = patient_id_of(p) if patient_id_of else None
        try:
            rec = extract_features_from_edf(p, cfg, patient_id=pid, logger=logger)
            frames.append(rec.feature_df)
            if logger is not None:
                logger.info(
                    "Özellik çıkarıldı: %s | sfreq %.1f->%.1f | %d kanal | %d pencere | %d satır",
                    Path(p).name, rec.sfreq_original, rec.sfreq_used,
                    len(rec.channels_used), rec.n_windows, len(rec.feature_df),
                )
        except Exception as e:  # noqa: BLE001
            failures.append({"edf_path": str(p), "error": f"{type(e).__name__}: {e}"})
            if logger is not None:
                logger.error("Özellik çıkarma başarısız: %s — %s", p, e)
    if not frames:
        return pd.DataFrame(), failures
    return pd.concat(frames, ignore_index=True), failures
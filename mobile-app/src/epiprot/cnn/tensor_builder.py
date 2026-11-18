"""Ham EDF'lerden CNN için tensör oluştur.

Çıktı yapısı (her hasta için bir .npz dosyası):
    X:      (n_windows, n_channels, n_samples)  float32, µV
    y_30:   (n_windows,)                        int8   {0, 1, -1}  (-1 = exclude)
    y_45, y_60, y_75, y_90: aynı
    window_start_s: (n_windows,)                float32
    edf_path: (n_windows,)                      object (string array)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import mne
import numpy as np
from tqdm import tqdm

from ..data.edf_reader import classify_channels
from ..labeling.config import LabelConfig
from ..labeling.horizons import Seizure, label_window


@dataclass
class PatientTensors:
    patient_id: str
    X: np.ndarray                   # (N, C, T) float32
    y_by_horizon: dict[int, np.ndarray]  # {30: (N,), 45: (N,), ...} int8
    window_start_s: np.ndarray      # (N,) float32
    edf_paths: np.ndarray           # (N,) <U (string)
    channels: List[str]
    sfreq: float
    n_samples: int
    window_seconds: float


def _load_edf_raw(edf_path: Path) -> tuple[np.ndarray, List[str], float]:
    """EDF yükle, EEG kanallarını seç, döndür (data_uv, channel_names, sfreq)."""
    raw = mne.io.read_raw_edf(str(edf_path), preload=True, verbose="ERROR")
    eeg, _, _ = classify_channels(raw.ch_names)
    if not eeg:
        raise RuntimeError(f"{edf_path.name}: EEG kanalı yok")
    raw = raw.copy().pick(eeg)
    raw.filter(l_freq=0.5, h_freq=min(40.0, raw.info["sfreq"] / 2 - 0.01),
               method="fir", fir_design="firwin", verbose="ERROR")
    data_uv = raw.get_data() * 1e6  # (C, total_samples)
    sfreq = float(raw.info["sfreq"])
    raw.close()
    return data_uv, eeg, sfreq


def _common_channels(channel_lists: List[List[str]]) -> List[str]:
    """Tüm dosyalarda ortak olan kanalları bul (sıra korunur)."""
    if not channel_lists:
        return []
    common = set(channel_lists[0])
    for cl in channel_lists[1:]:
        common &= set(cl)
    # İlk listenin sırasını koru
    return [c for c in channel_lists[0] if c in common]


def build_patient_tensors(
    patient_id: str,
    edf_paths: List[Path],
    seizures_by_edf: dict[str, List[Seizure]],
    window_seconds: float = 10.0,
    label_cfg: Optional[LabelConfig] = None,
    logger=None,
) -> PatientTensors:
    """Bir hastanın tüm EDF'lerinden (N, C, T) tensörleri oluştur.

    Aynı hastadaki tüm EDF'lerin **ortak EEG kanallarını** kullanır.
    Böylece tensör boyutu tüm dosyalarda tutarlı olur.
    """
    if label_cfg is None:
        label_cfg = LabelConfig()

    # 1) Tüm dosyaların kanallarını öğren
    per_file_channels = []
    for p in edf_paths:
        try:
            raw = mne.io.read_raw_edf(str(p), preload=False, verbose="ERROR")
            eeg, _, _ = classify_channels(raw.ch_names)
            per_file_channels.append(eeg)
            raw.close()
        except Exception as e:
            if logger:
                logger.warning("Kanal tespiti başarısız %s: %s", p.name, e)
            per_file_channels.append([])

    common_channels = _common_channels(per_file_channels)
    if not common_channels:
        raise RuntimeError(f"{patient_id}: ortak EEG kanalı bulunamadı")
    if logger:
        logger.info("%s: %d ortak kanal → %s", patient_id, len(common_channels), common_channels)

    # 2) Birinci geçiş: kaç pencere üretileceğini say (sadece metadata)
    total_windows = 0
    file_metadata = []  # (path, n_windows, sfreq, n_samples_per_window, seizures)
    first_sfreq = None          # ← BU SATIRI EKLEYİN
    first_n_samples = None      # ← BU SATIRI EKLEYİN

    for p in tqdm(edf_paths, desc=f"{patient_id}-scan", disable=(logger is None)):
        try:
            data_uv, chans, sfreq = _load_edf_raw(p)
        except Exception as e:
            if logger:
                logger.error("EDF okunamadı %s: %s", p.name, e)
            continue

        if first_sfreq is None:
            first_sfreq = sfreq
        elif abs(sfreq - first_sfreq) > 0.5:
            continue

        idx_map = {c: i for i, c in enumerate(chans)}
        if not all(c in idx_map for c in common_channels):
            continue
        data_uv = data_uv[[idx_map[c] for c in common_channels], :]

        n_samples_per_window = int(round(window_seconds * sfreq))
        if first_n_samples is None:
            first_n_samples = n_samples_per_window
        total_samples = data_uv.shape[1]
        n_windows = total_samples // n_samples_per_window
        edf_name = p.name
        seizures = seizures_by_edf.get(edf_name, [])

        kept = 0
        for w in range(n_windows):
            t_start = w * window_seconds
            t_end = t_start + window_seconds
            wl = label_window(t_start, t_end, seizures, label_cfg)
            if any(not np.isnan(wl.label(h)) for h in label_cfg.horizons_minutes):
                kept += 1

        file_metadata.append((p, n_windows, sfreq, n_samples_per_window, seizures))
        total_windows += kept

        # RAM serbest bırak
        del data_uv

    if total_windows == 0:
        raise RuntimeError(f"{patient_id}: hiç geçerli pencere yok")

    if logger:
        logger.info("%s: %d pencere üretilecek, diske yazılıyor (memmap)...",
                    patient_id, total_windows)

    # 3) Memmap dosyalarını aç
    C = len(common_channels)
    T = first_n_samples
    tmp_dir = Path(f"/tmp/{patient_id}_tmp")
    tmp_dir.mkdir(exist_ok=True)

    X_mm = np.lib.format.open_memmap(
        tmp_dir / "X.npy", mode="w+", dtype=np.float32,
        shape=(total_windows, C, T),
    )
    y_mm = {h: np.lib.format.open_memmap(
        tmp_dir / f"y_{h}.npy", mode="w+", dtype=np.int8,
        shape=(total_windows,)
    ) for h in label_cfg.horizons_minutes}
    ws_mm = np.lib.format.open_memmap(
        tmp_dir / "ws.npy", mode="w+", dtype=np.float32,
        shape=(total_windows,),
    )
    edf_list = []

    # 4) İkinci geçiş: veriyi diske yaz
    idx = 0
    for (p, n_windows, sfreq, n_samples_per_window, seizures) in \
            tqdm(file_metadata, desc=f"{patient_id}-write", disable=(logger is None)):
        try:
            data_uv, chans, sfreq = _load_edf_raw(p)
        except Exception as e:
            if logger:
                logger.error("EDF yeniden okunamadı %s: %s", p.name, e)
            continue

        idx_map = {c: i for i, c in enumerate(chans)}
        data_uv = data_uv[[idx_map[c] for c in common_channels], :]

        for w in range(n_windows):
            t_start = w * window_seconds
            t_end = t_start + window_seconds
            sample_start = w * n_samples_per_window
            sample_end = sample_start + n_samples_per_window
            x_win = data_uv[:, sample_start:sample_end].astype(np.float32)
            if x_win.shape[1] != T:
                continue

            wl = label_window(t_start, t_end, seizures, label_cfg)
            y_row = {}
            for h in label_cfg.horizons_minutes:
                lab = wl.label(h)
                y_row[h] = -1 if np.isnan(lab) else int(lab)

            if all(v == -1 for v in y_row.values()):
                continue

            X_mm[idx] = x_win
            for h, v in y_row.items():
                y_mm[h][idx] = v
            ws_mm[idx] = t_start
            edf_list.append(p.name)
            idx += 1

        del data_uv

    if idx != total_windows:
        if logger:
            logger.warning("%s: %d/%d (bazı pencereler atlandı)",
                           patient_id, idx, total_windows)
        X_mm = X_mm[:idx]
        for h in y_mm:
            y_mm[h] = y_mm[h][:idx]
        ws_mm = ws_mm[:idx]

    X_mm.flush()
    for h in y_mm:
        y_mm[h].flush()
    ws_mm.flush()

    # 5) RAM'e yükle (artık sadece bu hasta kadarı, sorun değil)
    X = np.asarray(X_mm)
    y_by_horizon = {h: np.asarray(y_mm[h]) for h in y_mm}
    window_start_s = np.asarray(ws_mm)
    edf_paths_arr = np.array(edf_list, dtype=object)

    # Temp dosyaları sil
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return PatientTensors(
        patient_id=patient_id,
        X=X,
        y_by_horizon=y_by_horizon,
        window_start_s=window_start_s,
        edf_paths=edf_paths_arr,
        channels=common_channels,
        sfreq=float(first_sfreq),
        n_samples=int(first_n_samples),
        window_seconds=window_seconds,
    )


def save_patient_tensors(t: PatientTensors, out_path: Path) -> None:
    """Hasta tensörlerini .npz olarak kaydet."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_dict = {
        "X": t.X,
        "window_start_s": t.window_start_s,
        "edf_paths": t.edf_paths,
        "channels": np.array(t.channels, dtype=object),
        "sfreq": np.array(t.sfreq),
        "n_samples": np.array(t.n_samples),
        "window_seconds": np.array(t.window_seconds),
    }
    for h, y in t.y_by_horizon.items():
        save_dict[f"y_{h}"] = y
    np.savez_compressed(out_path, **save_dict)


def load_patient_tensors(path: Path) -> PatientTensors:
    """Kaydedilmiş .npz dosyasından hasta tensörlerini yükle."""
    data = np.load(path, allow_pickle=True)
    patient_id = Path(path).stem
    y_by_horizon = {}
    for key in data.files:
        if key.startswith("y_"):
            h = int(key.split("_")[1])
            y_by_horizon[h] = data[key]
    return PatientTensors(
        patient_id=patient_id,
        X=data["X"],
        y_by_horizon=y_by_horizon,
        window_start_s=data["window_start_s"],
        edf_paths=data["edf_paths"],
        channels=list(data["channels"]),
        sfreq=float(data["sfreq"]),
        n_samples=int(data["n_samples"]),
        window_seconds=float(data["window_seconds"]),
    )
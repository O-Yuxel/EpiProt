"""STFT tensörleri + etiketler → PyTorch Dataset."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
import torch
from torch.utils.data import Dataset

from ..labeling.config import LabelConfig
from ..labeling.horizons import Seizure, label_window
from .stft_builder import build_stft_tensors


class STFTDataset(Dataset):
    """STFT tensörlerini ve etiketlerini saran Dataset."""
    def __init__(self, X: np.ndarray, y: np.ndarray, normalize: bool = True):
        mask = y >= 0
        self.X = X[mask].astype(np.float32)
        self.y = y[mask].astype(np.float32)
        self.normalize = normalize

        if normalize and len(self.X) > 0:
            self.mean = self.X.mean(axis=(0, 2, 3), keepdims=True).astype(np.float32)
            self.std = (self.X.std(axis=(0, 2, 3), keepdims=True) + 1e-6).astype(np.float32)
        else:
            self.mean = np.float32(0.0)
            self.std = np.float32(1.0)

    def __len__(self) -> int:
        return len(self.y)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        x = (self.X[idx] - self.mean[0]) / self.std[0]
        return torch.from_numpy(x), torch.tensor(self.y[idx], dtype=torch.float32)

    def class_counts(self) -> dict[int, int]:
        return {
            0: int((self.y == 0).sum()),
            1: int((self.y == 1).sum()),
        }


def build_stft_dataset_for_patient(
    edf_paths: List[Path],
    seizures_by_edf: Dict[str, List[Seizure]],
    horizon_min: int,
    label_cfg: LabelConfig,
    window_seconds: float = 30.0,
    logger=None,
) -> tuple[np.ndarray, np.ndarray]:
    """Bir hastanın tüm EDF'leri için STFT tensörleri ve etiketleri üret.

    Dönüş: (X, y)
    - X: (n_windows, 4, 40, 59)
    - y: (n_windows,) — horizon için etiket (-1 excluded, 0 negatif, 1 pozitif)
    """
    all_X = []
    all_y = []

    for p in edf_paths:
        try:
            X_single, meta_single = build_stft_tensors(
                [p], window_seconds=window_seconds, logger=logger,
            )
        except Exception as e:
            if logger:
                logger.warning("STFT atlandı %s: %s", p.name, e)
            continue

        seizures = seizures_by_edf.get(p.name, [])

        for i, (w_name, w_idx) in enumerate(meta_single):
            w_start = w_idx * window_seconds
            w_end = w_start + window_seconds
            wl = label_window(w_start, w_end, seizures, label_cfg)
            label = wl.label(horizon_min)

            all_X.append(X_single[i])
            all_y.append(label)

    if not all_X:
        raise RuntimeError("Hiç pencere üretilemedi")

    X = np.stack(all_X, axis=0)
    y = np.array(all_y, dtype=np.float32)
    return X, y
"""PyTorch Dataset ve hasta-bazlı split."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import torch
from torch.utils.data import Dataset

from .tensor_builder import PatientTensors


class WindowDataset(Dataset):
    """(N, C, T) tensörleri ve (N,) etiketleri saran PyTorch Dataset.

    `-1` etiketli pencereler (excluded) yüklenmez.
    """
    def __init__(self, X: np.ndarray, y: np.ndarray,
                 normalize: bool = True, memmap_safe: bool = True):
        mask = y >= 0
        # RAM'de kopya yapma — sadece filtreleme maskesi uygula
        # Eğer X memmap ise, X[mask] yine RAM'e kopyalar ama en azından
        # normalizasyon parametrelerini sample üzerinden hesaplayabiliriz.
        self.X_full = X
        self.mask = mask
        self.y = y[mask].astype(np.float32)
        self.normalize = normalize

        # Normalizasyon parametrelerini sadece bir alt örnek üzerinden hesapla
        if normalize and mask.sum() > 0:
            # Bellek dostu: sabit bir alt örnek (max 2000 pencere) üzerinden
            n = min(2000, mask.sum())
            idx = np.where(mask)[0][:n]
            sample = X[idx]  # sadece 2000 pencere RAM'e kopyalanır
            self.mean = sample.mean(axis=(0, 2), keepdims=True).astype(np.float32)
            self.std = (sample.std(axis=(0, 2), keepdims=True) + 1e-6).astype(np.float32)
        else:
            self.mean = np.float32(0.0)
            self.std = np.float32(1.0)

    def __len__(self) -> int:
        return len(self.y)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        # Mask'i uygula, orijinal X'ten al
        orig_idx = np.where(self.mask)[0][idx]
        x = (self.X_full[orig_idx] - self.mean[0]) / self.std[0]
        x = x.astype(np.float32)
        return torch.from_numpy(x), torch.tensor(self.y[idx], dtype=torch.float32)

    def class_counts(self) -> dict[int, int]:
        return {
            0: int((self.y == 0).sum()),
            1: int((self.y == 1).sum()),
        }

    def __len__(self) -> int:
        return len(self.y)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        # Maske uygula: idx, filtre edilmiş y'deki sıra
        orig_idx = np.where(self.mask)[0][idx]
        x = ((self.X_full[orig_idx] - self.mean[0]) / self.std[0]).astype(np.float32)
        return torch.from_numpy(x), torch.tensor(self.y[idx], dtype=torch.float32)

    def class_counts(self) -> dict[int, int]:
        return {
            0: int((self.y == 0).sum()),
            1: int((self.y == 1).sum()),
        }


@dataclass
class TrainTestSplit:
    train_X: np.ndarray | list
    train_y: np.ndarray | list
    test_X: np.ndarray | list
    test_y: np.ndarray | list
    train_patients: list
    test_patients: list


def build_split(
    patient_tensors: dict[str, PatientTensors],
    horizon_min: int,
    test_patient_ids: List[str],
) -> TrainTestSplit:
    """Hasta bazlı split. test_patient_ids test tarafında, gerisi train."""
    train_X, train_y, test_X, test_y = [], [], [], []
    train_pids, test_pids = [], []

    for pid, t in patient_tensors.items():
        X = t.X
        y = t.y_by_horizon[horizon_min]
        if pid in test_patient_ids:
            test_X.append(X)
            test_y.append(y)
            test_pids.append(pid)
        else:
            train_X.append(X)
            train_y.append(y)
            train_pids.append(pid)

    if not train_X or not test_X:
        raise ValueError("Train veya test boş")

    # RAM dostu: concatenate yerine listeyi koruyup, her birini ayrı tut
    # WindowDataset'ler zaten memmap safe, burada concatenate yapma
    return TrainTestSplit(
        train_X=train_X,           # artık bir liste
        train_y=train_y,
        test_X=test_X,
        test_y=test_y,
        train_patients=train_pids,
        test_patients=test_pids,
    )
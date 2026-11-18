from __future__ import annotations
import numpy as np
import torch
from torch.utils.data import Dataset
from typing import List, Tuple

class SeizeitDataset(Dataset):
    def __init__(self, X: np.ndarray, y: np.ndarray):
        self.mask = y >= 0
        self.X = X 
        self.y = y[self.mask].astype(np.float32)
        
        if self.mask.sum() > 0:
            n = min(2000, self.mask.sum())
            idx = np.where(self.mask)[0][:n]
            sample = X[idx]
            self.mean = sample.mean(axis=(0, 2, 3), keepdims=True).astype(np.float32)
            self.std = (sample.std(axis=(0, 2, 3), keepdims=True) + 1e-6).astype(np.float32)
        else:
            self.mean = np.float32(0.0)
            self.std = np.float32(1.0)

    def __len__(self) -> int:
        return len(self.y)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        orig_idx = np.where(self.mask)[0][idx]
        x = (self.X[orig_idx] - self.mean[0]) / self.std[0]
        return torch.from_numpy(x.astype(np.float32)), torch.tensor(self.y[idx], dtype=torch.float32)

    def class_counts(self) -> dict[int, int]:
        return {0: int((self.y == 0).sum()), 1: int((self.y == 1).sum())}


def build_seizeit_labels(
    window_starts: List[float], 
    window_seconds: float, 
    seizures: List[Tuple[float, float]], 
    horizon_min: int, 
    gap_min: int = 5
) -> np.ndarray:
    y = np.full(len(window_starts), -1.0, dtype=np.float32)
    
    for i, w_start in enumerate(window_starts):
        w_end = w_start + window_seconds
        
        touching = False
        for sz_start, sz_end in seizures:
            if w_start < sz_end and w_end > sz_start:
                touching = True
                break
        if touching:
            continue
            
        next_sz_start = None
        for sz_start, sz_end in seizures:
            if sz_start >= w_end:
                if next_sz_start is None or sz_start < next_sz_start:
                    next_sz_start = sz_start
                    
        if next_sz_start is None:
            y[i] = 0.0
        else:
            delta = next_sz_start - w_end
            if delta <= gap_min * 60:
                y[i] = -1.0
            elif delta <= horizon_min * 60:
                y[i] = 1.0 
            else:
                y[i] = 0.0
                
    return y
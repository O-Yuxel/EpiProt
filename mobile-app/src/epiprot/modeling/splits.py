"""Zamansal ve hasta bazlı veri bölme.

Sızıntı önleme kuralları:
    1. Aynı pencerenin tüm kanalları AYNI tarafta olmalı.
    2. Zamansal split: eğitim öncesi, test sonrası.
    3. Nöbet çevresindeki pencereler tek tarafta toplanmalı.
    4. Hasta bazlı split: aynı hasta tümüyle bir tarafta.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd


@dataclass
class SplitIndices:
    train: np.ndarray
    test: np.ndarray

    def summary(self) -> dict:
        return {
            "n_train": int(self.train.size),
            "n_test": int(self.test.size),
        }


def temporal_split(
    df: pd.DataFrame,
    label_col: str,
    test_fraction: float = 0.2,
    time_col: str = "window_start_s",
    group_col: str = "edf_path",
) -> SplitIndices:
    """Zamansal split — her EDF içinde ilk %80 eğitim, son %20 test.

    Etiketli satırlar arasında yapılır (NaN etiketler zaten dışlanmış olur).
    Aynı pencere (group_col + time_col) aynı tarafa gider.
    """
    if not 0.0 < test_fraction < 1.0:
        raise ValueError(f"test_fraction (0,1) içinde olmalı, alındı: {test_fraction}")

    labeled = df[df[label_col].notna()].copy()
    if labeled.empty:
        raise ValueError(f"'{label_col}' sütununda hiç etiketli satır yok")

    train_parts: List[pd.DataFrame] = []
    test_parts: List[pd.DataFrame] = []

    for edf_path, g in labeled.groupby(group_col, sort=False):
        # Pencere bazlı benzersiz zamanlar
        unique_times = np.sort(g[time_col].unique())
        n = unique_times.size
        if n < 2:
            # Çok az pencere: bu EDF tamamen eğitimde
            train_parts.append(g)
            continue
        cutoff_idx = int(np.floor(n * (1.0 - test_fraction)))
        cutoff_idx = max(1, min(cutoff_idx, n - 1))
        cutoff_time = unique_times[cutoff_idx]
        train_parts.append(g[g[time_col] < cutoff_time])
        test_parts.append(g[g[time_col] >= cutoff_time])

    train = pd.concat(train_parts, ignore_index=False) if train_parts else labeled.iloc[0:0]
    test = pd.concat(test_parts, ignore_index=False) if test_parts else labeled.iloc[0:0]

    if train.empty or test.empty:
        # Eğitim veya test boş kalırsa hata — sessizce başarı uydurma.
        raise ValueError(
            f"Zamansal split sonucu train={len(train)}, test={len(test)} — "
            "yeterli değil"
        )

    return SplitIndices(
        train=train.index.to_numpy(),
        test=test.index.to_numpy(),
    )


def patient_split(
    df: pd.DataFrame,
    label_col: str,
    test_patient_ids: List[str],
    patient_col: str = "patient_id",
) -> SplitIndices:
    """Hasta bazlı split — verilen test hastaları test, gerisi eğitim."""
    if not test_patient_ids:
        raise ValueError("test_patient_ids boş olamaz")
    labeled = df[df[label_col].notna()]
    if labeled.empty:
        raise ValueError(f"'{label_col}' sütununda hiç etiketli satır yok")

    test_mask = labeled[patient_col].isin(test_patient_ids)
    train = labeled.loc[~test_mask]
    test = labeled.loc[test_mask]
    if train.empty or test.empty:
        raise ValueError(
            f"Hasta split sonucu train={len(train)}, test={len(test)} — "
            "yeterli değil"
        )
    return SplitIndices(
        train=train.index.to_numpy(),
        test=test.index.to_numpy(),
    )


def assert_no_leakage(
    df: pd.DataFrame,
    split: SplitIndices,
    group_cols: Tuple[str, str] = ("edf_path", "window_start_s"),
) -> None:
    """Aynı (edf_path, window_start_s) çifti iki tarafta da var mı kontrol et."""
    train_groups = set(map(tuple, df.loc[split.train, list(group_cols)].itertuples(index=False)))
    test_groups = set(map(tuple, df.loc[split.test, list(group_cols)].itertuples(index=False)))
    overlap = train_groups & test_groups
    if overlap:
        raise AssertionError(
            f"Veri sızıntısı! {len(overlap)} pencere hem eğitimde hem testte. "
            f"Örnek: {list(overlap)[:3]}"
        )
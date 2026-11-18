"""Etiketleri özellik tablosuna uygula ve özet rapor üret."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

from .config import LabelConfig
from .horizons import Seizure, WindowLabel, label_window


@dataclass
class LabelReport:
    """Her ufuk için sınıf dağılımı ve dışlama nedenleri."""
    horizon: int
    n_positive: int
    n_negative: int
    n_excluded: int
    n_total: int
    exclusion_reasons: Dict[str, int]

    @property
    def positive_ratio(self) -> float:
        denom = self.n_positive + self.n_negative
        return self.n_positive / denom if denom > 0 else float("nan")

    def to_row(self) -> dict:
        return {
            "horizon_min": self.horizon,
            "n_positive": self.n_positive,
            "n_negative": self.n_negative,
            "n_excluded": self.n_excluded,
            "n_total": self.n_total,
            "positive_ratio": self.positive_ratio,
            **{f"excl_{k}": v for k, v in self.exclusion_reasons.items()},
        }


def _label_one_edf_row(
    df: pd.DataFrame,
    seizures: List[Seizure],
    cfg: LabelConfig,
    n_samples_per_window: int,
) -> pd.DataFrame:
    """Bir EDF'nin özellik tablosunu etiketle (satır = pencere×kanal).

    Aynı pencere içindeki tüm kanallar **aynı etiketi** alır (kanal bazlı
    etiket farkı yoktur). Bu yüzden pencereyi bir kez etiketleyip tüm
    kanallara yayarız; performans için bu önemlidir.
    """
    # Pencere bazlı benzersiz (start, end) çiftleri
    unique_windows = df[["window_start_s", "window_end_s"]].drop_duplicates()
    label_by_key: Dict[tuple[float, float], WindowLabel] = {}
    for _, row in unique_windows.iterrows():
        wl = label_window(float(row["window_start_s"]),
                          float(row["window_end_s"]),
                          seizures, cfg)
        label_by_key[(float(row["window_start_s"]), float(row["window_end_s"]))] = wl

    for h in cfg.horizons_minutes:
        col = f"label_{h}min"
        reason_col = f"label_reason_{h}min"
        df[col] = np.nan
        df[reason_col] = ""
        for (ws, we), wl in label_by_key.items():
            mask = (df["window_start_s"] == ws) & (df["window_end_s"] == we)
            df.loc[mask, col] = wl.label(h)
            df.loc[mask, reason_col] = wl.reason(h)
    return df


def apply_labels(
    features_df: pd.DataFrame,
    seizures_by_edf: Dict[str, List[Seizure]],
    cfg: LabelConfig | None = None,
) -> tuple[pd.DataFrame, List[LabelReport]]:
    """Özellik tablosuna her ufuk için etiket sütunları ekle.

    Parametreler
    ------------
    features_df : DataFrame
        `edf_path`, `window_start_s`, `window_end_s` sütunları olmalı.
    seizures_by_edf : dict
        {edf_path: [Seizure, ...]}. EDF listede yoksa o EDF'nin tüm
        pencereleri **nöbetsiz** kabul edilir ve "negatif_no_future_seizure"
        ile işaretlenir.
    cfg : LabelConfig

    Dönüş
    -----
    (etiketlenmiş_df, raporlar)
    """
    if cfg is None:
        cfg = LabelConfig()

    required = {"edf_path", "window_start_s", "window_end_s"}
    if not required.issubset(features_df.columns):
        missing = required - set(features_df.columns)
        raise ValueError(f"Eksik sütunlar: {missing}")

    out = features_df.copy()

    # Her EDF için ayrı ayrı etiketle
    for edf_path, group in out.groupby("edf_path", sort=False):
        # group üzerinde çalışmak için indekse ihtiyaç var
        idx = group.index
        seizures = seizures_by_edf.get(str(edf_path), [])
        # Pencere bazlı benzersiz etiketleme
        label_by_key: Dict[tuple[float, float], WindowLabel] = {}
        for _, row in group[["window_start_s", "window_end_s"]].drop_duplicates().iterrows():
            key = (float(row["window_start_s"]), float(row["window_end_s"]))
            label_by_key[key] = label_window(key[0], key[1], seizures, cfg)

        for h in cfg.horizons_minutes:
            label_col = f"label_{h}min"
            reason_col = f"label_reason_{h}min"
            # Önce tüm grubu NaN/"" yap
            out.loc[idx, label_col] = np.nan
            out.loc[idx, reason_col] = ""
            for key, wl in label_by_key.items():
                m = (group["window_start_s"] == key[0]) & (group["window_end_s"] == key[1])
                target_idx = group.index[m]
                out.loc[target_idx, label_col] = wl.label(h)
                out.loc[target_idx, reason_col] = wl.reason(h)

    # Raporlar
    reports: List[LabelReport] = []
    for h in cfg.horizons_minutes:
        col = f"label_{h}min"
        reason_col = f"label_reason_{h}min"
        labels = out[col]
        n_total = len(labels)
        n_pos = int((labels == 1.0).sum())
        n_neg = int((labels == 0.0).sum())
        n_exc = int(labels.isna().sum())
        reasons = (
            out.loc[labels.isna(), reason_col]
            .value_counts()
            .to_dict()
        )
        reports.append(LabelReport(
            horizon=h,
            n_positive=n_pos,
            n_negative=n_neg,
            n_excluded=n_exc,
            n_total=n_total,
            exclusion_reasons=reasons,
        ))

    return out, reports


def reports_to_dataframe(reports: List[LabelReport]) -> pd.DataFrame:
    """Raporları CSV'ye yazılabilir DataFrame'e çevir."""
    return pd.DataFrame([r.to_row() for r in reports])
"""Skor serisini alarm dönemlerine dönüştür.

Kurallar:
    1. Skor >= threshold olan pencereler "aday" sayılır.
    2. Birbirine `merge_gap_s` içinde yakın aday pencereler tek bir
       "ham alarm" altında birleşir.
    3. Ham alarmın süresi `min_alarm_duration_s` altındaysa atılır.
    4. Kalan her alarm için:
       - start_s = ilk pencerenin başlangıcı
       - end_s   = son pencerenin bitişi
       - peak_score = aralıktaki en yüksek olasılık
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from .alarm_config import AlarmConfig


@dataclass
class AlarmEvent:
    edf_path: str
    patient_id: str | None
    start_s: float
    end_s: float
    peak_score: float
    n_windows: int

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class AlarmEventsResult:
    events: List[AlarmEvent] = field(default_factory=list)
    n_candidate_windows: int = 0
    n_merged_events: int = 0
    n_dropped_too_short: int = 0


def _group_close_candidates(
    times: np.ndarray, merge_gap_s: float
) -> List[tuple[int, int]]:
    """Ardışık zamanları `merge_gap_s` içinde grupla. (start_idx, end_idx) inclusive."""
    if times.size == 0:
        return []
    groups: List[tuple[int, int]] = []
    start = 0
    for i in range(1, times.size):
        if times[i] - times[i - 1] > merge_gap_s:
            groups.append((start, i - 1))
            start = i
    groups.append((start, times.size - 1))
    return groups


def extract_alarms(
    predictions_df: pd.DataFrame,
    alarm_cfg: AlarmConfig,
    score_col: str = "y_proba",
    time_col: str = "window_start_s",
    end_col: str = "window_end_s",
    group_col: str = "edf_path",
    patient_col: str = "patient_id",
) -> AlarmEventsResult:
    """Tahmin tablosundan (her satır bir pencere×kanal ya da pencere) alarm olayları üret.

    Girdi tablo **pencere bazlı olmalı** — aynı pencere için birden çok kanal
    varsa, önce kanal skorlarını birleştirmek gerekir. Bunu `aggregate_scores_by_window`
    fonksiyonu yapar.
    """
    required = {group_col, time_col, end_col, score_col}
    missing = required - set(predictions_df.columns)
    if missing:
        raise ValueError(f"Eksik sütunlar: {missing}")

    out = AlarmEventsResult()

    for edf_path, g in predictions_df.groupby(group_col, sort=False):
        g = g.sort_values(time_col).reset_index(drop=True)
        scores = g[score_col].to_numpy(dtype=float)
        times = g[time_col].to_numpy(dtype=float)
        ends = g[end_col].to_numpy(dtype=float)
        pid = g[patient_col].iloc[0] if patient_col in g.columns else None

        above = scores >= alarm_cfg.threshold
        if not above.any():
            continue

        cand_idx = np.where(above)[0]
        out.n_candidate_windows += int(cand_idx.size)
        cand_times = times[cand_idx]

        groups = _group_close_candidates(cand_times, alarm_cfg.merge_gap_s)
        for (lo, hi) in groups:
            abs_indices = cand_idx[lo:hi + 1]
            a = float(times[abs_indices[0]])
            b = float(ends[abs_indices[-1]])
            # Bir grup içinde tüm aday pencereler zaten above; süre kontrolü
            dur = b - a
            if dur < alarm_cfg.min_alarm_duration_s:
                out.n_dropped_too_short += 1
                continue
            peak = float(np.max(scores[abs_indices]))
            ev = AlarmEvent(
                edf_path=str(edf_path),
                patient_id=str(pid) if pid is not None else None,
                start_s=a,
                end_s=b,
                peak_score=peak,
                n_windows=int(abs_indices.size),
            )
            out.events.append(ev)
            out.n_merged_events += 1

    return out


def aggregate_scores_by_window(
    predictions_df: pd.DataFrame,
    score_col: str = "y_proba",
    group_cols: tuple = ("edf_path", "window_start_s", "window_end_s"),
    agg: str = "max",
    patient_col: str = "patient_id",
) -> pd.DataFrame:
    """Kanal başına skorları pencere başına tek skora indir.

    Aynı pencere içindeki kanallar için:
        - 'max'    -> en yüksek skor (en hassas)
        - 'mean'   -> ortalama (en muhafazakâr)
        - 'median' -> ortanca

    Nöbet uyarısı için genellikle 'max' tercih edilir; bir kanal uyarıyı
    tetiklerse alarm üretmek erken uyarı için anlamlıdır.
    """
    if agg not in {"max", "mean", "median"}:
        raise ValueError(f"agg '{agg}' desteklenmiyor (max|mean|median)")
    if score_col not in predictions_df.columns:
        raise ValueError(f"'{score_col}' sütunu yok")

    group_cols = list(group_cols)
    # patient_id gruba dâhil et (aynı pencere için sabit)
    extra = [patient_col] if patient_col in predictions_df.columns else []
    grouped = predictions_df.groupby(group_cols + extra, as_index=False, sort=False)
    if agg == "max":
        result = grouped.agg(**{score_col: (score_col, "max")})
    elif agg == "mean":
        result = grouped.agg(**{score_col: (score_col, "mean")})
    else:
        result = grouped.agg(**{score_col: (score_col, "median")})
    return result
"""Model eğitimi yapılandırması."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class ModelConfig:
    """Tek bir ufuk için model eğitim yapılandırması."""
    # Model seçimi: "logistic" | "random_forest" | "hist_gb"
    model_name: str = "logistic"

    # Özellik grubu: "time" | "freq" | "time+freq" | "time+freq+complex" | "all"
    feature_groups: str = "time+freq+complex"

    # Ön işleme
    scale_features: bool = True
    impute_strategy: str = "median"     # "median" | "mean" | "most_frequent"
    feature_selection: str | None = None  # None | "variance" | "univariate"
    feature_selection_k: int = 50

    # Hiperparametre araması
    random_search_n_iter: int = 20
    cv_folds: int = 3

    # Rastgelelik
    random_seed: int = 42

    # Zamansal split için minimum test süresi (saniye)
    test_fraction: float = 0.2

    def as_dict(self) -> dict:
        return asdict(self)


FEATURE_GROUP_PREFIXES = {
    "time": ("time_",),
    "freq": ("freq_",),
    "complex": ("complex_",),
    "qc": ("qc_",),  # QC özellikleri bilinçli olarak dışlanır
}


def resolve_feature_columns(columns: list[str], feature_groups: str) -> list[str]:
    """`feature_groups` string'ine göre özellik sütunlarını seç.

    Kabul edilen gruplar: time, freq, complex; '+' ile birleştirilebilir.
    QC sütunları hiçbir grupta yer almaz (bunlar kalite göstergesidir).
    Meta sütunlar (window_start_s, channel, ...) daima dışlanır.
    """
    meta_and_labels = (
        "edf_path", "patient_id", "channel",
        "window_index", "window_start_s", "window_end_s",
        "window_duration_s", "sfreq_used", "n_samples",
    )
    allowed_prefixes: list[str] = []
    for g in feature_groups.split("+"):
        g = g.strip()
        if g not in FEATURE_GROUP_PREFIXES:
            raise ValueError(
                f"Bilinmeyen özellik grubu: '{g}'. "
                f"Geçerliler: {list(FEATURE_GROUP_PREFIXES)}"
            )
        allowed_prefixes.extend(FEATURE_GROUP_PREFIXES[g])

    selected = []
    for c in columns:
        if c in meta_and_labels:
            continue
        if c.startswith("label_"):
            continue
        if c.startswith("label_reason_"):
            continue
        if any(c.startswith(p) for p in allowed_prefixes):
            selected.append(c)
    return selected
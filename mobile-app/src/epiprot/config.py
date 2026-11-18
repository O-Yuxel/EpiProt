"""Konfigürasyon — dataclass tabanlı, tek doğruluk kaynağı."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# CHB-MIT'te görülen tipik non-EEG kanal adları
# (kanal adından EEG olduğu kesin olarak çıkarılamayanlar hariç tutulur).
NON_EEG_CHANNEL_PATTERNS = (
    "ECG", "EKG", "EOG", "EMG", "IBI", "HR", "PULSE",
    "STIM", "MARK", "EVENT", "TRIG", "RESP", "SPO2",
    "TEMP", "ANNOT", "STATUS",
)

# CHB-MIT'te EEG olmayan ama sık görülen (bazı kayıtlarda başka) kanal listesi.
# Kural: ad "EEG" içermiyorsa ve bilinen non-EEG kalıplarından birini içermiyorsa,
# konservatif davranıp EEG kabul etmeyiz. Adı kesin EEG olduğu doğrulanamayan
# kanallar sessizce EEG sayılmaz.


@dataclass
class AuditConfig:
    """Aşama 1 — veri denetimi için yapılandırma."""
    data_dir: Path
    out_dir: Path
    max_files: int | None = None
    edf_glob: str = "**/*.edf"
    summary_glob: str = "**/*-summary.txt"
    # Anotasyonun EDF zaman eksenine eşlenmesi için tolerans (saniye).
    # CHB-MIT summary.txt'deki başlangıç zamanları kayıt başlangıcına göre saniyedir;
    # EDF header süresi ile son anotasyon zamanı arasındaki farkı kontrol ederiz.
    annotation_duration_tolerance_s: float = 5.0

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.out_dir = Path(self.out_dir)
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Veri klasörü bulunamadı: {self.data_dir}")

    def as_dict(self) -> dict:
        d = asdict(self)
        d["data_dir"] = str(self.data_dir)
        d["out_dir"] = str(self.out_dir)
        return d


@dataclass
class FileAuditRecord:
    """Tek bir EDF dosyası için denetim kaydı."""
    edf_path: str
    patient_id: str | None = None
    summary_path: str | None = None
    edf_ok: bool = False
    edf_error: str | None = None
    sampling_rate_hz: float | None = None
    duration_s: float | None = None
    n_channels_total: int | None = None
    eeg_channels: List[str] = field(default_factory=list)
    non_eeg_channels: List[str] = field(default_factory=list)
    unmatched_channels: List[str] = field(default_factory=list)
    n_seizures_in_summary: int = 0
    n_seizures_matched_to_this_file: int = 0
    annotations_matched: bool = False
    annotation_error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None

    def to_row(self) -> dict:
        d = asdict(self)
        d["eeg_channels"] = "|".join(d["eeg_channels"])
        d["non_eeg_channels"] = "|".join(d["non_eeg_channels"])
        d["unmatched_channels"] = "|".join(d["unmatched_channels"])
        return d
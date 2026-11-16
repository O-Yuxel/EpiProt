"""Özyinelemeli EDF ve summary dosyası keşfi."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass
class DiscoveryResult:
    edf_files: List[Path]
    summary_files: List[Path]
    data_root: Path


def discover_files(data_dir: Path, edf_glob: str, summary_glob: str, max_files: int | None) -> DiscoveryResult:
    data_dir = Path(data_dir)
    if not data_dir.exists():
        raise FileNotFoundError(f"Veri klasörü bulunamadı: {data_dir}")

    edfs = sorted(p for p in data_dir.glob(edf_glob) if p.is_file())
    summaries = sorted(p for p in data_dir.glob(summary_glob) if p.is_file())

    if max_files is not None and max_files > 0:
        edfs = edfs[:max_files]

    return DiscoveryResult(edf_files=edfs, summary_files=summaries, data_root=data_dir)


def patient_id_from_path(edf_path: Path) -> str | None:
    """chb01/.../chb01_01.edf -> 'chb01' (dosya adından)."""
    stem = edf_path.stem  # chb01_01
    if "_" in stem:
        cand = stem.split("_")[0]
        if cand.lower().startswith("chb"):
            return cand
    # Klasörden türet.
    for part in reversed(edf_path.parts):
        if part.lower().startswith("chb") and part[3:].isdigit():
            return part
    return None


def summary_for_patient(summary_files: List[Path], patient_id: str | None) -> Path | None:
    """Bir hastaya ait summary dosyasını bul."""
    if patient_id is None:
        return None
    # 1) Doğrudan dosya adı eşleşmesi: chb01-summary.txt
    for s in summary_files:
        if s.name.lower() == f"{patient_id.lower()}-summary.txt":
            return s
    # 2) Stem içinde patient_id geçen summary
    for s in summary_files:
        if patient_id.lower() in s.stem.lower():
            return s
    return None
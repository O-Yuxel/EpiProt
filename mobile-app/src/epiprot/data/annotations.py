"""CHB-MIT özet dosyası ayrıştırma.

Format referansı: https://physionet.org/content/chbmit/1.0.0/
Her summary.txt bir veya daha fazla 'File Name:' bloğu içerir.
Zamanlar, ilgili EDF kaydının başlangıcına göre SANİYE cinsindendir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class SeizureInterval:
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if self.end_s < self.start_s:
            raise ValueError(
                f"Geçersiz nöbet aralığı: start={self.start_s} > end={self.end_s}"
            )


@dataclass
class FileAnnotation:
    edf_filename: str
    file_start_time: Optional[str] = None
    file_end_time: Optional[str] = None
    n_seizures_declared: int = 0
    seizures: List[SeizureInterval] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.n_seizures_declared != len(self.seizures):
            # CHB-MIT'te bildirilen ile gerçek sayı bazen tutmaz; kaydı işaretle ama fırlatma.
            pass


@dataclass
class SummaryParseResult:
    summary_path: str
    files: List[FileAnnotation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    ok: bool = True
    error: Optional[str] = None


_FILE_NAME_RE = re.compile(r"^File Name:\s*(.+?)\s*$", re.IGNORECASE)
_START_RE = re.compile(r"^File Start Time:\s*(.+?)\s*$", re.IGNORECASE)
_END_RE = re.compile(r"^File End Time:\s*(.+?)\s*$", re.IGNORECASE)
_NUM_RE = re.compile(r"^Number of Seizures in File:\s*(\d+)\s*$", re.IGNORECASE)
_SS_RE = re.compile(r"^Seizure\s+(\d+)?\s*Start Time:\s*([0-9.]+)\s*seconds\s*$", re.IGNORECASE)
_SE_RE = re.compile(r"^Seizure\s+(\d+)?\s*End Time:\s*([0-9.]+)\s*seconds\s*$", re.IGNORECASE)


def parse_chbmit_summary(path: str | Path) -> SummaryParseResult:
    """CHB-MIT summary.txt dosyasını ayrıştır."""
    path = Path(path)
    result = SummaryParseResult(summary_path=str(path))

    if not path.exists():
        result.ok = False
        result.error = f"Dosya bulunamadı: {path}"
        return result

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result.ok = False
        result.error = f"Okuma hatası: {e}"
        return result

    current: Optional[FileAnnotation] = None
    pending_starts: dict[int, float] = {}
    pending_ends: dict[int, float] = {}

    def flush() -> None:
        nonlocal current, pending_starts, pending_ends
        if current is None:
            return
        # Seizure start/end çiftlerini eşleştir.
        idxs = sorted(set(pending_starts) | set(pending_ends))
        for i in idxs:
            if i not in pending_starts or i not in pending_ends:
                result.warnings.append(
                    f"{current.edf_filename}: nöbet {i} için start/end eşleşmedi "
                    f"(start={pending_starts.get(i)}, end={pending_ends.get(i)})"
                )
                continue
            try:
                current.seizures.append(
                    SeizureInterval(start_s=pending_starts[i], end_s=pending_ends[i])
                )
            except ValueError as e:
                result.warnings.append(f"{current.edf_filename}: {e}")
        current.seizures.sort(key=lambda s: s.start_s)
        if current.n_seizures_declared != len(current.seizures):
            result.warnings.append(
                f"{current.edf_filename}: bildirilen={current.n_seizures_declared}, "
                f"ayrıştırılan={len(current.seizures)}"
            )
        result.files.append(current)
        current, pending_starts, pending_ends = None, {}, {}

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        m = _FILE_NAME_RE.match(line)
        if m:
            flush()
            current = FileAnnotation(edf_filename=m.group(1))
            continue

        if current is None:
            # Başlık öncesi satırlar (bazı dosyalarda) sessizce atlanır.
            continue

        m = _START_RE.match(line)
        if m:
            current.file_start_time = m.group(1)
            continue
        m = _END_RE.match(line)
        if m:
            current.file_end_time = m.group(1)
            continue
        m = _NUM_RE.match(line)
        if m:
            current.n_seizures_declared = int(m.group(1))
            continue
        m = _SS_RE.match(line)
        if m:
            idx = int(m.group(1)) if m.group(1) else 1
            pending_starts[idx] = float(m.group(2))
            continue
        m = _SE_RE.match(line)
        if m:
            idx = int(m.group(1)) if m.group(1) else 1
            pending_ends[idx] = float(m.group(2))
            continue

        # Tanınmayan satır — uyarıya ekle, atlamayı sessiz yapma.
        result.warnings.append(f"satır {lineno} tanınmadı: {line!r}")

    flush()
    return result


def index_annotations_by_filename(
    parse_results: List[SummaryParseResult],
) -> dict[str, List[FileAnnotation]]:
    """Dosya adı -> [FileAnnotation] indeksi oluştur.

    Aynı dosya adı birden fazla summary'de geçebilir (kopya); bu durum
    çağıran tarafta çakışma olarak işaretlenmelidir.
    """
    index: dict[str, List[FileAnnotation]] = {}
    for pr in parse_results:
        for fa in pr.files:
            index.setdefault(fa.edf_filename, []).append(fa)
    return index
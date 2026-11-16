"""annotations.py için birim testleri."""
from __future__ import annotations

from pathlib import Path

from epiprot.data.annotations import (
    index_annotations_by_filename,
    parse_chbmit_summary,
)


def test_parse_basic_summary(tmp_path: Path) -> None:
    f = tmp_path / "chb99-summary.txt"
    f.write_text(
        "File Name: chb99_01.edf\n"
        "File Start Time: 11:42:54\n"
        "File End Time: 12:42:54\n"
        "Number of Seizures in File: 0\n"
        "\n"
        "File Name: chb99_02.edf\n"
        "File Start Time: 12:42:54\n"
        "File End Time: 13:42:54\n"
        "Number of Seizures in File: 2\n"
        "Seizure Start Time: 100 seconds\n"
        "Seizure End Time: 130 seconds\n"
        "Seizure 2 Start Time: 500 seconds\n"
        "Seizure 2 End Time: 540 seconds\n",
        encoding="utf-8",
    )
    pr = parse_chbmit_summary(f)
    assert pr.ok
    assert pr.error is None
    assert len(pr.files) == 2

    fa1, fa2 = pr.files
    assert fa1.edf_filename == "chb99_01.edf"
    assert fa1.n_seizures_declared == 0
    assert fa1.seizures == []

    assert fa2.edf_filename == "chb99_02.edf"
    assert fa2.n_seizures_declared == 2
    assert len(fa2.seizures) == 2
    assert fa2.seizures[0].start_s == 100.0
    assert fa2.seizures[0].end_s == 130.0
    assert fa2.seizures[1].start_s == 500.0
    assert fa2.seizures[1].end_s == 540.0


def test_parse_missing_file(tmp_path: Path) -> None:
    pr = parse_chbmit_summary(tmp_path / "does_not_exist.txt")
    assert not pr.ok
    assert "bulunamadı" in (pr.error or "")


def test_parse_unmatched_start_warns(tmp_path: Path) -> None:
    f = tmp_path / "chb99-summary.txt"
    f.write_text(
        "File Name: chb99_01.edf\n"
        "Number of Seizures in File: 1\n"
        "Seizure Start Time: 100 seconds\n",
        encoding="utf-8",
    )
    pr = parse_chbmit_summary(f)
    assert pr.ok
    # start var, end yok -> nöbet eklenmez, uyarı üretilir.
    assert len(pr.files) == 1
    assert pr.files[0].seizures == []
    assert any("eşleşmedi" in w for w in pr.warnings)


def test_parse_invalid_interval_warns(tmp_path: Path) -> None:
    f = tmp_path / "chb99-summary.txt"
    f.write_text(
        "File Name: chb99_01.edf\n"
        "Number of Seizures in File: 1\n"
        "Seizure Start Time: 200 seconds\n"
        "Seizure End Time: 100 seconds\n",
        encoding="utf-8",
    )
    pr = parse_chbmit_summary(f)
    assert pr.ok
    assert pr.files[0].seizures == []
    assert any("Geçersiz" in w or "geçersiz" in w.lower() for w in pr.warnings)


def test_index_annotations_by_filename(tmp_path: Path) -> None:
    f = tmp_path / "chb99-summary.txt"
    f.write_text(
        "File Name: chb99_01.edf\n"
        "Number of Seizures in File: 0\n",
        encoding="utf-8",
    )
    pr = parse_chbmit_summary(f)
    idx = index_annotations_by_filename([pr])
    assert "chb99_01.edf" in idx
    assert len(idx["chb99_01.edf"]) == 1
"""discovery.py için birim testleri."""
from __future__ import annotations

from pathlib import Path

from epiprot.data.discovery import (
    discover_files,
    patient_id_from_path,
    summary_for_patient,
)


def test_discover_files_and_max(tmp_path: Path) -> None:
    (tmp_path / "chb01").mkdir()
    (tmp_path / "chb01" / "chb01_01.edf").write_bytes(b"x")
    (tmp_path / "chb01" / "chb01_02.edf").write_bytes(b"x")
    (tmp_path / "chb01" / "chb01-summary.txt").write_text("")

    res = discover_files(tmp_path, "**/*.edf", "**/*-summary.txt", max_files=None)
    assert len(res.edf_files) == 2
    assert len(res.summary_files) == 1

    res2 = discover_files(tmp_path, "**/*.edf", "**/*-summary.txt", max_files=1)
    assert len(res2.edf_files) == 1


def test_patient_id_from_edf_path() -> None:
    assert patient_id_from_path(Path("/a/chb01/chb01_01.edf")) == "chb01"
    assert patient_id_from_path(Path("/a/chb23/chb23_45.edf")) == "chb23"


def test_summary_for_patient(tmp_path: Path) -> None:
    s1 = tmp_path / "chb01-summary.txt"
    s2 = tmp_path / "chb02-summary.txt"
    s1.write_text("")
    s2.write_text("")
    assert summary_for_patient([s1, s2], "chb01") == s1
    assert summary_for_patient([s1, s2], "chb02") == s2
    assert summary_for_patient([s1, s2], "chb99") is None
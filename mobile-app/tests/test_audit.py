"""audit.py uçtan uca testi (sentetik veri)."""
from __future__ import annotations

from pathlib import Path

from epiprot.config import AuditConfig
from epiprot.data.audit import run_audit
from tests.fixtures.make_synthetic import build_synthetic_chbmit


def test_run_audit_end_to_end(tmp_path: Path) -> None:
    data_root = build_synthetic_chbmit(
        tmp_path / "chbmit",
        n_patients=1,
        files_per_patient=2,
        duration_s=60.0,
        sfreq=128.0,
    )
    out = tmp_path / "out"
    cfg = AuditConfig(data_dir=data_root, out_dir=out, max_files=None)
    audit_df, seizures_df = run_audit(cfg)

    # 2 EDF de başarıyla okunmalı.
    assert len(audit_df) == 2
    assert audit_df["edf_ok"].all()

    # İlk dosyada 1 nöbet, ikincide 0.
    assert (audit_df["n_seizures_matched_to_this_file"] == [1, 0]).all()
    assert len(seizures_df) == 1
    row = seizures_df.iloc[0]
    assert row["seizure_start_s"] == 20.0
    assert row["seizure_end_s"] == 35.0
    assert row["patient_id"] == "chb01"

    # Çıktı dosyaları var mı?
    assert (out / "data_audit.csv").exists()
    assert (out / "seizure_annotations.csv").exists()
    assert (out / "logs" / "processing.log").exists()


def test_run_audit_skips_edf_without_annotations(tmp_path: Path) -> None:
    # Summary'de olmayan bir EDF ekle -> eşleşme hatası beklenir.
    data_root = build_synthetic_chbmit(tmp_path / "chbmit", n_patients=1, files_per_patient=1)
    (data_root / "chb01" / "chb01_99.edf").write_bytes(b"not a real edf")

    out = tmp_path / "out"
    cfg = AuditConfig(data_dir=data_root, out_dir=out)
    audit_df, _ = run_audit(cfg)

    # Bozuk EDF satırı atlanmış olmalı.
    bad = audit_df[audit_df["edf_path"].str.endswith("chb01_99.edf")]
    assert len(bad) == 1
    assert bad.iloc[0]["skipped"] is True or bad.iloc[0]["skipped"] == True  # noqa: E712
    assert bad.iloc[0]["skip_reason"]
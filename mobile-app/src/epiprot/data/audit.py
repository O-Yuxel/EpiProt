"""Aşama 1 — CHB-MIT veri denetimi.

Kullanım:
    python -m epiprot.data.audit \
        --data-dir /path/to/chbmit \
        --out-dir epiprot_results \
        --max-files 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

import pandas as pd

from ..config import AuditConfig, FileAuditRecord
from ..logging_utils import setup_logging
from .annotations import FileAnnotation, index_annotations_by_filename, parse_chbmit_summary
from .discovery import discover_files, patient_id_from_path, summary_for_patient
from .edf_reader import read_edf_info


def _patient_id_from_summary_path(summary_path: str) -> str | None:
    """'.../chb01-summary.txt' -> 'chb01'."""
    stem = Path(summary_path).stem  # chb01-summary
    if "-summary" in stem:
        cand = stem.split("-summary")[0]
        if cand.lower().startswith("chb"):
            return cand
    return None


def _match_annotations_to_edf(
    edf_name: str,
    patient_index: dict[str, List[FileAnnotation]],
) -> tuple[FileAnnotation | None, str | None]:
    """EDF dosya adına göre summary'den ilgili FileAnnotation'ı seç."""
    candidates = patient_index.get(edf_name, [])
    if not candidates:
        return None, f"summary'de '{edf_name}' için kayıt yok"
    if len(candidates) > 1:
        return None, f"'{edf_name}' için {len(candidates)} çakışan summary kaydı"
    return candidates[0], None


def run_audit(cfg: AuditConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Denetimi çalıştır; (data_audit_df, seizures_df) döndür."""
    logger = setup_logging(cfg.out_dir)
    logger.info("EpiProt Aşama 1 — Veri denetimi başlıyor")
    logger.info("Konfigürasyon: %s", cfg.as_dict())

    disc = discover_files(cfg.data_dir, cfg.edf_glob, cfg.summary_glob, cfg.max_files)
    logger.info("Bulunan EDF: %d, summary: %d", len(disc.edf_files), len(disc.summary_files))

    if not disc.edf_files:
        logger.error("Hiç EDF dosyası bulunamadı: %s", cfg.data_dir)

    # Tüm summary'leri parse et.
    parse_results = []
    for s in disc.summary_files:
        pr = parse_chbmit_summary(s)
        parse_results.append(pr)
        if not pr.ok:
            logger.error("Summary okunamadı: %s — %s", s, pr.error)
        for w in pr.warnings:
            logger.warning("Summary uyarısı [%s]: %s", s.name, w)

    # Hasta başına: dosya adı -> FileAnnotation indeksi.
    patient_to_index: dict[str, dict[str, List[FileAnnotation]]] = {}
    for pr in parse_results:
        if not pr.ok:
            continue
        pid = _patient_id_from_summary_path(pr.summary_path)
        if pid is None:
            logger.warning("Summary'den hasta kimliği çıkarılamadı: %s", pr.summary_path)
            continue
        idx = index_annotations_by_filename([pr])
        patient_to_index.setdefault(pid, {}).update(idx)

    audit_rows: list[FileAuditRecord] = []
    seizure_rows: list[dict] = []

    for edf_path in disc.edf_files:
        pid = patient_id_from_path(edf_path)
        rec = FileAuditRecord(edf_path=str(edf_path), patient_id=pid)

        # 1) EDF başlığını oku.
        info = read_edf_info(edf_path)
        rec.edf_ok = info.ok
        rec.edf_error = info.error
        rec.sampling_rate_hz = info.sampling_rate_hz
        rec.duration_s = info.duration_s
        rec.n_channels_total = info.n_channels_total
        rec.eeg_channels = info.eeg_channels
        rec.non_eeg_channels = info.non_eeg_channels
        rec.unmatched_channels = info.unmatched_channels

        if not info.ok:
            rec.skipped = True
            rec.skip_reason = f"EDF okunamadı: {info.error}"
            logger.error("%s — %s", edf_path.name, rec.skip_reason)
            audit_rows.append(rec)
            continue

        if not info.eeg_channels:
            rec.skipped = True
            rec.skip_reason = "EEG kanalı bulunamadı"
            logger.warning("%s — %s (kanallar: %s)", edf_path.name, rec.skip_reason, info.all_channels)
            audit_rows.append(rec)
            continue

        if info.unmatched_channels:
            logger.warning(
                "%s — sınıflandırılamayan kanallar EEG'ye katılmadı: %s",
                edf_path.name, info.unmatched_channels,
            )

        # 2) Anotasyon eşleştir.
        if pid is None or pid not in patient_to_index:
            rec.annotation_error = f"Hasta '{pid}' için summary indeksi yok"
            logger.warning("%s — %s", edf_path.name, rec.annotation_error)
            audit_rows.append(rec)
            continue

        rec.summary_path = str(summary_for_patient(disc.summary_files, pid) or "")
        fa, err = _match_annotations_to_edf(edf_path.name, patient_to_index[pid])
        if err:
            rec.annotation_error = err
            logger.warning("%s — %s", edf_path.name, err)
            audit_rows.append(rec)
            continue

        rec.n_seizures_in_summary = len(fa.seizures)

        # 3) Anotasyon sürelerini EDF süresiyle tutarlılık için kontrol et.
        if info.duration_s is not None:
            for i, sz in enumerate(fa.seizures):
                if sz.end_s > info.duration_s + cfg.annotation_duration_tolerance_s:
                    rec.annotation_error = (
                        f"nöbet {i} bitiş {sz.end_s}s > EDF süresi "
                        f"{info.duration_s:.1f}s (tolerans "
                        f"{cfg.annotation_duration_tolerance_s}s)"
                    )
                    logger.warning("%s — %s", edf_path.name, rec.annotation_error)
                    break

        # 4) Nöbetleri bu EDF için kaydet.
        rec.n_seizures_matched_to_this_file = len(fa.seizures)
        rec.annotations_matched = True
        for i, sz in enumerate(fa.seizures):
            seizure_rows.append({
                "patient_id": pid,
                "edf_path": str(edf_path),
                "edf_filename": edf_path.name,
                "seizure_index": i,
                "seizure_start_s": sz.start_s,
                "seizure_end_s": sz.end_s,
                "seizure_duration_s": sz.end_s - sz.start_s,
                "edf_duration_s": info.duration_s,
                "edf_sampling_rate_hz": info.sampling_rate_hz,
                "n_eeg_channels": len(info.eeg_channels),
            })

        audit_rows.append(rec)

    audit_df = pd.DataFrame([r.to_row() for r in audit_rows])
    seizures_df = pd.DataFrame(seizure_rows)

    # Çıktıları yaz.
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    audit_path = cfg.out_dir / "data_audit.csv"
    seizures_path = cfg.out_dir / "seizure_annotations.csv"
    audit_df.to_csv(audit_path, index=False)
    seizures_df.to_csv(seizures_path, index=False)
    logger.info("data_audit.csv yazıldı: %s (%d satır)", audit_path, len(audit_df))
    logger.info("seizure_annotations.csv yazıldı: %s (%d satır)", seizures_path, len(seizures_df))

    # Özet log.
    if len(audit_df) > 0:
        n_ok = int(audit_df["edf_ok"].sum())
        n_skipped = int(audit_df["skipped"].sum())
        n_with_seiz = int((audit_df["n_seizures_matched_to_this_file"] > 0).sum())
        logger.info(
            "Özet: %d/%d EDF okundu, %d atlandı, %d dosyada nöbet var, toplam %d nöbet anotasyonu",
            n_ok, len(audit_df), n_skipped, n_with_seiz, len(seizures_df),
        )

    return audit_df, seizures_df


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="epiprot.data.audit",
        description="EpiProt Aşama 1 — CHB-MIT veri denetimi",
    )
    p.add_argument("--data-dir", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--max-files", type=int, default=None,
                   help="Yalnızca ilk N EDF dosyasını işle (test modu)")
    p.add_argument("--annotation-duration-tolerance-s", type=float, default=5.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    try:
        cfg = AuditConfig(
            data_dir=args.data_dir,
            out_dir=args.out_dir,
            max_files=args.max_files,
            annotation_duration_tolerance_s=args.annotation_duration_tolerance_s,
        )
    except FileNotFoundError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2

    try:
        run_audit(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"BEKLENMEYEN HATA: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
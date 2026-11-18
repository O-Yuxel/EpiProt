"""EpiProt CLI — uçtan uca araştırma hattı.

Kullanım:
    python -m epiprot.cli --data-dir /path/to/chbmit --out-dir epiprot_results
    python -m epiprot.cli --data-dir /path/to/chbmit --out-dir epiprot_results --max-files 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .config import AuditConfig
from .data.annotations import parse_chbmit_summary
from .data.audit import run_audit
from .data.discovery import discover_files, patient_id_from_path
from .experiments.compare import run_comparison
from .features.config import FeatureConfig
from .features.extractor import extract_many
from .labeling.apply import apply_labels, reports_to_dataframe
from .labeling.config import LabelConfig
from .labeling.horizons import Seizure
from .logging_utils import setup_logging
from .modeling.config import ModelConfig
from .evaluation.alarm_config import AlarmConfig
from .evaluation.alarm_events import aggregate_scores_by_window, extract_alarms
from .evaluation.event_metrics import compute_patient_event_metrics
from .evaluation.report import event_metrics_to_dataframe, matches_to_dataframe, false_alarms_to_dataframe
from .experiments.feature_importance import extract_feature_importance, summarize_by_family, top_k_subset


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="epiprot",
        description="EpiProt — EEG tabanlı nöbet ön tahmini araştırma prototipi",
    )
    p.add_argument("--data-dir", required=True, type=Path,
                   help="CHB-MIT kök klasörü")
    p.add_argument("--out-dir", required=True, type=Path,
                   help="Çıktı klasörü (epiprot_results)")
    p.add_argument("--max-files", type=int, default=None,
                   help="Test modu: yalnız ilk N EDF dosyasını işle")
    p.add_argument("--horizons", type=int, nargs="+",
                   default=[30, 45, 60, 75, 90],
                   help="Tahmin ufukları (dakika)")
    p.add_argument("--window-seconds", type=float, default=10.0)
    p.add_argument("--prediction-gap-minutes", type=float, default=5.0)
    p.add_argument("--negative-exclusion-hours", type=float, default=4.0)
    p.add_argument("--models", nargs="+", default=["logistic"],
                   choices=["logistic", "random_forest", "hist_gb"])
    p.add_argument("--feature-groups", nargs="+", default=["C_time_freq"],
                   choices=["A_time", "B_freq", "C_time_freq", "D_time_freq_complex"])
    p.add_argument("--top-features", type=int, default=None,
                   help="En önemli K özelliği kullan (10 gibi)")
    p.add_argument("--random-seed", type=int, default=42)
    p.add_argument("--random-search-n-iter", type=int, default=5)
    p.add_argument("--cv-folds", type=int, default=3)
    p.add_argument("--skip-audit", action="store_true",
                   help="Denetimi atla (data_audit.csv zaten var)")
    p.add_argument("--skip-features", action="store_true",
                   help="Özellik çıkarmayı atla (feature_table.csv zaten var)")
    p.add_argument("--top-k-features", type=int, default=None,
                   help="Önem sırasına göre en önemli K özelliği kullan (ilk çalıştırmada belirlenir)")
    return p


def _seizures_from_summaries(summary_paths: list[Path]) -> dict[str, list[Seizure]]:
    """{edf_dosya_adı: [Seizure, ...]} indeksi.

    Not: EDF dosya adları CHB-MIT'te evrensel olarak benzersizdir
    (chb01_01.edf, chb02_05.edf, ...). Yine de tam yol eşleşmesi için
    çağıran taraf EDF adını günceller.
    """
    idx: dict[str, list[Seizure]] = {}
    for sp in summary_paths:
        pr = parse_chbmit_summary(sp)
        if not pr.ok:
            continue
        for fa in pr.files:
            idx[fa.edf_filename] = [
                Seizure(start_s=sz.start_s, end_s=sz.end_s)
                for sz in fa.seizures
            ]
    return idx


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    logger = setup_logging(args.out_dir)

    logger.info("EpiProt başlıyor | data=%s | out=%s", args.data_dir, args.out_dir)
    logger.info("Konfigürasyon: %s", vars(args))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # --- Aşama 1: Denetim ---
    audit_csv = args.out_dir / "data_audit.csv"
    seizures_csv = args.out_dir / "seizure_annotations.csv"
    if not args.skip_audit or not audit_csv.exists():
        logger.info("=== Aşama 1: Veri denetimi ===")
        cfg = AuditConfig(
            data_dir=args.data_dir,
            out_dir=args.out_dir,
            max_files=args.max_files,
        )
        run_audit(cfg)
    else:
        logger.info("Aşama 1 atlandı (data_audit.csv mevcut)")

    # --- Aşama 2: Özellikler ---
    features_csv = args.out_dir / "feature_table.csv"
    if not args.skip_features or not features_csv.exists():
        logger.info("=== Aşama 2: Özellik çıkarma ===")
        disc = discover_files(
            args.data_dir, "**/*.edf", "**/*-summary.txt", args.max_files
        )
        feat_cfg = FeatureConfig(window_seconds=args.window_seconds)
        df, failures = extract_many(
            disc.edf_files, feat_cfg,
            patient_id_of=patient_id_from_path,
            logger=logger,
        )
        if df.empty:
            logger.error("Hiç özellik çıkarılamadı")
            return 1
        df.to_csv(features_csv, index=False)
        logger.info("feature_table.csv yazıldı: %d satır", len(df))
        if failures:
            (args.out_dir / "feature_failures.json").write_text(
                json.dumps(failures, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    else:
        logger.info("Aşama 2 atlandı (feature_table.csv mevcut)")
        df = pd.read_csv(features_csv)

    # --- Aşama 3: Etiketleme ---
    logger.info("=== Aşama 3: Etiketleme ===")
    # seizure_annotations.csv -> {edf_path: [Seizure]}
    # Boş veya geçersiz CSV dosyalarına karşı koruma
    try:
        sz_df = pd.read_csv(seizures_csv) if seizures_csv.exists() else pd.DataFrame()
    except pd.errors.EmptyDataError:
        sz_df = pd.DataFrame()
    seizures_by_edf: dict[str, list[Seizure]] = {}
    if not sz_df.empty:
        for edf_path, g in sz_df.groupby("edf_path"):
            seizures_by_edf[str(edf_path)] = [
                Seizure(start_s=float(r["seizure_start_s"]),
                        end_s=float(r["seizure_end_s"]))
                for _, r in g.iterrows()
            ]

    label_cfg = LabelConfig(
        horizons_minutes=args.horizons,
        prediction_gap_minutes=args.prediction_gap_minutes,
        negative_exclusion_hours=args.negative_exclusion_hours,
    )
    df_labeled, reports = apply_labels(df, seizures_by_edf, label_cfg)
    df_labeled.to_csv(args.out_dir / "feature_table_labeled.csv", index=False)
    reports_df = reports_to_dataframe(reports)
    reports_df.to_csv(args.out_dir / "label_counts.csv", index=False)
    logger.info("Etiketleme tamam:\n%s", reports_df.to_string())

    # --- Aşama 4+6: Model karşılaştırma ---
    logger.info("=== Aşama 4+6: Model eğitimi ve karşılaştırma ===")
    all_comparisons = []
    alarm_cfg = AlarmConfig(threshold=0.70, min_alarm_duration_s=60.0, merge_gap_s=600.0)
    all_event_metrics = []

    df_labeled.attrs["out_dir"] = args.out_dir
    if args.top_features is not None:
        top10 = ['freq_spectral_centroid_hz', 'freq_gamma_rel', 'freq_delta_rel',
                 'complex_hjorth_mobility', 'freq_alpha_abs_uv2', 'freq_beta_rel',
                 'time_rms_uv', 'time_std_uv', 'freq_alpha_rel', 'time_zero_crossing_rate']
        top_k = top10[:args.top_features]
        keep_cols = set(top_k) | {'edf_path', 'patient_id', 'channel', 'window_start_s', 
                                  'window_end_s', 'window_duration_s', 'label_30min', 
                                  'label_45min', 'label_60min', 'label_75min', 'label_90min'}
        # Diğer ufuklar için de etiket sütunlarını koru (varsa)
        for h in args.horizons:
            keep_cols.add(f'label_{h}min')
            keep_cols.add(f'label_reason_{h}min')
        
        existing = [c for c in df_labeled.columns if c in keep_cols]
        df_labeled = df_labeled[existing].copy()
        logger.info("En önemli %d özellik kullanılacak: %s", args.top_features, top_k)
    for h in args.horizons:
        results, cmp_df = run_comparison(
            df_labeled,
            horizon_min=h,
            model_names=args.models,
            feature_groups_keys=args.feature_groups,
            random_search_n_iter=args.random_search_n_iter,
            cv_folds=args.cv_folds,
            random_seed=args.random_seed,
            logger=logger,
        )
        all_comparisons.append(cmp_df)

        # --- AŞAMA 5: Olay Düzeyi (Alarm) Değerlendirmesi ---
        for res in results:
            if res.status != "ok" or res.artifact_path is None:
                continue
            try:
                from joblib import load
                model_data = load(res.artifact_path)
                model = model_data["model"]
                feat_cols = model_data["feature_columns"]

                importance_df = extract_feature_importance(model, feat_cols)
                if not importance_df.empty:
                    safe_name = res.feature_groups.replace("+", "_")
                    importance_df.to_csv(
                        args.out_dir / f"feature_importance_{h}min_{safe_name}.csv",
                        index=False,
                    )
                    family_df = summarize_by_family(importance_df)
                    family_df.to_csv(
                        args.out_dir / f"feature_family_{h}min_{safe_name}.csv",
                        index=False,
                    )
                    top10 = importance_df.head(10)
                    logger.info(
                        "Ufuk %d | Özellik aileleri:\n%s",
                        h, family_df.to_string(),
                    )
                    logger.info(
                        "Ufuk %d | İlk 10 önemli özellik:\n%s",
                        h,
                        top10[["rank", "feature", "importance", "cumulative_importance"]].to_string(),
                    )
                    n_for_80 = (importance_df["cumulative_importance"] < 0.8).sum() + 1
                    logger.info(
                        "Ufuk %d | Kümülatif önemin %%80'i için gereken özellik: %d / %d",
                        h, n_for_80, len(importance_df),
                    )

                test_df = df_labeled.loc[res.split.test].copy()
                if test_df.empty: continue

                # 1. Pencereler için olasılık tahmini yap
                X_test = test_df[feat_cols].to_numpy(dtype=float)
                test_df["y_proba"] = model.predict_proba(X_test)[:, 1]

                # 2. Kanal bazlı tahminleri pencere bazına indir (max)
                window_df = aggregate_scores_by_window(test_df, agg="max")

                # 3. Alarm olaylarını çıkar
                alarms = extract_alarms(window_df, alarm_cfg)

                # 4. Hasta bazlı metrikleri hesapla (Şimdilik sadece chb01 var)
                edf_durations = test_df.groupby("edf_path")["window_end_s"].max().to_dict()
                patient_metrics = compute_patient_event_metrics(
                    patient_id="chb01",
                    alarms=alarms.events,
                    seizures_by_edf=seizures_by_edf,
                    edf_durations_s=edf_durations,
                    cfg=alarm_cfg
                )
                
                # Özet log
                logger.info("Alarm [%s / %dh] | Nöbet: %d | Yakalanan: %d (%%%.1f) | Yanlış Alarm: %d | Lead (Med): %.1f dk",
                            res.feature_groups, h, patient_metrics.n_seizures, patient_metrics.n_seizures_caught,
                            patient_metrics.seizure_detection_rate * 100 if patient_metrics.n_seizures > 0 else 0,
                            patient_metrics.n_false_alarms, patient_metrics.median_lead_minutes)

                # CSV için kaydet
                ev_df = event_metrics_to_dataframe([patient_metrics])
                ev_df["feature_group"] = res.feature_groups
                ev_df["horizon_min"] = h
                all_event_metrics.append(ev_df)

            except Exception as e:
                logger.error("Alarm değerlendirmesi başarısız [%s]: %s", res.feature_groups, e)

    comp_df = pd.concat(all_comparisons, ignore_index=True)
    comp_df.to_csv(args.out_dir / "horizon_comparison.csv", index=False)
    logger.info("horizon_comparison.csv yazıldı (%d satır)", len(comp_df))
    logger.info("EpiProt tamamlandı")
    if all_event_metrics:
        event_df = pd.concat(all_event_metrics, ignore_index=True)
        event_df.to_csv(args.out_dir / "event_level_metrics.csv", index=False)
        logger.info("event_level_metrics.csv yazıldı")
    return 0


if __name__ == "__main__":
    sys.exit(main())
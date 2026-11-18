"""CNN CLI — ayrı komut satırı."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.annotations import parse_chbmit_summary
from ..data.discovery import discover_files
from ..labeling.config import LabelConfig
from ..labeling.horizons import Seizure
from ..logging_utils import setup_logging
from .dataset import build_split
from .tensor_builder import (
    build_patient_tensors, load_patient_tensors, save_patient_tensors,
)
from .trainer import TrainingConfig, predict, train_cnn


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="epiprot.cnn.cli")
    p.add_argument("--data-dir", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--tensors-dir", type=Path, default=None,
                   help="Hasta tensörlerinin .npz olarak saklanacağı klasör (default: out_dir/cnn_tensors)")
    p.add_argument("--patients", nargs="+", default=None,
                   help="Sadece bu hastaları işle (default: hepsi)")
    p.add_argument("--test-patients", nargs="+", default=None,
                   help="Test için ayrılacak hastalar (default: son 3 hasta)")
    p.add_argument("--horizons", type=int, nargs="+", default=[30])
    p.add_argument("--window-seconds", type=float, default=10.0)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--random-seed", type=int, default=42)
    p.add_argument("--skip-tensor-build", action="store_true",
                   help="Tensörler zaten varsa atla")
    return p


def _seizures_by_edf(summary_paths: list[Path]) -> dict[str, list[Seizure]]:
    idx = {}
    for sp in summary_paths:
        pr = parse_chbmit_summary(sp)
        if not pr.ok:
            continue
        for fa in pr.files:
            idx[fa.edf_filename] = [Seizure(start_s=sz.start_s, end_s=sz.end_s)
                                    for sz in fa.seizures]
    return idx


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    logger = setup_logging(args.out_dir)
    tensors_dir = args.tensors_dir or (args.out_dir / "cnn_tensors")
    tensors_dir.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("CNN CLI başlıyor | data=%s | tensors=%s", args.data_dir, tensors_dir)

    # 1) Hasta listesi
    disc = discover_files(args.data_dir, "**/*.edf", "**/*-summary.txt", None)
    if args.patients:
        selected = set(args.patients)
        edfs = [p for p in disc.edf_files
                if any(part in selected for part in p.parts)]
    else:
        edfs = disc.edf_files

    # Hastaya göre grupla
    from collections import defaultdict
    by_patient = defaultdict(list)
    for p in edfs:
        # chb01/chb01_01.edf → chb01
        pid = None
        for part in p.parts:
            if part.lower().startswith("chb") and part[3:].isdigit():
                pid = part
                break
        if pid:
            by_patient[pid].append(p)

    logger.info("Hastalar: %s", sorted(by_patient.keys()))

    # 2) Tensörleri oluştur veya yükle
    label_cfg = LabelConfig(horizons_minutes=args.horizons)
    all_tensors = {}
    for pid in sorted(by_patient.keys()):
        npz_path = tensors_dir / f"{pid}.npz"
        if args.skip_tensor_build and npz_path.exists():
            logger.info("[%s] tensör yükleniyor: %s", pid, npz_path)
            all_tensors[pid] = load_patient_tensors(npz_path)
        else:
            logger.info("[%s] tensör oluşturuluyor (%d EDF)", pid, len(by_patient[pid]))
            # Bu hastanın summary'sini bul
            summary = next((s for s in disc.summary_files
                            if pid in s.name), None)
            sz_by_edf = _seizures_by_edf([summary]) if summary else {}
            try:
                t = build_patient_tensors(
                    patient_id=pid,
                    edf_paths=by_patient[pid],
                    seizures_by_edf=sz_by_edf,
                    window_seconds=args.window_seconds,
                    label_cfg=label_cfg,
                    logger=logger,
                )
                save_patient_tensors(t, npz_path)
                all_tensors[pid] = t
                logger.info("[%s] %d pencere, %d kanal, X=%s",
                            pid, len(t.X), len(t.channels), t.X.shape)
            except Exception as e:
                logger.error("[%s] tensör oluşturma başarısız: %s", pid, e)

    if not all_tensors:
        logger.error("Hiç tensör yok, çıkılıyor")
        return 1

    # 3) Test hastalarını belirle
    pids = sorted(all_tensors.keys())
    if args.test_patients:
        test_pids = [p for p in args.test_patients if p in all_tensors]
    else:
        test_pids = pids[-3:]  # son 3 hasta
    logger.info("Test hastaları: %s | Train: %s",
                test_pids, [p for p in pids if p not in test_pids])

    # 4) Her ufuk için eğit
    for h in args.horizons:
        logger.info("=== Ufuk %d dk ===", h)
        try:
            split = build_split(all_tensors, horizon_min=h,
                                test_patient_ids=test_pids)
        except Exception as e:
            logger.error("Split başarısız [%dh]: %s", h, e)
            continue

        cfg = TrainingConfig(
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.lr,
            random_seed=args.random_seed,
        )
        result = train_cnn(split, horizon_min=h, cfg=cfg, logger=logger)

        # Test metrikleri
        from sklearn.metrics import (roc_auc_score, recall_score,
                                     precision_score, f1_score)
        probs = predict(result.model, split.test_X, device=cfg.device,
                        mean=result.mean, std=result.std)
        # Excluded (-1) satırları çıkar
        mask = split.test_y >= 0
        y_true = split.test_y[mask].astype(int)
        y_prob = probs[mask]
        y_pred = (y_prob >= 0.5).astype(int)
        metrics = {
            "horizon_min": h,
            "n_train": int((split.train_y >= 0).sum()),
            "n_test": int(mask.sum()),
            "n_pos_test": int((y_true == 1).sum()),
            "n_neg_test": int((y_true == 0).sum()),
            "auc": float(roc_auc_score(y_true, y_prob)) if len(np.unique(y_true)) > 1 else float("nan"),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "f1": float(f1_score(y_true, y_pred, zero_division=0)),
            "best_epoch": result.best_epoch,
            "n_params": result.n_params,
            "test_patients": ",".join(test_pids),
        }
        logger.info("SONUÇ [%dh]: AUC=%.4f Recall=%.4f Precision=%.4f F1=%.4f",
                    h, metrics["auc"], metrics["recall"],
                    metrics["precision"], metrics["f1"])

        # Kaydet
        metrics_path = args.out_dir / f"cnn_metrics_{h}min.json"
        metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        # Eğitim geçmişi
        pd.DataFrame(result.history).to_csv(
            args.out_dir / f"cnn_history_{h}min.csv", index=False)

        # Modeli kaydet
        import torch
        torch.save({
            "state_dict": result.model.state_dict(),
            "n_channels": split.train_X.shape[1],
            "n_samples": split.train_X.shape[2],
            "horizon_min": h,
            "channels": all_tensors[pids[0]].channels,
            "test_patients": test_pids,
        }, args.out_dir / f"cnn_model_{h}min.pt")

    logger.info("CNN CLI tamamlandı")
    return 0


if __name__ == "__main__":
    sys.exit(main())
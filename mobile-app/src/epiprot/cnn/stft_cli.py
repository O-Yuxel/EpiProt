"""STFT + CNN CLI — 5 horizon için ayrı model eğitir."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score, recall_score, precision_score
from torch.utils.data import DataLoader

from ..data.annotations import parse_chbmit_summary
from ..data.discovery import discover_files, patient_id_from_path
from ..labeling.config import LabelConfig
from ..labeling.horizons import Seizure
from ..logging_utils import setup_logging
from .stft_cnn import STFTCNN, count_parameters
from .stft_dataset import STFTDataset, build_stft_dataset_for_patient


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="epiprot.cnn.stft_cli")
    p.add_argument("--data-dir", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--patients", nargs="+", default=None)
    p.add_argument("--test-patients", nargs="+", default=None)
    p.add_argument("--horizons", type=int, nargs="+", default=[30, 45, 60, 75, 90])
    p.add_argument("--window-seconds", type=float, default=30.0)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--random-seed", type=int, default=42)
    return p


def _seizures_by_edf(summary_paths):
    idx = {}
    for sp in summary_paths:
        pr = parse_chbmit_summary(sp)
        if not pr.ok:
            continue
        for fa in pr.files:
            idx[fa.edf_filename] = [Seizure(start_s=s.start_s, end_s=s.end_s) for s in fa.seizures]
    return idx


def _train_one_horizon(
    X_train, y_train, X_test, y_test, horizon, cfg, logger,
):
    """Bir horizon için CNN eğit."""
    train_ds = STFTDataset(X_train, y_train)
    test_ds = STFTDataset(X_test, y_test)
    test_ds.mean = train_ds.mean
    test_ds.std = train_ds.std

    logger.info("Horizon %d | train=%d (pos=%d) test=%d (pos=%d)",
                horizon, len(train_ds), train_ds.class_counts()[1],
                len(test_ds), test_ds.class_counts()[1])

    if len(train_ds) == 0 or len(test_ds) == 0:
        return {"status": "insufficient_data", "horizon": horizon}

    train_loader = DataLoader(train_ds, batch_size=cfg["batch_size"], shuffle=True, num_workers=0)
    test_loader = DataLoader(test_ds, batch_size=cfg["batch_size"], shuffle=False, num_workers=0)

    n_channels = X_train.shape[1]
    freq_bins = X_train.shape[2]
    time_bins = X_train.shape[3]

    model = STFTCNN(n_channels, freq_bins, time_bins)
    n_params = count_parameters(model)
    logger.info("Model: %d parametre", n_params)

    # Sınıf ağırlığı
    n_pos = train_ds.class_counts()[1]
    n_neg = train_ds.class_counts()[0]
    pos_weight = torch.tensor(min(n_neg / max(n_pos, 1), 10.0), dtype=torch.float32)

    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["lr"], weight_decay=1e-4)

    best_auc = -1.0
    best_state = None
    best_epoch = -1
    patience = 5
    patience_counter = 0
    history = []

    for epoch in range(cfg["epochs"]):
        # Eğitim
        model.train()
        train_loss = 0.0
        n_train = 0
        for xb, yb in train_loader:
            optimizer.zero_grad()
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * xb.size(0)
            n_train += xb.size(0)
        train_loss /= max(n_train, 1)

        # Validation (test set üzerinde AUC — not: gerçekte ayrı validation gerekir)
        model.eval()
        probs, targets = [], []
        with torch.no_grad():
            for xb, yb in test_loader:
                logits = model(xb)
                probs.append(torch.sigmoid(logits).numpy())
                targets.append(yb.numpy())
        probs = np.concatenate(probs)
        targets = np.concatenate(targets)

        try:
            val_auc = roc_auc_score(targets, probs)
        except ValueError:
            val_auc = float("nan")

        history.append({"epoch": epoch + 1, "train_loss": train_loss, "val_auc": val_auc})
        logger.info("Epoch %02d | train_loss=%.4f val_auc=%.4f", epoch + 1, train_loss, val_auc)

        if np.isfinite(val_auc) and val_auc > best_auc:
            best_auc = val_auc
            best_epoch = epoch + 1
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= patience:
                logger.info("Erken durdurma (epoch %d)", epoch + 1)
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    # Final metrikler
    model.eval()
    probs, targets = [], []
    with torch.no_grad():
        for xb, yb in test_loader:
            logits = model(xb)
            probs.append(torch.sigmoid(logits).numpy())
            targets.append(yb.numpy())
    probs = np.concatenate(probs)
    targets = np.concatenate(targets)

    y_pred = (probs >= 0.6).astype(int)
        # Firing Power: 5 ardışık pencere 0.6 üzerindeyse alarm
    n_consecutive = 5
    fp_threshold = 0.6
    firing_power = np.zeros_like(probs, dtype=bool)
    for i in range(len(probs) - n_consecutive + 1):
        if all(probs[i:i + n_consecutive] >= fp_threshold):
            firing_power[i:i + n_consecutive] = True
    y_pred_fp = firing_power.astype(int)
    result = {
        "horizon": horizon,
        "status": "ok",
        "n_train": len(train_ds),
        "n_test": len(test_ds),
        "n_pos_test": int((targets == 1).sum()),
        "n_neg_test": int((targets == 0).sum()),
        "auc": float(roc_auc_score(targets, probs)) if len(np.unique(targets)) > 1 else float("nan"),
        "recall": float(recall_score(targets, y_pred, zero_division=0)),
        "precision": float(precision_score(targets, y_pred, zero_division=0)),
        "best_epoch": best_epoch,
        "n_params": n_params,
        "recall_fp": float(recall_score(targets, y_pred_fp, zero_division=0)),
        "precision_fp": float(precision_score(targets, y_pred_fp, zero_division=0))
    }
    logger.info("SONUÇ [%dh]: AUC=%.4f Recall=%.4f Precision=%.4f",
                horizon, result["auc"], result["recall"], result["precision"])
    logger.info("Firing Power: Recall=%.4f Precision=%.4f",
                result["recall_fp"], result["precision_fp"])

    # History kaydet
    pd.DataFrame(history).to_csv(cfg["out_dir"] / f"stft_history_{horizon}min.csv", index=False)

    # Model kaydet
    torch.save({
        "state_dict": model.state_dict(),
        "n_channels": n_channels,
        "freq_bins": freq_bins,
        "time_bins": time_bins,
        "horizon": horizon,
    }, cfg["out_dir"] / f"stft_model_{horizon}min.pt")

    return result


def main(argv=None):
    args = _build_argparser().parse_args(argv)
    logger = setup_logging(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("STFT CNN CLI başlıyor | data=%s | out=%s", args.data_dir, args.out_dir)

    torch.manual_seed(args.random_seed)
    np.random.seed(args.random_seed)

    # Keşif
    disc = discover_files(args.data_dir, "**/*.edf", "**/*-summary.txt", None)
    if args.patients:
        selected = set(args.patients)
        edfs = [p for p in disc.edf_files if any(part in selected for part in p.parts)]
    else:
        edfs = disc.edf_files

    by_patient = {}
    for p in edfs:
        pid = patient_id_from_path(p)
        if pid:
            by_patient.setdefault(pid, []).append(p)

    logger.info("Hastalar: %s", sorted(by_patient.keys()))

    # Test hastaları
    pids = sorted(by_patient.keys())
    if args.test_patients:
        test_pids = [p for p in args.test_patients if p in by_patient]
    else:
        test_pids = pids[-3:]
    train_pids = [p for p in pids if p not in test_pids]
    logger.info("Train: %s | Test: %s", train_pids, test_pids)

    # Anotasyonlar
    sz_by_edf = _seizures_by_edf(disc.summary_files)
    label_cfg = LabelConfig(horizons_minutes=[max(args.horizons)])  # tüm horizonlar için

    # Her hasta için STFT tensörlerini üret (horizon bağımsız)
    logger.info("STFT tensörleri üretiliyor...")
    patient_data = {}
    for pid in pids:
        try:
            # 30dk horizon için X ve y üret (diğer horizonlar da aynı X'i kullanır)
            label_cfg_h = LabelConfig(horizons_minutes=[30])
            X, y_30 = build_stft_dataset_for_patient(
                by_patient[pid], sz_by_edf, 30, label_cfg_h,
                window_seconds=args.window_seconds, logger=logger,
            )
            patient_data[pid] = (X, by_patient[pid])
            logger.info("[%s] X=%s", pid, X.shape)
        except Exception as e:
            logger.error("[%s] başarısız: %s", pid, e)

    if not patient_data:
        logger.error("Hiç hasta verisi yok")
        return 1

    # Her horizon için ayrı eğit
    all_results = []
    for h in args.horizons:
        logger.info("=== Horizon %d dk ===", h)
        label_cfg_h = LabelConfig(horizons_minutes=[h])

        # Train ve test X/y birleştir
        X_train_parts, y_train_parts = [], []
        X_test_parts, y_test_parts = [], []
        for pid, (X, edf_list) in patient_data.items():
            try:
                _, y = build_stft_dataset_for_patient(
                    edf_list, sz_by_edf, h, label_cfg_h,
                    window_seconds=args.window_seconds, logger=None,
                )
            except Exception:
                continue
            if pid in test_pids:
                X_test_parts.append(X); y_test_parts.append(y)
            else:
                X_train_parts.append(X); y_train_parts.append(y)

        if not X_train_parts or not X_test_parts:
            logger.warning("Horizon %d: train/test boş, atlanıyor", h)
            all_results.append({"horizon": h, "status": "insufficient_data"})
            continue

        X_train = np.concatenate(X_train_parts, axis=0)
        y_train = np.concatenate(y_train_parts, axis=0)
        X_test = np.concatenate(X_test_parts, axis=0)
        y_test = np.concatenate(y_test_parts, axis=0)

        cfg = {
            "batch_size": args.batch_size,
            "lr": args.lr,
            "epochs": args.epochs,
            "out_dir": args.out_dir,
        }
        result = _train_one_horizon(X_train, y_train, X_test, y_test, h, cfg, logger)
        all_results.append(result)

    pd.DataFrame(all_results).to_csv(args.out_dir / "stft_horizon_comparison.csv", index=False)
    logger.info("Tamamlandı")
    return 0


if __name__ == "__main__":
    sys.exit(main())
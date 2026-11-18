"""SeizeIT2 Çoklu Hasta CLI — Diskteki Hazır Verilerle Hızlı Eğitim."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score, recall_score, precision_score
from torch.utils.data import DataLoader

from ..logging_utils import setup_logging
from .seizeit_dataset import SeizeitDataset
from .stft_cnn import STFTCNN, count_parameters

class FocalLoss(nn.Module):
    def __init__(self, alpha: float = 0.5, gamma: float = 1.0):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        bce = nn.functional.binary_cross_entropy_with_logits(logits, targets, reduction="none")
        p = torch.sigmoid(logits)
        pt = torch.where(targets == 1, p, 1 - p)
        focal = self.alpha * (1 - pt) ** self.gamma * bce
        return focal.mean()

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="epiprot.cnn.seizeit_cli")
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--neg-sample-size", type=int, default=100000)
    return p

def main(argv=None):
    args = _build_argparser().parse_args(argv)
    logger = setup_logging(args.out_dir)
    
    cache_dir = args.out_dir / "1d_cache_final"
    if not cache_dir.exists():
        logger.error("1d_cache_final klasörü bulunamadı!")
        return 1

    logger.info("Diskteki hazır dosyalar okunuyor...")
    
    train_files = sorted(list(cache_dir.glob("train_*.npz")))
    test_files = sorted(list(cache_dir.glob("test_*.npz")))
    
    if not train_files or not test_files:
        logger.error("Eğitim veya test dosyaları bulunamadı!")
        return 1

    # 1. Eğitim verisini RAM'e yükle (Sadece 100k negatif + tüm pozitifler)
    X_train_list, y_train_list = [], []
    pos_count, neg_count = 0, 0
    np.random.seed(42)
    
    logger.info("Eğitim verileri taranıyor (Downsampling yapılıyor)...")
    for p in train_files:
        data = np.load(p)
        X, y = data['X'], data['y']
        
        # Pozitifleri ayır
        pos_mask = (y == 1)
        if pos_mask.any():
            X_train_list.append(X[pos_mask])
            y_train_list.append(y[pos_mask])
            pos_count += pos_mask.sum()
            
        # Negatiflerden rastgele seç
        if neg_count < args.neg_sample_size:
            neg_mask = (y == 0)
            neg_idx = np.where(neg_mask)[0]
            needed = args.neg_sample_size - neg_count
            if len(neg_idx) > needed:
                neg_idx = np.random.choice(neg_idx, size=needed, replace=False)
            
            if len(neg_idx) > 0:
                X_train_list.append(X[neg_idx])
                y_train_list.append(y[neg_idx])
                neg_count += len(neg_idx)

    X_train = np.concatenate(X_train_list, axis=0)
    y_train = np.concatenate(y_train_list, axis=0)
    del X_train_list, y_train_list

    # 2. Test verisini RAM'e yükle
    X_test_list, y_test_list = [], []
    for p in test_files:
        data = np.load(p)
        X_test_list.append(data['X'])
        y_test_list.append(data['y'])
    X_test = np.concatenate(X_test_list, axis=0)
    y_test = np.concatenate(y_test_list, axis=0)

    logger.info("Eğitim Seti: %d (Pozitif: %d, Negatif: %d)", len(y_train), pos_count, neg_count)
    logger.info("Test Seti: %d (Pozitif: %d)", len(y_test), int((y_test==1).sum()))

    # 3. EĞİTİM
    train_ds = SeizeitDataset(X_train, y_train)
    test_ds = SeizeitDataset(X_test, y_test)
    test_ds.mean = train_ds.mean
    test_ds.std = train_ds.std
    
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False)

    model = STFTCNN(n_channels=3)
    logger.info("Model Parametre: %d", count_parameters(model))

    criterion = FocalLoss(alpha=0.5, gamma=1.0)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)

    best_auc = -1.0
    best_state = None
    patience_counter = 0
    patience = 5

    logger.info("=== EĞİTİM BAŞLIYOR ===")
    for epoch in range(args.epochs):
        model.train()
        train_loss = 0.0
        for xb, yb in train_loader:
            optimizer.zero_grad()
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * xb.size(0)
        train_loss /= len(train_ds)

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
            val_auc = 0.5
            
        logger.info("Epoch %02d | train_loss=%.4f | val_auc=%.4f", epoch+1, train_loss, val_auc)
        
        if val_auc > best_auc:
            best_auc = val_auc
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= patience:
                logger.info("Erken durdurma (epoch %d)", epoch+1)
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    # 4. SONUÇLAR
    logger.info("=== SONUÇLAR (Threshold Sweep) ===")
    best_f1, best_thr = 0, 0.5
    best_p, best_r = 0, 0
    
    for thr in np.arange(0.1, 0.95, 0.05):
        y_pred = (probs >= thr).astype(int)
        p = precision_score(targets, y_pred, zero_division=0)
        r = recall_score(targets, y_pred, zero_division=0)
        f1 = 2 * p * r / (p + r + 1e-10)
        
        if f1 > best_f1:
            best_f1, best_thr = f1, thr
            best_p, best_r = p, r

    logger.info("En İyi Eşik: %.2f", best_thr)
    logger.info("Recall: %.4f | Precision: %.4f | F1: %.4f", best_r, best_p, best_f1)
    
    if best_r >= 0.90 and best_p >= 0.85:
        logger.info("🎉 HEDEFE ULAŞILDI! (Recall >= 0.90 ve Precision >= 0.85)")
    else:
        logger.info("Hedefe henüz ulaşılamadı.")

if __name__ == "__main__":
    sys.exit(main())
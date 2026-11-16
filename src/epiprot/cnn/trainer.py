"""CNN eğitim döngüsü."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from .dataset import TrainTestSplit, WindowDataset
from .model import SeizureCNN, count_parameters


@dataclass
class TrainingConfig:
    epochs: int = 30
    batch_size: int = 64
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    early_stop_patience: int = 5
    pos_weight_cap: float = 10.0  # sınıf dengesizliği ağırlığı üst sınırı
    device: str = "cpu"
    random_seed: int = 42


@dataclass
class TrainingResult:
    model: SeizureCNN
    history: list[dict]
    best_epoch: int
    best_val_auc: float
    n_params: int
    device: str
    # YENİ:
    mean: np.ndarray = None
    std: np.ndarray = None


def _compute_pos_weight(y: np.ndarray, cap: float) -> torch.Tensor:
    """Pozitif sınıf ağırlığı (negatif/pozitif oranı, üst sınırlı)."""
    n_pos = (y == 1).sum()
    n_neg = (y == 0).sum()
    if n_pos == 0:
        return torch.tensor(1.0)
    w = float(n_neg) / float(n_pos)
    w = min(w, cap)
    return torch.tensor(w, dtype=torch.float32)


def train_cnn(
    split: TrainTestSplit,
    horizon_min: int,
    cfg: TrainingConfig,
    logger=None,
) -> TrainingResult:
    """Eğit, her epoch validation AUC hesapla, erken durdurma yap."""
    torch.manual_seed(cfg.random_seed)
    np.random.seed(cfg.random_seed)

    # Aynı normalizasyon parametrelerini test'e uygula (test sızıntısı yok)
    # RAM dostu: liste ise önce concat et
    if isinstance(split.train_X, list):
        train_X = np.concatenate(split.train_X, axis=0)
        train_y = np.concatenate(split.train_y, axis=0)
        test_X = np.concatenate(split.test_X, axis=0)
        test_y = np.concatenate(split.test_y, axis=0)
    else:
        train_X, train_y = split.train_X, split.train_y
        test_X, test_y = split.test_X, split.test_y

    train_ds = WindowDataset(train_X, train_y)
    test_ds = WindowDataset(test_X, test_y)

    train_loader = DataLoader(train_ds, batch_size=cfg.batch_size,
                              shuffle=True, num_workers=0)
    test_loader = DataLoader(test_ds, batch_size=cfg.batch_size,
                             shuffle=False, num_workers=0)

    n_channels = train_X.shape[1]
    n_samples = train_X.shape[2]
    model = SeizureCNN(n_channels, n_samples).to(cfg.device)
    n_params = count_parameters(model)

    # Sınıf ağırlığı
    pos_weight = _compute_pos_weight(train_ds.y, cfg.pos_weight_cap).to(cfg.device)
    if logger:
        logger.info("Eğitim: train=%d (pos=%d), test=%d (pos=%d), pos_weight=%.2f",
                    len(train_ds), train_ds.class_counts()[1],
                    len(test_ds), test_ds.class_counts()[1],
                    float(pos_weight))

    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.learning_rate,
                                  weight_decay=cfg.weight_decay)

    history = []
    best_auc = -1.0
    best_state = None
    best_epoch = -1
    patience_counter = 0

    from sklearn.metrics import roc_auc_score

    for epoch in range(cfg.epochs):
        # --- Eğitim ---
        model.train()
        train_loss = 0.0
        n_train = 0
        for xb, yb in train_loader:
            xb, yb = xb.to(cfg.device), yb.to(cfg.device)
            optimizer.zero_grad()
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            train_loss += loss.item() * xb.size(0)
            n_train += xb.size(0)
        train_loss /= max(n_train, 1)

        # --- Validation ---
        model.eval()
        val_probs, val_targets = [], []
        val_loss = 0.0
        n_val = 0
        with torch.no_grad():
            for xb, yb in test_loader:
                xb, yb = xb.to(cfg.device), yb.to(cfg.device)
                logits = model(xb)
                loss = criterion(logits, yb)
                val_loss += loss.item() * xb.size(0)
                n_val += xb.size(0)
                val_probs.append(torch.sigmoid(logits).cpu().numpy())
                val_targets.append(yb.cpu().numpy())
        val_loss /= max(n_val, 1)
        val_probs = np.concatenate(val_probs)
        val_targets = np.concatenate(val_targets)

        try:
            val_auc = float(roc_auc_score(val_targets, val_probs))
        except ValueError:
            val_auc = float("nan")

        history.append({
            "epoch": epoch + 1,
            "train_loss": train_loss,
            "val_loss": val_loss,
            "val_auc": val_auc,
        })
        if logger:
            logger.info("Epoch %02d/%d | train_loss=%.4f val_loss=%.4f val_auc=%.4f",
                        epoch + 1, cfg.epochs, train_loss, val_loss, val_auc)

        # Erken durdurma (AUC'ye göre)
        if np.isfinite(val_auc) and val_auc > best_auc:
            best_auc = val_auc
            best_epoch = epoch + 1
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= cfg.early_stop_patience:
                if logger:
                    logger.info("Erken durdurma: %d epoch iyileşme yok", patience_counter)
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    return TrainingResult(
        model=model,
        history=history,
        best_epoch=best_epoch,
        best_val_auc=best_auc,
        n_params=n_params,
        device=cfg.device,
        mean=train_ds.mean,     # YENİ
        std=train_ds.std,       # YENİ
    )


def predict(model: SeizureCNN, X: np.ndarray, batch_size: int = 128,
            device: str = "cpu",
            mean: float | np.ndarray = 0.0,
            std: float | np.ndarray = 1.0) -> np.ndarray:
    """Normalize edilmiş tahmin. mean/std eğitimden gelmeli."""
    model.eval()
    probs = []
    X_norm = (X - mean) / std
    with torch.no_grad():
        for i in range(0, len(X_norm), batch_size):
            xb = torch.from_numpy(X_norm[i:i + batch_size].astype(np.float32)).to(device)
            logits = model(xb)
            probs.append(torch.sigmoid(logits).cpu().numpy())
    return np.concatenate(probs)
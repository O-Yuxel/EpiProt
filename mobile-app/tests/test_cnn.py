"""CNN modülü için sentetik testler."""
from __future__ import annotations

import numpy as np
import pytest
import torch

from epiprot.cnn.dataset import WindowDataset, build_split
from epiprot.cnn.model import SeizureCNN, count_parameters
from epiprot.cnn.tensor_builder import PatientTensors


def _make_fake_patient(pid: str, n_windows: int = 50, n_channels: int = 4,
                       n_samples: int = 100, seed: int = 0,
                       n_pos: int = 5) -> PatientTensors:
    """Sentetik hasta tensörü oluştur."""
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n_windows, n_channels, n_samples)).astype(np.float32)
    y_30 = np.zeros(n_windows, dtype=np.int8)
    y_30[-n_pos:] = 1
    return PatientTensors(
        patient_id=pid,
        X=X,
        y_by_horizon={30: y_30},
        window_start_s=np.arange(n_windows, dtype=np.float32) * 10.0,
        edf_paths=np.array([f"{pid}_01.edf"] * n_windows, dtype=object),
        channels=[f"CH{i}" for i in range(n_channels)],
        sfreq=128.0,
        n_samples=n_samples,
        window_seconds=10.0,
    )


# ---------- Model testleri ----------

def test_model_forward_shape():
    model = SeizureCNN(n_channels=4, n_samples=100)
    x = torch.randn(8, 4, 100)
    out = model(x)
    assert out.shape == (8,), f"Beklenen (8,), alındı {out.shape}"


def test_model_param_count_reasonable():
    model = SeizureCNN(n_channels=22, n_samples=2560)
    n_params = count_parameters(model)
    # 50K-200K aralığında olmalı (küçük-orta model)
    assert 50_000 < n_params < 300_000, f"Parametre sayısı: {n_params}"


def test_model_is_differentiable():
    model = SeizureCNN(n_channels=2, n_samples=50)
    x = torch.randn(4, 2, 50, requires_grad=False)
    y = torch.tensor([0.0, 1.0, 0.0, 1.0])
    out = model(x)
    loss = torch.nn.functional.binary_cross_entropy_with_logits(out, y)
    loss.backward()
    # En az bir parametrenin gradyanı olmalı
    grads = [p.grad for p in model.parameters() if p.grad is not None]
    assert len(grads) > 0


def test_model_handles_variable_batch():
    model = SeizureCNN(n_channels=4, n_samples=100)
    for bs in (1, 5, 16):
        out = model(torch.randn(bs, 4, 100))
        assert out.shape == (bs,)


def test_model_handles_different_input_lengths():
    """AdaptiveAvgPool sayesinde farklı T'ler çalışmalı."""
    model = SeizureCNN(n_channels=4, n_samples=100)
    for T in (50, 100, 500, 1280):
        out = model(torch.randn(2, 4, T))
        assert out.shape == (2,)


# ---------- Dataset testleri ----------

def test_dataset_filters_excluded():
    X = np.random.randn(10, 3, 50).astype(np.float32)
    y = np.array([0, 1, -1, 0, 1, 0, -1, 1, 0, 1], dtype=np.int8)
    ds = WindowDataset(X, y)
    # -1'ler çıkarıldı: 10 - 2 = 8 örnek
    assert len(ds) == 8
    assert ds.class_counts() == {0: 4, 1: 4}


def test_dataset_normalization_computed_from_data():
    X = np.random.randn(20, 3, 50).astype(np.float32) * 5.0 + 10.0
    y = np.array([0, 1] * 10, dtype=np.int8)
    ds = WindowDataset(X, y, normalize=True)
    # Mean ve std hesaplanmış olmalı
    assert ds.mean.shape == (1, 3, 1)
    assert ds.std.shape == (1, 3, 1)
    # Ortalama ~10 civarında olmalı
    assert 5.0 < float(ds.mean.mean()) < 15.0


def test_dataset_getitem_returns_tensor():
    X = np.random.randn(10, 3, 50).astype(np.float32)
    y = np.array([0, 1] * 5, dtype=np.int8)
    ds = WindowDataset(X, y)
    x, label = ds[0]
    assert isinstance(x, torch.Tensor)
    assert isinstance(label, torch.Tensor)
    assert x.shape == (3, 50)
    assert label.dim() == 0


# ---------- Split testleri ----------

def test_build_split_assigns_patients_correctly():
    t1 = _make_fake_patient("chb01", n_windows=30, seed=1)
    t2 = _make_fake_patient("chb02", n_windows=40, seed=2)
    t3 = _make_fake_patient("chb03", n_windows=50, seed=3)

    split = build_split(
        {"chb01": t1, "chb02": t2, "chb03": t3},
        horizon_min=30,
        test_patient_ids=["chb03"],
    )
    assert split.train_patients == ["chb01", "chb02"]
    assert split.test_patients == ["chb03"]
    # build_split keeps one array per patient (no concatenation, to save RAM)
    assert sum(x.shape[0] for x in split.train_X) == 30 + 40
    assert sum(x.shape[0] for x in split.test_X) == 50


def test_build_split_empty_raises():
    t1 = _make_fake_patient("chb01")
    with pytest.raises(ValueError):
        build_split({"chb01": t1}, horizon_min=30,
                    test_patient_ids=["chb01"])  # train boş


# ---------- Trainer (hızlı, sentetik) ----------

def test_training_reduces_loss_on_separable_data():
    """Çok küçük sentetik veride eğitim loss'u düşürmeli."""
    # 4 kanal, 100 örnek, ilk yarısı 0'a, ikinci yarısı 1'e yakın
    n = 200
    X = np.zeros((n, 4, 100), dtype=np.float32)
    rng = np.random.default_rng(0)
    X[:n // 2] = rng.standard_normal((n // 2, 4, 100)) * 0.5  # düşük genlik
    X[n // 2:] = rng.standard_normal((n // 2, 4, 100)) * 3.0  # yüksek genlik
    y = np.array([0] * (n // 2) + [1] * (n // 2), dtype=np.int8)

    from epiprot.cnn.dataset import TrainTestSplit
    split = TrainTestSplit(
        train_X=X[:150], train_y=y[:150],
        test_X=X[150:], test_y=y[150:],
        train_patients=["p1"], test_patients=["p2"],
    )

    from epiprot.cnn.trainer import TrainingConfig, train_cnn
    cfg = TrainingConfig(epochs=10, batch_size=32, learning_rate=1e-2,
                        early_stop_patience=20, pos_weight_cap=1.0)
    result = train_cnn(split, horizon_min=30, cfg=cfg)

    # İlk epoch loss > son epoch loss olmalı
    assert result.history[0]["train_loss"] > result.history[-1]["train_loss"], \
        f"Loss düşmedi: {[h['train_loss'] for h in result.history]}"


def test_predict_returns_probabilities_in_range():
    from epiprot.cnn.dataset import TrainTestSplit
    n = 100
    X = np.random.randn(n, 4, 100).astype(np.float32)
    y = np.array([0, 1] * (n // 2), dtype=np.int8)
    split = TrainTestSplit(train_X=X[:80], train_y=y[:80],
                            test_X=X[80:], test_y=y[80:],
                            train_patients=["p1"], test_patients=["p2"])

    from epiprot.cnn.trainer import TrainingConfig, predict, train_cnn
    cfg = TrainingConfig(epochs=2, batch_size=16, pos_weight_cap=1.0)
    result = train_cnn(split, horizon_min=30, cfg=cfg)
    probs = predict(result.model, split.test_X,
                    mean=result.mean, std=result.std)
    assert probs.shape == (20,)
    assert (probs >= 0).all() and (probs <= 1).all()
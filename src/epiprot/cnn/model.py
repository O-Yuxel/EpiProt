"""1D-CNN mimarisi — ham EEG için."""
from __future__ import annotations

import torch
import torch.nn as nn


class SeizureCNN(nn.Module):
    """Küçük-orta 1D-CNN. Input: (batch, n_channels, n_samples).

    ~100K parametre. CPU'da eğitilebilir.
    """
    def __init__(self, n_channels: int, n_samples: int, dropout: float = 0.5):
        super().__init__()
        self.n_channels = n_channels
        self.n_samples = n_samples

        self.features = nn.Sequential(
            # Conv block 1
            nn.Conv1d(n_channels, 32, kernel_size=15, padding=7),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.MaxPool1d(2),

            # Conv block 2
            nn.Conv1d(32, 64, kernel_size=7, padding=3),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(2),

            # Conv block 3
            nn.Conv1d(64, 128, kernel_size=5, padding=2),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),  # (batch, 128, 1)
        )

        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(dropout),
            nn.Linear(128, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (batch, n_channels, n_samples). Çıkış: (batch,) logits."""
        feats = self.features(x)              # (batch, 128, 1)
        logits = self.classifier(feats)       # (batch, 1)
        return logits.squeeze(-1)              # (batch,)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
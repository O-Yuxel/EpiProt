from __future__ import annotations

import torch
import torch.nn as nn

class STFTCNN(nn.Module):
    def __init__(self, n_channels: int = 3, freq_bins: int = 40, time_bins: int = 59, 
                 d_model: int = 64, nhead: int = 4, num_layers: int = 2, dropout: float = 0.3):
        super().__init__()
        
        self.cnn = nn.Sequential(
            nn.Conv2d(n_channels, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
            
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
            
            nn.Conv2d(64, d_model, kernel_size=3, padding=1),
            nn.BatchNorm2d(d_model), nn.ReLU()
        )
        
        self.freq_out = freq_bins // 4
        self.time_out = time_bins // 4
        
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, 
            nhead=nhead, 
            dim_feedforward=d_model * 2, 
            dropout=dropout, 
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(d_model, 1)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.cnn(x)
        
        B, C, F, T = x.shape
        x = x.view(B, C, -1).permute(0, 2, 1) 
        
        x = self.transformer(x)
        
        x = x.mean(dim=1) 
        
        return self.classifier(x).squeeze(-1)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
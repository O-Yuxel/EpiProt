"""Sentetik CHB-MIT benzeri veri üretici.

Testlerde kullanılan yapı:
    chbmit/
        chbXX/
            chbXX-summary.txt
            chbXX_01.edf
            chbXX_02.edf
"""
from __future__ import annotations

from pathlib import Path

import mne
import numpy as np


def _make_edf(path: Path, duration_s: float, sfreq: float, eeg_channels: list[str],
              extra_channels: dict[str, str] | None = None, seed: int = 0) -> None:
    """Küçük, geçerli bir EDF yaz."""
    rng = np.random.default_rng(seed)
    n = int(duration_s * sfreq)
    ch_names = list(eeg_channels) + list((extra_channels or {}).keys())
    ch_types = ["eeg"] * len(eeg_channels) + list((extra_channels or {}).values())

    data = rng.standard_normal((len(ch_names), n)) * 20e-6  # ~20 µV
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)

    # MNE, EDF yazımı için ölçeklenebilir kanal tiplerine ihtiyaç duyar;
    # tüm kanalları 'eeg' yapıp yaz, isimlerle sınıflandırma test edilir.
    info.set_channel_types({c: "eeg" for c in ch_names})
    raw = mne.io.RawArray(data, info, verbose="ERROR")
    path.parent.mkdir(parents=True, exist_ok=True)
    mne.export.export_raw(str(path), raw, fmt="edf", overwrite=True, verbose="ERROR")


def build_synthetic_chbmit(root: Path,
                           n_patients: int = 1,
                           files_per_patient: int = 2,
                           duration_s: float = 60.0,
                           sfreq: float = 128.0) -> Path:
    """Sentetik CHB-MIT yapısını oluştur ve kök klasörü döndür."""
    root = Path(root)
    eeg_channels = ["FP1-F7", "F7-T7", "T7-P7", "P7-O1", "FP2-F8", "F8-T8"]
    extra = {"ECG": "ecg", "EOG": "eog"}  # MNE yazımı için hepsi eeg yapılır

    for p in range(1, n_patients + 1):
        pid = f"chb{p:02d}"
        pdir = root / pid
        pdir.mkdir(parents=True, exist_ok=True)

        summary_lines = []
        for f in range(1, files_per_patient + 1):
            fname = f"{pid}_{f:02d}.edf"
            _make_edf(pdir / fname, duration_s=duration_s, sfreq=sfreq,
                      eeg_channels=eeg_channels, extra_channels=extra, seed=p * 10 + f)
            summary_lines += [
                f"File Name: {fname}",
                "File Start Time: 00:00:00",
                f"File End Time: 00:01:00",
            ]
            # İlk dosyada nöbet var, ikincide yok.
            if f == 1:
                summary_lines += [
                    "Number of Seizures in File: 1",
                    "Seizure Start Time: 20 seconds",
                    "Seizure End Time: 35 seconds",
                    "",
                ]
            else:
                summary_lines += ["Number of Seizures in File: 0", ""]

        (pdir / f"{pid}-summary.txt").write_text("\n".join(summary_lines), encoding="utf-8")

    return root
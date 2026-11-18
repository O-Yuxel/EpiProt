"""Yapılandırılmış log — konsol + dosya."""
from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(out_dir: Path, name: str = "epiprot", level: int = logging.INFO) -> logging.Logger:
    out_dir = Path(out_dir)
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "processing.log"

    logger = logging.getLogger(name)
    logger.setLevel(level)
    # Tekrarlı handler'ları temizle (yeniden import / test durumları için).
    for h in list(logger.handlers):
        logger.removeHandler(h)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    logger.propagate = False
    return logger
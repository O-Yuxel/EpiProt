"""Pytest ortak fixture'ları ve sys.path düzeltmesi."""
from __future__ import annotations

import sys
from pathlib import Path

# src/ altındaki paketi import edilebilir yap (pip install -e yapılmamışsa diye).
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
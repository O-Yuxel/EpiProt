"""Model artefaktı kaydetme ve yükleme."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import joblib
import sklearn


@dataclass
class ModelArtifact:
    """Model + tüm meta veri."""
    model: Any  # sklearn Pipeline
    horizon_min: int
    feature_columns: List[str]
    feature_groups: str
    model_name: str
    window_seconds: float
    prediction_gap_minutes: float
    negative_exclusion_hours: float
    training_edfs: List[str]
    random_seed: int
    library_versions: Dict[str, str] = field(default_factory=dict)
    trained_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict:
        d = asdict(self)
        d.pop("model")
        d["feature_columns"] = list(self.feature_columns)
        return d


def _library_versions() -> Dict[str, str]:
    import numpy, pandas, scipy  # noqa: E401
    return {
        "python": sys.version.split()[0],
        "sklearn": sklearn.__version__,
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "scipy": scipy.__version__,
    }


def save_artifact(artifact: ModelArtifact, out_dir: Path) -> Path:
    """Model + JSON meta dosyasını yaz; model dosya yolunu döndür."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not artifact.library_versions:
        artifact.library_versions = _library_versions()

    model_path = out_dir / f"model_{artifact.horizon_min}min.joblib"
    meta_path = out_dir / f"model_{artifact.horizon_min}min.json"

    joblib.dump(
        {
            "model": artifact.model,
            "feature_columns": artifact.feature_columns,
        },
        model_path,
    )
    meta_path.write_text(
        json.dumps(artifact.to_metadata(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return model_path


def load_artifact(model_path: Path) -> tuple[Any, List[str], dict]:
    """model_path'ten (model, feature_columns, metadata_dict) yükle."""
    model_path = Path(model_path)
    blob = joblib.load(model_path)
    meta_path = model_path.with_suffix(".json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = {}
    return blob["model"], blob["feature_columns"], meta
"""save.py için birim testleri."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from epiprot.modeling.save import ModelArtifact, load_artifact, save_artifact


def _make_fake_model() -> LogisticRegression:
    model = LogisticRegression()
    model.fit(np.array([[0.0], [1.0], [2.0], [3.0]]), [0, 0, 1, 1])
    return model


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    model = _make_fake_model()
    art = ModelArtifact(
        model=model,
        horizon_min=30,
        feature_columns=["f1", "f2"],
        feature_groups="time+freq",
        model_name="logistic",
        window_seconds=10.0,
        prediction_gap_minutes=5.0,
        negative_exclusion_hours=4.0,
        training_edfs=["/a/chb01_01.edf"],
        random_seed=42,
    )
    p = save_artifact(art, tmp_path)
    assert p.exists()
    assert (tmp_path / "model_30min.json").exists()

    loaded_model, feat_cols, meta = load_artifact(p)
    assert feat_cols == ["f1", "f2"]
    assert meta["horizon_min"] == 30
    assert meta["model_name"] == "logistic"

    # Aynı girdi -> aynı tahmin
    X = np.array([[0.5], [2.5]])
    assert np.array_equal(model.predict(X), loaded_model.predict(X))


def test_save_includes_library_versions(tmp_path: Path) -> None:
    art = ModelArtifact(
        model=_make_fake_model(),
        horizon_min=30,
        feature_columns=["f1"],
        feature_groups="time",
        model_name="logistic",
        window_seconds=10.0,
        prediction_gap_minutes=5.0,
        negative_exclusion_hours=4.0,
        training_edfs=[],
        random_seed=42,
    )
    p = save_artifact(art, tmp_path)
    _, _, meta = load_artifact(p)
    assert "sklearn" in meta["library_versions"]
    assert "python" in meta["library_versions"]
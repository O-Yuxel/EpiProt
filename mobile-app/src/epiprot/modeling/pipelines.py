"""sklearn Pipeline fabrikaları."""
from __future__ import annotations

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.feature_selection import SelectKBest, VarianceThreshold, f_classif
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import ModelConfig


def build_pipeline(cfg: ModelConfig, n_features_hint: int | None = None) -> Pipeline:
    """ModelConfig'e göre bir sklearn Pipeline oluştur.

    Ön işleme sırası: impute -> scale -> (opsiyonel) feature selection -> model.
    Tüm adımlar Pipeline içinde; `.fit(train)` ile yalnızca eğitim verisinden
    öğrenilir. Test verisi dönüşümü `.transform`/`.predict` ile yapılır.
    """
    steps: list[tuple[str, object]] = [
        ("imputer", SimpleImputer(strategy=cfg.impute_strategy)),
    ]

    if cfg.scale_features:
        steps.append(("scaler", StandardScaler()))

    if cfg.feature_selection == "variance":
        steps.append(("selector", VarianceThreshold(threshold=0.0)))
    elif cfg.feature_selection == "univariate":
        k = cfg.feature_selection_k
        if n_features_hint is not None:
            k = min(k, n_features_hint)
        steps.append(("selector", SelectKBest(score_func=f_classif, k=k)))

    if cfg.model_name == "logistic":
        model = LogisticRegression(
            max_iter=2000,
            class_weight="balanced",  # sınıf dengesizliği için
            random_state=cfg.random_seed,
        )
        # Hiperparametre grid'i RandomizedSearchCV'de ayrıca verilir
    elif cfg.model_name == "random_forest":
        model = RandomForestClassifier(
            n_estimators=200,
            class_weight="balanced",
            random_state=cfg.random_seed,
            n_jobs=-1,
        )
    elif cfg.model_name == "hist_gb":
        model = HistGradientBoostingClassifier(
            random_state=cfg.random_seed,
            class_weight="balanced",
        )
    else:
        raise ValueError(f"Bilinmeyen model: {cfg.model_name}")

    steps.append(("model", model))
    return Pipeline(steps)


def param_grid(model_name: str) -> dict:
    """RandomizedSearchCV için model parametre aralığı."""
    if model_name == "logistic":
        return {
            "model__C": [0.01, 0.1, 1.0, 10.0, 100.0],
        }
    if model_name == "random_forest":
        return {
            "model__n_estimators": [100, 200, 400],
            "model__max_depth": [None, 5, 10, 20],
            "model__min_samples_leaf": [1, 5, 20],
        }
    if model_name == "hist_gb":
        return {
            "model__learning_rate": [0.01, 0.05, 0.1],
            "model__max_depth": [None, 3, 6],
            "model__max_iter": [100, 200, 400],
        }
    raise ValueError(f"Bilinmeyen model: {model_name}")
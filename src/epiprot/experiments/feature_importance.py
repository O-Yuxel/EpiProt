"""Eğitilen modelden özellik önemlerini çıkar ve raporla."""
from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path


def extract_feature_importance(model, feature_columns: list[str]) -> pd.DataFrame:
    """Pipeline'dan özellik önemlerini çıkar.
    
    Lojistik regresyon -> |coef_| (mutlak değer, yön kaybı olmadan önem)
    Random forest       -> feature_importances_ (Gini importance)
    HistGradientBoosting -> feature_importances_ (varsa)
    """
    # Pipeline içindeki son adım modeldir
    final_estimator = model.steps[-1][1] if hasattr(model, "steps") else model
    
    if hasattr(final_estimator, "coef_"):
        # LogisticRegression: coef_ shape = (1, n_features)
        coef = np.abs(final_estimator.coef_).ravel()
        importance = coef
        method = "abs_coef"
    elif hasattr(final_estimator, "feature_importances_"):
        importance = final_estimator.feature_importances_
        method = "gini"
    else:
        return pd.DataFrame()

    # Özellik seçimi varsa, orijinal indeksleri al
    # (şu an feature_selection=None, ama ileride lazım olabilir)
    if len(importance) != len(feature_columns):
        # SelectKBest gibi bir adım varsa, seçilen özellikleri al
        selector = None
        for name, step in model.steps:
            if "select" in name.lower() or "selector" in name.lower():
                selector = step
                break
        if selector is not None and hasattr(selector, "get_support"):
            support = selector.get_support()
            original_cols = [c for c, keep in zip(feature_columns, support) if keep]
        else:
            original_cols = feature_columns[:len(importance)]
    else:
        original_cols = feature_columns

    df = pd.DataFrame({
        "feature": original_cols,
        "importance": importance,
        "method": method,
    }).sort_values("importance", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    df["cumulative_importance"] = df["importance"].cumsum() / df["importance"].sum()
    return df


def summarize_by_family(importance_df: pd.DataFrame) -> pd.DataFrame:
    """Özellikleri ailelere göre özetle: time_*, freq_*, complex_*."""
    df = importance_df.copy()
    df["family"] = df["feature"].apply(
        lambda f: "time" if f.startswith("time_") else
                  "freq" if f.startswith("freq_") else
                  "complex" if f.startswith("complex_") else "other"
    )
    return (
        df.groupby("family")
        .agg(n_features=("feature", "count"),
             total_importance=("importance", "sum"),
             mean_importance=("importance", "mean"),
             top_feature=("feature", lambda s: s.iloc[0]))
        .sort_values("total_importance", ascending=False)
        .reset_index()
    )


def top_k_subset(importance_df: pd.DataFrame, k: int) -> list[str]:
    """En önemli k özelliğin adlarını döndür."""
    return importance_df.head(k)["feature"].tolist()

def save_top_k_features(importance_df: pd.DataFrame, out_path: Path, k: int = 10) -> list[str]:
    """En önemli k özelliği ayrı bir dosyaya kaydet ve listesini döndür."""
    top = top_k_subset(importance_df, k)
    out_path = Path(out_path)
    out_path.write_text("\n".join(top), encoding="utf-8")
    return top
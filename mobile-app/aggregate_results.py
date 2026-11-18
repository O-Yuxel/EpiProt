"""22 hasta sonuçlarını birleştir, global feature importance üret."""
from pathlib import Path
import pandas as pd
import numpy as np

base = Path('/app/per_patient')
all_imp = []
all_metrics = []

for pdir in sorted(base.iterdir()):
    if not pdir.is_dir():
        continue
    pid = pdir.name
    # Metrikler
    csv = pdir / 'horizon_comparison.csv'
    if csv.exists():
        df = pd.read_csv(csv)
        df['patient_id'] = pid
        all_metrics.append(df)
    # Feature importance
    imp_files = list(pdir.glob('feature_importance_*.csv'))
    if imp_files:
        imp = pd.read_csv(imp_files[0])
        imp['patient_id'] = pid
        all_imp.append(imp)

# ===== 1. Metrikler =====
if all_metrics:
    metrics_all = pd.concat(all_metrics, ignore_index=True)
    metrics_all.to_csv(base / 'all_patients_metrics.csv', index=False)
    print(f"\n=== PER-PATIENT AUC (n={len(metrics_all)}) ===")
    for _, r in metrics_all.iterrows():
        auc = r.get('roc_auc', float('nan'))
        f1 = r.get('f1', float('nan'))
        print(f"{r['patient_id']}: AUC={auc:.3f} | F1={f1:.3f}")
    print(f"\nORTALAMA AUC: {metrics_all['roc_auc'].mean():.3f}")
    print(f"MEDYAN AUC:  {metrics_all['roc_auc'].median():.3f}")
    print(f"STD AUC:     {metrics_all['roc_auc'].std():.3f}")
    print(f"ORTALAMA F1: {metrics_all['f1'].mean():.3f}")

# ===== 2. Global feature importance =====
if all_imp:
    imp_all = pd.concat(all_imp, ignore_index=True)
    # Her hasta için normalize et (toplam=1)
    imp_all['norm_imp'] = imp_all.groupby('patient_id')['importance'].transform(
        lambda x: x / x.sum() if x.sum() > 0 else x
    )
    # 22 hasta ortalaması + standart sapma
    agg = (
        imp_all.groupby('feature')['norm_imp']
        .agg(['mean', 'std', 'count'])
        .reset_index()
        .sort_values('mean', ascending=False)
        .reset_index(drop=True)
    )
    agg['rank'] = agg.index + 1
    agg['cumulative'] = agg['mean'].cumsum() / agg['mean'].sum()
    agg.to_csv(base / 'global_feature_importance.csv', index=False)

    print("\n=== GLOBAL FEATURE IMPORTANCE (22 hasta ortalaması) ===")
    print(agg.head(20).to_string(index=False))

    n80 = int((agg['cumulative'] < 0.8).sum()) + 1
    print(f"\n%80 kümülatif önem için gereken özellik sayısı: {n80}")

    # İlk 10'un listesi (yeni top-10)
    new_top10 = agg.head(10)['feature'].tolist()
    print("\n=== YENİ TOP 10 ÖZELLİK ===")
    for i, f in enumerate(new_top10, 1):
        row = agg[agg['feature'] == f].iloc[0]
        print(f"{i:2d}. {f:40s} mean={row['mean']:.4f}  std={row['std']:.4f}")

    # Dosyaya yaz
    with open(base / 'new_top10_features.txt', 'w') as fp:
        fp.write('\n'.join(new_top10))
    print(f"\nYeni top-10 {base / 'new_top10_features.txt'} dosyasına kaydedildi.")
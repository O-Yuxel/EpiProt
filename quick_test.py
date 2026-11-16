import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, recall_score, precision_score

# Veriyi yükle
df = pd.read_csv('/app/epiprot_results/feature_table_labeled.csv')
label_col = 'label_30min'
df = df[df[label_col].notna()].copy()

# Her EDF içinde zaman bazlı split (train.py'deki mantıkla aynı)
train_parts, test_parts = [], []
for edf, g in df.groupby('edf_path'):
    g = g.sort_values('window_start_s')
    unique_times = np.sort(g['window_start_s'].unique())
    if len(unique_times) < 2:
        train_parts.append(g)
        continue
    cutoff_idx = max(1, min(int(len(unique_times) * 0.8), len(unique_times) - 1))
    cutoff = unique_times[cutoff_idx]
    train_parts.append(g[g['window_start_s'] < cutoff])
    test_parts.append(g[g['window_start_s'] >= cutoff])

train = pd.concat(train_parts, ignore_index=True)
test = pd.concat(test_parts, ignore_index=True)

print(f"Train: {len(train)} satır | Pozitif: {int((train[label_col]==1).sum())}")
print(f"Test:  {len(test)} satır | Pozitif: {int((test[label_col]==1).sum())}")

# En önemli 10 özellik
top10 = ['freq_spectral_centroid_hz', 'freq_gamma_rel', 'freq_delta_rel',
         'complex_hjorth_mobility', 'freq_alpha_abs_uv2', 'freq_beta_rel',
         'time_rms_uv', 'time_std_uv', 'freq_alpha_rel', 'time_zero_crossing_rate']

X_train = train[top10].to_numpy(dtype=float)
y_train = train[label_col].to_numpy(dtype=int)
X_test = test[top10].to_numpy(dtype=float)
y_test = test[label_col].to_numpy(dtype=int)

pipe = Pipeline([
    ('imputer', SimpleImputer(strategy='median')),
    ('scaler', StandardScaler()),
    ('model', LogisticRegression(max_iter=2000, class_weight='balanced', random_state=42)),
])
pipe.fit(X_train, y_train)
y_proba = pipe.predict_proba(X_test)[:, 1]
y_pred = pipe.predict(X_test)

print(f'\n=== SONUÇ (10 Özellik) ===')
print(f'AUC:       {roc_auc_score(y_test, y_proba):.4f}')
print(f'Recall:    {recall_score(y_test, y_pred):.4f}')
print(f'Precision: {precision_score(y_test, y_pred):.4f}')
print(f'\n=== KARŞILAŞTIRMA (25 özellikli tam model: AUC 0.826) ===')
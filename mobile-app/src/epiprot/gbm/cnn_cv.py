"""Small spectrogram CNN, patient-wise CV, out-of-fold probabilities for stacking.

Same patient folds as epiprot.gbm.cv (seed 42). Per fold:
  * training patients -> 85 % fit / 15 % validation patients
  * each epoch draws a patient-balanced sample (<= P positives and P negatives per patient)
  * best epoch by validation PR-AUC
  * out-of-fold probabilities for every window of the test patients are saved
    (epiprot_results/gbm/<out>/oof_cnn.npz) and can be fed to LightGBM via --extra-oof.

Usage: python -m epiprot.gbm.cnn_cv --spec-dir epiprot_results/gbm/spec16 --raw-dir /raw \
           --out-dir epiprot_results/gbm/cnn_30_90 --lead-min 30 --sop-min 90
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import average_precision_score, roc_auc_score

from .labels import relabel
from .timeline import build_timeline


class SpecCNN(nn.Module):
    def __init__(self, c=3, dropout=0.3):
        super().__init__()
        def blk(i, o):
            return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU())
        self.f = nn.Sequential(blk(c, 16), nn.MaxPool2d(2), blk(16, 32), nn.MaxPool2d(2),
                               blk(32, 64), nn.AdaptiveAvgPool2d(1), nn.Flatten())
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(64, 1))

    def forward(self, x):
        return self.head(self.f(x)).squeeze(-1)


def load_labels(spec_dir, raw_dir, lead, sop):
    out = {}
    for f in sorted(spec_dir.glob("sub-*.npy")):
        if ".tmp" in f.name:
            continue
        X = np.load(f, mmap_mode="r")
        tl = build_timeline(raw_dir, f.stem, len(X))
        y0 = np.zeros(len(X), np.float32)
        yc, ev = relabel(y0, lead_min=lead, sop_min=sop,
                         seizures=tl.seizures if tl else [])
        out[f.stem] = {"X": X, "y": yc, "events": ev}
    return out


def sample(data, subs, per, rng):
    idx = []
    for s in subs:
        y = data[s]["y"]
        p, n = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
        if len(p):
            idx += [(s, i) for i in rng.choice(p, min(per, len(p)), replace=False)]
        idx += [(s, i) for i in rng.choice(n, min(per, len(n)), replace=False)]
    rng.shuffle(idx)
    return idx


def gather(data, pairs):
    # group by patient, sorted indices -> sequential memmap reads
    X = np.empty((len(pairs), 3, 40, 59), np.float16)  # half memory; cast per batch
    y = np.empty(len(pairs), np.float32)
    by = {}
    for k, (s, i) in enumerate(pairs):
        by.setdefault(s, []).append((i, k))
    for s, lst in by.items():
        lst.sort()
        ii = np.array([i for i, _ in lst])
        kk = np.array([k for _, k in lst])
        X[kk] = data[s]["X"][ii]
        y[kk] = data[s]["y"][ii]
    return X, y


@torch.no_grad()
def predict(model, Xmm, bs=2048):
    model.eval()
    out = []
    for i in range(0, len(Xmm), bs):
        out.append(torch.sigmoid(model(torch.from_numpy(np.asarray(Xmm[i:i + bs], np.float32)))).numpy())
    return np.concatenate(out) if out else np.zeros(0)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec-dir", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--lead-min", type=float, default=30.0)
    ap.add_argument("--sop-min", type=float, default=90.0)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--per-patient", type=int, default=300)
    ap.add_argument("--bs", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--threads", type=int, default=10)
    ap.add_argument("--fold", type=int, default=0, help="run only this fold (1-based); 0 = all")
    ap.add_argument("--merge", action="store_true", help="merge oof_fold*.npz and report")
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(a.threads)
    torch.manual_seed(0)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)  # noqa: E731

    data = load_labels(a.spec_dir, a.raw_dir, a.lead_min, a.sop_min)
    subs = sorted(data)
    order = list(subs)
    np.random.default_rng(42).shuffle(order)  # same folds as epiprot.gbm.cv
    folds = [order[i::a.folds] for i in range(a.folds)]
    rng = np.random.default_rng(1)
    log(f"{len(subs)} patients")

    if a.merge:
        oof = {}
        for f in sorted(a.out_dir.glob("oof_fold*.npz")):
            with np.load(f) as z:
                oof |= {k: z[k] for k in z.files}
        missing = [s for s in subs if s not in oof]
        assert not missing, f"missing folds for {len(missing)} patients"
        y = np.concatenate([data[s]["y"] for s in subs])
        p = np.concatenate([oof[s] for s in subs])
        m = y >= 0
        res = {"pooled_auc": float(roc_auc_score(y[m], p[m])),
               "pooled_ap": float(average_precision_score(y[m], p[m]))}
        log(f"POOLED CNN out-of-fold: AUC={res['pooled_auc']:.3f} AP={res['pooled_ap']:.3f}")
        np.savez(a.out_dir / "oof_cnn.npz", **oof)
        (a.out_dir / "cnn_results.json").write_text(json.dumps(res, indent=2))
        return

    oof, hist = {}, []
    for fi, test in enumerate(folds):
        if a.fold and fi + 1 != a.fold:
            continue
        rng = np.random.default_rng(100 + fi)  # per-fold stream: folds can run separately
        tr = [s for s in subs if s not in set(test)]
        rng.shuffle(tr)
        nv = max(3, round(0.15 * len(tr)))
        val, fit = tr[:nv], tr[nv:]
        Xv, yv = gather(data, sample(data, val, 1500, rng))
        model = SpecCNN()
        opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-3)
        lossf = nn.BCEWithLogitsLoss()
        best, best_state = -1.0, None
        for ep in range(a.epochs):
            model.train()
            Xt, yt = gather(data, sample(data, fit, a.per_patient, rng))
            perm = rng.permutation(len(yt))
            tl = 0.0
            for i in range(0, len(perm), a.bs):
                b = perm[i:i + a.bs]
                xb = torch.from_numpy(Xt[b].astype(np.float32))
                # light augmentation: random time roll
                xb = torch.roll(xb, int(rng.integers(0, 59)), dims=3)
                opt.zero_grad()
                loss = lossf(model(xb), torch.from_numpy(yt[b]))
                loss.backward()
                opt.step()
                tl += loss.item() * len(b)
            pv = predict(model, Xv)
            ap_v, auc_v = average_precision_score(yv, pv), roc_auc_score(yv, pv)
            log(f"fold {fi + 1} ep {ep + 1}: loss={tl / len(perm):.4f} val AUC={auc_v:.3f} AP={ap_v:.3f}")
            hist.append({"fold": fi + 1, "epoch": ep + 1, "val_auc": auc_v, "val_ap": ap_v})
            if ap_v > best:
                best, best_state = ap_v, {k: v.clone() for k, v in model.state_dict().items()}
        model.load_state_dict(best_state)
        torch.save(best_state, a.out_dir / f"cnn_fold{fi + 1}.pt")
        for s in test:
            oof[s] = predict(model, data[s]["X"]).astype(np.float32)
        yt_ = np.concatenate([data[s]["y"] for s in test])
        pt_ = np.concatenate([oof[s] for s in test])
        m = yt_ >= 0
        log(f"fold {fi + 1} TEST AUC={roc_auc_score(yt_[m], pt_[m]):.3f} "
            f"AP={average_precision_score(yt_[m], pt_[m]):.3f}")
        np.savez(a.out_dir / f"oof_fold{fi + 1}.npz", **{s: oof[s] for s in test})
        (a.out_dir / f"hist_fold{fi + 1}.json").write_text(json.dumps(
            [h for h in hist if h["fold"] == fi + 1], indent=2))
    if a.fold:
        return

    y = np.concatenate([data[s]["y"] for s in subs])
    p = np.concatenate([oof[s] for s in subs])
    m = y >= 0
    res = {"pooled_auc": float(roc_auc_score(y[m], p[m])),
           "pooled_ap": float(average_precision_score(y[m], p[m])), "history": hist}
    log(f"POOLED CNN out-of-fold: AUC={res['pooled_auc']:.3f} AP={res['pooled_ap']:.3f}")
    np.savez(a.out_dir / "oof_cnn.npz", **oof)
    (a.out_dir / "cnn_results.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

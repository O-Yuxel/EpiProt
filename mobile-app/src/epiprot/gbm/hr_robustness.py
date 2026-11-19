"""How much does the hardware-only system depend on the watch heart rate?

An optical (PPG) heart rate from a wrist watch is often lost or wrong during convulsions.
This re-runs the patient-wise 5-fold cross-validation of the three models of the phone
system (A: eeg+ecg+head 5 s, A': eeg+ecg 5 s, B: 30 s from tc30s_features) and scores every
TEST patient three times:

  clean     : heart rate as recorded
  hr_none   : no heart rate at all (watch not worn / no PPG)
  hr_lost_sz: heart rate missing from each seizure's onset until 5 min after its end

Models are always trained on clean data (as deployed); only the test inputs change. The
heart-rate features are set to missing BEFORE the context / change features are computed,
as the phone would see them. Combine afterwards with tc_ensemble (--oof5-test etc.): the
alarm threshold is chosen on the clean scores of the training patients.

--robust trains with heart-rate dropout that looks like the real thing: extra training copies
of every training patient in which the heart rate is missing during each seizure (+5 min) and
in random gaps (about 10% of the time, 1-10 min each), computed BEFORE the context / change
features exactly as the phone does. The feature set (and the phone code) stays the same.

Usage: python -m epiprot.gbm.hr_robustness --out-dir epiprot_results/gbm/hr_robust
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import numpy as np

from . import detect as D
from . import tc_detect as T

SCEN = ("clean", "hr_none", "hr_lost_sz")
# heart rate PRESENT but WRONG (optical sensor fooled by movement): the phone cannot see it is wrong, so the main
# models (not the no-heart-rate backups) are used
WRONG = ("hr_erratic_sz", "hr_frozen_sz", "hr_spurious")
HR30 = ("hr_mean", "hr_std", "hr_min", "hr_max")


def aug_mask(n, seizures, post, seg, rng, frac=0.10):
    """missing during seizures (+post windows) and in random gaps of seg=(min, max) windows"""
    m = np.zeros(n, bool)
    for on, end in seizures:
        m[int(on):min(n, int(end) + post)] = True
    target = int(frac * n)
    while target > 0 and n > seg[1]:
        L = int(rng.integers(seg[0], seg[1] + 1))
        st = int(rng.integers(0, n - L))
        m[st:st + L] = True
        target -= L
    return m


STUCK_WINDOWS = 12          # 1 minute of 5 s windows


def stuck_mask(hr, bpm, n=STUCK_WINDOWS):
    """True where the heart rate varied less than `bpm` over the last n windows (current included) and all of them
    had a value: a stuck optical sensor (a real heart rate always moves). Causal; same rule as the phone (Detector.kt)."""
    hr = np.asarray(hr, np.float64)
    out = np.zeros(len(hr), bool)
    if bpm <= 0 or len(hr) < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(hr, n)
    ok = np.all(np.isfinite(w), axis=1)
    rng = np.where(ok, np.nanmax(np.where(ok[:, None], w, 0), axis=1) - np.nanmin(np.where(ok[:, None], w, 0), axis=1), np.inf)
    out[n - 1:] = ok & (rng < bpm)
    return out


def _rng(path, scen):
    import zlib
    return np.random.default_rng(zlib.crc32(f"{Path(path).stem}:{scen}".encode()))


def _spurious_segments(n, seizures, post, seg, rng, valid, frac=0.10):
    """random activity-like episodes (frac of the time, seg windows long), away from seizures, where the watch sends"""
    protect = np.zeros(n, bool)
    for on, end in seizures:
        protect[max(0, int(on) - post):min(n, int(end) + post)] = True
    out, target = [], int(frac * n)
    while target > 0 and n > seg[1]:
        L = int(rng.integers(seg[0], seg[1] + 1))
        st = int(rng.integers(0, n - L))
        idx = np.arange(st, st + L)
        out.append(idx[~protect[idx] & valid[idx]])
        target -= L
    return out


def wrong5(F, names, seizures, scen, rng):
    """5 s base feature ecg_hr (the watch's heart rate) made wrong"""
    j, n = names.index("ecg_hr"), len(F)
    if scen == "hr_erratic_sz":          # fooled by the convulsion: random values 60-180 during the seizure (+5 min)
        for on, end in seizures:
            e = min(n, end + 60)
            F[on:e, j] = rng.uniform(60, 180, e - on)
    elif scen == "hr_frozen_sz":         # stuck at the last value before the seizure: no rise visible
        for on, end in seizures:
            prev = F[max(0, on - 60):on, j]
            prev = prev[np.isfinite(prev)]
            F[on:min(n, end + 60), j] = prev[-1] if len(prev) else np.nan
    elif scen == "hr_spurious":          # walking / sport / brushing teeth: false high rate, 10 % of the time
        for idx in _spurious_segments(n, seizures, 60, (12, 120), rng, np.isfinite(F[:, j])):
            F[idx, j] = rng.uniform(120, 170) + rng.normal(0, 4, len(idx))


def wrong30(F, names, seizures, scen, rng):
    """30 s heart-rate statistics made wrong in the same way"""
    c = {k: names.index(k) for k in (*HR30, "hr_missing")}
    n = len(F)

    def put(i, mean, std):
        F[i, c["hr_mean"]] = mean; F[i, c["hr_std"]] = std
        F[i, c["hr_min"]] = np.maximum(mean - 2 * std, 35); F[i, c["hr_max"]] = mean + 2 * std
        F[i, c["hr_missing"]] = 0.0
    if scen == "hr_erratic_sz":
        for on, end in seizures:
            i = np.arange(int(on), min(n, int(end) + 10))
            put(i, rng.uniform(60, 180, len(i)), rng.uniform(10, 40, len(i)))
    elif scen == "hr_frozen_sz":
        for on, end in seizures:
            on = int(on)
            prev = [k for k in range(max(0, on - 10), on) if np.isfinite(F[k, c["hr_mean"]])]
            i = np.arange(on, min(n, int(end) + 10))
            if prev:
                for k in HR30:
                    F[i, c[k]] = F[prev[-1], c[k]]
                F[i, c["hr_missing"]] = 0.0
    elif scen == "hr_spurious":
        for idx in _spurious_segments(n, [tuple(map(int, s)) for s in seizures], 10, (2, 20), rng,
                                      np.isfinite(F[:, c["hr_mean"]])):
            put(idx, rng.uniform(120, 170) + rng.normal(0, 4, len(idx)), rng.uniform(3, 10, len(idx)))


def mask5(n, seizures, scen):
    m = np.zeros(n, bool)
    if scen == "hr_none":
        m[:] = True
    elif scen == "hr_lost_sz":
        for on, end in seizures:
            m[on:min(n, end + 60)] = True
    return m


def x5(path, scen, m=None):
    z = np.load(path)
    names = [str(x) for x in z["names"]]
    F = z["F"].astype(np.float32).copy()
    if scen in WRONG:
        wrong5(F, names, [tuple(map(int, s)) for s in z["seizures"]], scen, _rng(path, scen))
        return T.expand(F, names)[0]
    if m is None:
        m = mask5(len(F), [tuple(map(int, s)) for s in z["seizures"]], scen)
    F[np.ix_(m, [names.index("ecg_hr")])] = np.nan
    return T.expand(F, names)[0]


def x30(path, scen, m=None):
    z = np.load(path)
    names = [str(x) for x in z["names"]]
    F = z["F"].astype(np.float32).copy()
    n = len(F)
    if scen in WRONG:
        wrong30(F, names, z["seizures"], scen, _rng(path, scen))
        return D.make_features(F, "both")
    if m is not None:
        pass
    elif scen == "hr_none":
        m = np.ones(n, bool)
    elif scen == "hr_lost_sz":
        m = np.zeros(n, bool)
        for on, end in z["seizures"]:
            m[int(on):min(n, int(end) + 10)] = True
    else:
        m = np.zeros(n, bool)
    for c in HR30:
        F[m, names.index(c)] = np.nan
    F[m, names.index("hr_missing")] = 1.0
    return D.make_features(F, "both")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data5", type=Path, default=Path("epiprot_results/gbm/tc5s"))
    ap.add_argument("--data30", type=Path, default=Path("epiprot_results/gbm/sz30_hw"))
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--parts", nargs="+", default=["b", "eeg+ecg+head", "eeg+ecg"])
    ap.add_argument("--robust", action="store_true", help="train with realistic heart-rate dropout")
    ap.add_argument("--scenarios", nargs="+", default=list(SCEN), help=f"test-time scenarios; also {WRONG}")
    ap.add_argument("--no-hr", action="store_true",
                    help="model B without any heart-rate feature (backup while the watch sends no heart rate)")
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)  # noqa: E731

    if "b" in a.parts:
        data = D.load(a.data30)
        subs = sorted(data)
        if a.no_hr:
            with np.load(a.data30 / f"{subs[0]}.npz") as z:
                keep = [i for i, c in enumerate(z["names"]) if not str(c).startswith("hr_")]
            for d in data.values():
                d["F"] = d["F"][:, keep]
            log(f"B without heart rate: {len(keep)} base features")
        order = list(subs)
        np.random.default_rng(42).shuffle(order)
        folds = [order[i::5] for i in range(5)]
        X = {s: D.make_features(d["F"], "both") for s, d in data.items()}
        if a.robust:
            arng = np.random.default_rng(7)
            for s in subs:
                n = len(data[s]["y"])
                m = aug_mask(n, data[s]["seizures"], 10, (2, 20), arng)
                data[f"{s}#aug"] = data[s]
                X[f"{s}#aug"] = x30(a.data30 / f"{s}.npz", None, m).astype(np.float16)
            log("B: heart-rate dropout copies ready")
        out = {sc: {} for sc in a.scenarios}
        for fi, test in enumerate(folds):
            rng = np.random.default_rng(100 + fi)
            tr = [s for s in subs if s not in set(test)]
            rng.shuffle(tr)
            nv = max(3, round(0.15 * len(tr)))
            val, fit = tr[:nv], tr[nv:]
            if a.robust:
                fit = fit + [f"{s}#aug" for s in fit]
            Xs = dict(X)
            keys = []
            for s in test:
                for sc in a.scenarios:
                    Xs[f"{s}@{sc}"] = X[s] if a.no_hr else x30(a.data30 / f"{s}.npz", sc)
                    keys.append(f"{s}@{sc}")
            p = D.fit_predict("lgbm", data, Xs, fit, val, keys, rng, 2000, a.threads)
            for k, v in p.items():
                s, sc = k.split("@")
                out[sc][s] = v
            log(f"B fold {fi + 1}/5 done")
        for sc in a.scenarios:
            np.savez(a.out_dir / f"b_{sc}.npz", **out[sc])
        del data, X

    groups = [g for g in a.parts if g != "b"]
    if groups:
        data, cols = T.load(a.data5)
        subs = sorted(data)
        order = list(subs)
        np.random.default_rng(42).shuffle(order)
        folds = [order[i::5] for i in range(5)]
        aug = {}
        if a.robust:   # per patient: all seizure windows + 3000 random normal ones, with HR dropout
            arng = np.random.default_rng(7)
            for s in subs:
                d = data[s]
                n = len(d["y"])
                with np.load(a.data5 / f"{s}.npz") as z:
                    sz = [tuple(map(int, q)) for q in z["seizures"]]
                m = aug_mask(n, sz, 60, (12, 120), arng)
                pos, neg = np.flatnonzero(d["ytr"] == 1), np.flatnonzero(d["ytr"] == 0)
                if len(neg) > 3000:
                    neg = arng.choice(neg, 3000, replace=False)
                idx = np.r_[pos, neg]
                aug[s] = (x5(a.data5 / f"{s}.npz", None, m)[idx], d["ytr"][idx], d["w"][idx])
            log("A: heart-rate dropout copies ready")
        for g in groups:
            colidx = np.array([i for i, c in enumerate(cols) if re.search(T.GROUPS[g], c)])
            T.OPTS["hard_neg"], T.OPTS["drop_ecg"] = 1000, 0.1
            T.OPTS["ecg_local"] = np.array([j for j, i in enumerate(colidx)
                                            if cols[i].startswith("ecg")], int)
            out = {sc: {} for sc in a.scenarios}
            for fi, test in enumerate(folds):
                tr = [s for s in subs if s not in set(test)]
                extra = None
                if a.robust:
                    extra = [[], [], []]
                    for s in tr:
                        ex, ey, ew = aug[s]
                        extra[0].append(ex[:, colidx].astype(np.float32))
                        extra[1].append(ey)
                        extra[2].append(ew)
                    extra = (np.vstack(extra[0]), np.concatenate(extra[1]), np.concatenate(extra[2]))
                b = T.train(data, tr, colidx, np.random.default_rng(100 + fi), threads=a.threads,
                            extra=extra)
                for sc in a.scenarios:
                    for s in test:
                        Xt = x5(a.data5 / f"{s}.npz", sc)[:, colidx].astype(np.float32)
                        out[sc][s] = np.concatenate([b.predict(Xt[i:i + 50000])
                                                     for i in range(0, len(Xt), 50000)]).astype(np.float32)
                log(f"{g} fold {fi + 1}/5 done")
            for sc in a.scenarios:
                np.savez(a.out_dir / f"a_{g}_{sc}.npz", **out[sc])


if __name__ == "__main__":
    main()

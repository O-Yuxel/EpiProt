"""How long should the post-seizure "high risk" warning last? (SeizeIT2)

For every seizure (index event) we look at the following hours of the same patient's
recording: was there another seizure within X hours? Only index seizures with at least
X hours of recording afterwards count (censoring). Compared with the chance of a seizure
starting in a random X-hour window that does NOT follow a seizure within 24 h.

Reported separately for index = any seizure and index = tonic-clonic (the type the
device detects reliably), and next = any seizure / tonic-clonic.

Usage: python -m epiprot.gbm.cluster_risk --data-dir epiprot_results/gbm/tc5s
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .tc_detect import W, is_tc

HOURS = (1, 2, 4, 6, 8, 12, 24)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("epiprot_results/gbm/cluster_risk.json"))
    a = ap.parse_args(argv)
    H = 3600 / W
    pats = []
    for f in sorted(a.data_dir.glob("sub-*.npz")):
        if ".tmp" in f.name:
            continue
        with np.load(f) as z:
            n = len(z["F"])
            sz = [(int(s[0]), int(s[1]), is_tc(str(t))) for s, t in zip(z["seizures"], z["sz_type"])]
        pats.append((n, sorted(sz)))

    res = {}
    rng = np.random.default_rng(0)
    for idx_kind in ("any", "tc"):
        for next_kind in ("any", "tc"):
            row = {}
            for X in HOURS:
                w = int(X * H)
                hit = tot = 0
                for n, sz in pats:
                    for i, (on, end, tc) in enumerate(sz):
                        if idx_kind == "tc" and not tc:
                            continue
                        if end + w > n:
                            continue  # not enough follow-up
                        tot += 1
                        hit += any(end <= o < end + w for o, _, t2 in sz[i + 1:]
                                   if next_kind == "any" or t2)
                # baseline: random windows not within 24 h after any seizure
                bh = bt = 0
                for n, sz in pats:
                    ends = np.array([e for _, e, _ in sz])
                    ons = np.array([o for o, _, t in sz if next_kind == "any" or t])
                    if n <= w:
                        continue
                    for st in rng.integers(0, n - w, size=200):
                        if len(ends) and ((ends <= st) & (ends > st - 24 * H)).any():
                            continue
                        bt += 1
                        bh += bool(len(ons) and ((ons >= st) & (ons < st + w)).any())
                p, b = hit / max(tot, 1), bh / max(bt, 1)
                row[str(X)] = {"index_seizures": tot, "followed": hit, "p_after": p,
                               "p_baseline": b, "ratio": p / b if b else None}
            res[f"index={idx_kind}, next={next_kind}"] = row
            print(f"\nindex={idx_kind:3s} next={next_kind:3s}")
            for X, r in row.items():
                print(f"  within {X:>2s} h: {r['followed']:3d}/{r['index_seizures']:3d} = {r['p_after']:5.1%}"
                      f"  vs random window {r['p_baseline']:5.1%}  -> {r['ratio'] or float('nan'):.1f}x")
    a.out.write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

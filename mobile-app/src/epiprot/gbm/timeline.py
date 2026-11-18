"""Per-patient chronological timeline rebuilt from the raw SeizeIT2 BIDS events.

The cached tensors concatenate a patient's runs in *lexicographic* file order, so for
patients with >= 100 runs (sub-081, 089, 092, 095, 121) "run-100" comes before "run-10"
and the window order is not chronological. Labels were also computed per run, so a
seizure early in a run had no pre-ictal windows at the end of the previous run.

Here we:
  * compute each run's window count (floor(recordingDuration / 30)), which matches the
    cache length exactly,
  * build the permutation lexicographic -> numeric run order,
  * place every seizure on the continuous timeline (runs assumed back-to-back; the
    true gaps are not available because timestamps are anonymised).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

WINDOW_S = 30.0


@dataclass
class Timeline:
    perm: np.ndarray                    # cache index for each chronological position
    seizures: list[tuple[int, int]]     # (onset_idx, end_idx) on the chronological timeline
    run_starts: np.ndarray              # chronological window index where each run starts


def _run_num(p: Path) -> int:
    return int(re.search(r"run-(\d+)", p.name).group(1))


def build_timeline(raw_dir: Path, sub: str, n_cache: int) -> Timeline | None:
    tsvs = list((raw_dir / sub / "ses-01" / "eeg").glob("*_events.tsv"))
    if not tsvs:
        return None
    info = {}
    for t in tsvs:
        with open(t, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        dur = float(rows[0]["recordingDuration"]) if rows else 0.0
        sz = [(float(r["onset"]), float(r["onset"]) + float(r["duration"]))
              for r in rows if r["eventType"].lower().startswith("sz")]
        info[t] = (int(dur // WINDOW_S), sz)

    lex = sorted(tsvs, key=lambda p: p.name)
    num = sorted(tsvs, key=_run_num)
    if sum(info[t][0] for t in lex) != n_cache:
        return None  # cannot align safely; caller falls back to cache labels

    lex_start, off = {}, 0
    for t in lex:
        lex_start[t] = off
        off += info[t][0]

    perm, seizures, run_starts, pos = [], [], [], 0
    for t in num:
        n, sz = info[t]
        run_starts.append(pos)
        perm.append(np.arange(lex_start[t], lex_start[t] + n))
        for on_s, end_s in sz:
            on = pos + int(on_s // WINDOW_S)
            end = pos + int(np.ceil(end_s / WINDOW_S))
            if on < pos + n:
                seizures.append((on, min(max(end, on + 1), pos + n)))
        pos += n
    seizures.sort()
    return Timeline(np.concatenate(perm), seizures, np.asarray(run_starts))

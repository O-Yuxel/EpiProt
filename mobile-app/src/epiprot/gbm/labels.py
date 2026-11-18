"""Configurable pre-ictal labels and seizure events derived from the cached window labels.

Cached labels: 1 = 5-30 min before onset, 0 = other, -1 = 5-min gap + ictal. Windows
are chronological (30 s each), and each run of -1 is GAP (10) windows of gap followed
by the seizure itself, so seizure onsets/ends can be recovered without the raw
annotations and labels can be rebuilt for any horizon.

New labelling for lead time L and seizure-occurrence period S (minutes):
    positive  : windows starting in [onset - (L+S), onset - L)
    excluded  : [onset - L, onset)               (too late to warn L minutes ahead)
                [onset - (L+S) - pre_buffer, onset - (L+S))   (ambiguous boundary)
                ictal, and `postictal_min` after each seizure
    negative  : everything else
An event is a "lead" seizure whose positive period is >= 90 % intact (not cut by the
post-ictal period of a previous seizure or by the recording start).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WIN_PER_MIN = 2
GAP = 10  # windows of the 5-min gap at the start of each cached -1 run


@dataclass
class Event:
    pos_start: int  # first positive window
    pos_end: int    # one past last positive window
    onset: int = -1


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs as (start, end) half-open intervals."""
    if not mask.any():
        return []
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def seizures_from_cache_labels(y: np.ndarray) -> list[tuple[int, int]]:
    """(onset_idx, end_idx) per seizure, from the -1 runs of the cached labels."""
    out = []
    for s, e in _runs(np.asarray(y) == -1):
        onset = s + GAP if s > 0 else s  # a run at index 0 has an unknown gap
        out.append((min(onset, e - 1), e))
    return out


def relabel(
    y: np.ndarray,
    postictal_min: float = 60.0,
    pre_buffer_min: float = 30.0,
    min_preictal_frac: float = 0.9,
    lead_min: float = 5.0,
    sop_min: float = 25.0,
    seizures: list[tuple[int, int]] | None = None,
) -> tuple[np.ndarray, list[Event]]:
    """Return (labels, lead_events). Defaults reproduce the original 5-30 min horizon.

    If `seizures` [(onset_idx, end_idx), ...] is given (e.g. from the raw annotations via
    epiprot.gbm.timeline), it is used instead of the seizures implied by the cache labels.
    """
    y = np.asarray(y, dtype=np.float32)
    n = len(y)
    L, S = int(lead_min * WIN_PER_MIN), int(sop_min * WIN_PER_MIN)
    B, post = int(pre_buffer_min * WIN_PER_MIN), int(postictal_min * WIN_PER_MIN)
    if seizures is None:
        sz = seizures_from_cache_labels(y)
        ictal = y == -1
    else:
        sz = list(seizures)
        ictal = np.zeros(n, bool)
        for on, end in sz:
            ictal[on:end] = True

    yc = np.where(ictal, -1.0, 0.0).astype(np.float32)
    pos = np.zeros(n, bool)
    excl = np.zeros(n, bool)
    for onset, end in sz:
        a, b = max(0, onset - L - S), max(0, onset - L)
        pos[a:b] = True
        excl[b:onset] = True
        excl[max(0, a - B):a] = True
        excl[end:min(n, end + post)] = True
    post_mask = np.zeros(n, bool)
    for _onset, end in sz:
        post_mask[end:min(n, end + post)] = True

    yc[pos] = 1.0
    yc[excl & ~pos] = -1.0
    yc[post_mask | ictal] = -1.0  # post-ictal and ictal always win

    events = []
    need = int(np.ceil(min_preictal_frac * S))
    for onset, _end in sz:
        a, b = max(0, onset - L - S), max(0, onset - L)
        if b - a > 0 and (yc[a:b] == 1).sum() >= need:
            events.append(Event(int(a), int(b), int(onset)))
        else:
            seg = yc[a:b]
            seg[seg == 1] = -1.0
    # positives not belonging to any lead event (overlapping clusters) -> excluded
    keep = np.zeros(n, bool)
    for ev in events:
        keep[ev.pos_start:ev.pos_end] = True
    yc[(yc == 1) & ~keep] = -1.0
    return yc, events

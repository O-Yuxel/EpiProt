"""Cleaner labels and seizure events derived from the cached window labels.

The cached labels mark every window that is not pre-ictal / gap / ictal as 0, which
makes post-ictal windows (right after a seizure) and windows 30-60 min before onset
"negatives". Both are ambiguous and hurt prediction. Windows are chronological, and
each run of -1 is the 5-min gap plus the seizure itself, so we can repair this
without the raw annotations.

Window = 30 s, so 2 windows per minute.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WIN_PER_MIN = 2
PREICTAL_LEN = 50  # 5-30 min before onset = 25 min = 50 windows


@dataclass
class Event:
    pos_start: int  # first pre-ictal window (30 min before onset)
    pos_end: int    # one past last pre-ictal window (5 min before onset)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs as (start, end) half-open intervals."""
    if not mask.any():
        return []
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def relabel(
    y: np.ndarray,
    postictal_min: float = 60.0,
    pre_buffer_min: float = 30.0,
    min_preictal_frac: float = 0.9,
) -> tuple[np.ndarray, list[Event]]:
    """Return (y_clean, lead_events).

    - post-ictal: `postictal_min` after each seizure -> excluded (-1). Pre-ictal windows
      falling there belong to clustered seizures that cannot be predicted separately,
      so they are excluded too.
    - pre-buffer: negatives within `pre_buffer_min` before a pre-ictal period -> excluded.
    - pre-ictal runs that are truncated (cluster seizure, recording start) -> excluded.
    """
    y = np.asarray(y, dtype=np.float32)
    yc = y.copy()
    n = len(y)
    post = int(postictal_min * WIN_PER_MIN)
    pre = int(pre_buffer_min * WIN_PER_MIN)

    for s, _e in _runs(y == 1):
        lo = max(0, s - pre)
        seg = yc[lo:s]
        seg[seg == 0] = -1
    for _s, e in _runs(y == -1):
        yc[e:min(n, e + post)] = -1

    events = []
    min_len = int(np.ceil(min_preictal_frac * PREICTAL_LEN))
    for s, e in _runs(yc == 1):
        if e - s >= min_len:
            events.append(Event(int(s), int(e)))
        else:
            yc[s:e] = -1
    return yc, events

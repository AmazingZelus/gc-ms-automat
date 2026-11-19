"""Alignment: group peaks of different runs that belong to the same compound.

Two peaks are "the same compound" when their retention times differ by at most
`rt_tolerance` [min] AND their spectral similarity is at least `min_similarity`.
Each compound (cluster) holds at most one peak per run.

Procedure (deterministic):
  1. Go through all peaks from the highest to the lowest (large peaks have the
     most reliable spectra, so they define the clusters).
  2. Put the peak into the existing cluster that has no peak from this run yet,
     lies within the RT tolerance and has the highest spectral similarity
     (at least min_similarity); otherwise start a new cluster.
  3. Merge neighbouring clusters that satisfy the same two criteria and share no
     run (fixes clusters split only because of the processing order).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np


@dataclass
class PeakRef:
    """A detected peak together with its run and spectrum."""

    run: int              # index of the run
    index: int            # index of the peak within that run
    rt: float             # apex retention time [min]
    height: float         # apex height [counts]
    spectrum: np.ndarray  # relative spectrum [%] on the common m/z axis


@dataclass
class Cluster:
    """One compound: at most one peak per run."""

    members: dict[int, PeakRef] = field(default_factory=dict)
    rt: float = 0.0
    spectrum: np.ndarray | None = None  # spectrum of the highest member

    def add(self, peak: PeakRef) -> None:
        # This adds a peak; the reference spectrum is always the highest peak's.
        self.members[peak.run] = peak
        self.rt = float(np.mean([m.rt for m in self.members.values()]))
        highest = max(self.members.values(), key=lambda m: m.height)
        self.spectrum = highest.spectrum


def align_peaks(peaks: list[PeakRef], n_runs: int, rt_tolerance: float, min_similarity: float,
                similarity: Callable[[np.ndarray, np.ndarray], float]) -> list[Cluster]:
    """Group peaks into clusters (see module description). Sorted by RT."""
    clusters: list[Cluster] = []
    rts = np.empty(0)
    has_run = np.zeros((0, n_runs), dtype=bool)

    # ---- Step 1+2: assign peaks from the highest to the lowest ----
    order = sorted(range(len(peaks)), key=lambda i: (-peaks[i].height, i))
    for i in order:
        peak = peaks[i]
        candidates = np.flatnonzero((np.abs(rts - peak.rt) <= rt_tolerance) & ~has_run[:, peak.run]) \
            if clusters else np.empty(0, dtype=int)
        best, best_score = None, -1.0
        for c in candidates:
            score = similarity(clusters[c].spectrum, peak.spectrum)
            if score >= min_similarity and score > best_score:
                best, best_score = int(c), score
        if best is None:
            cluster = Cluster()
            cluster.add(peak)
            clusters.append(cluster)
            rts = np.append(rts, cluster.rt)
            has_run = np.vstack([has_run, np.zeros(n_runs, dtype=bool)])
            best = len(clusters) - 1
        else:
            clusters[best].add(peak)
            rts[best] = clusters[best].rt
        has_run[best, peak.run] = True

    # ---- Step 3: merge neighbouring clusters that fit together ----
    clusters.sort(key=lambda c: c.rt)
    merged = True
    while merged:
        merged = False
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                first, second = clusters[a], clusters[b]
                if second.rt - first.rt > rt_tolerance:
                    break
                if set(first.members) & set(second.members):
                    continue
                if similarity(first.spectrum, second.spectrum) >= min_similarity:
                    for member in second.members.values():
                        first.add(member)
                    del clusters[b]
                    clusters.sort(key=lambda c: c.rt)
                    merged = True
                    break
            if merged:
                break
    return clusters

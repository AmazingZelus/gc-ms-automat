"""Retention indices from n-alkanes."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

from .cdf import Run
from .signal import pick_peaks, process_trace
from .spectra import MzAxis, peak_spectrum, top_ions


@dataclass
class Alkane:
    """One n-alkane reference point: carbon number and retention time [min]."""

    carbons: int
    rt: float
    source: str = "ručně"


def retention_index(rt: float, alkanes: list[Alkane]) -> float:
    """Linear (temperature-programmed) retention index; NaN outside the alkane range.

    van den Dool & Kratz (1963), J. Chromatogr. 11, 463-471:
        RI = 100 * [ n + (N - n) * (t_x - t_n) / (t_N - t_n) ]
    t_n, t_N = retention times [min] of the alkanes eluting just before and after
    the compound, n, N their carbon numbers (N - n = 1 for consecutive alkanes).
    """
    points = sorted((a for a in alkanes if math.isfinite(a.rt)), key=lambda a: a.rt)
    for before, after in zip(points, points[1:]):
        if before.rt <= rt <= after.rt and after.rt > before.rt:
            fraction = (rt - before.rt) / (after.rt - before.rt)
            return 100.0 * (before.carbons + (after.carbons - before.carbons) * fraction)
    return float("nan")


def parse_alkane_table(text: str) -> list[Alkane]:
    """Parse pasted/imported alkane times: one alkane per line, 'C10; 5.234' or 'C10 5,234'.

    Lines that do not contain a carbon number and a time are skipped (e.g. a header).
    """
    result = []
    for line in text.splitlines():
        # This splits on semicolon/tab/space; a comma separates columns only if
        # nothing else does (otherwise it is a decimal comma).
        parts = [p for p in re.split(r"[;\t ]+", line.strip()) if p]
        if len(parts) == 1 and parts[0].count(",") == 1:
            parts = parts[0].split(",")
        if len(parts) < 2:
            continue
        try:
            carbons = int(parts[0].lstrip("Cc"))
            rt = float(parts[1].replace(",", "."))
        except ValueError:
            continue
        if carbons > 0 and rt > 0:
            result.append(Alkane(carbons, rt, "import"))
    return sorted(result, key=lambda a: a.rt)


# Ions typical for n-alkanes (CnH2n+1 fragments and alkenyl ions).
ALKANE_IONS = {41, 42, 43, 55, 56, 57, 70, 71, 85}


def find_alkanes(runs: list[Run], axis: MzAxis, baseline_window_min: float,
                 smooth_points: int, carbon_range: tuple[int, int] = (5, 40)) -> list[Alkane]:
    """Suggest n-alkane retention times from alkane-standard runs (user checks them).

    1. Peaks in the summed ion chromatogram of m/z 43+57+71+85.
    2. Keep peaks whose 3 strongest ions are typical alkane ions.
    3. Carbon number from the largest molecular ion M+ = 14n + 2 present (>= 0.3 %).
    4. Pick the longest chain with increasing RT and increasing carbon number,
       preferring large peaks (dynamic programming over log peak heights).
    The molecular ion of long alkanes is weak, so the result must be checked.
    """
    candidates = []
    for run in runs:
        # This builds the alkane-ion chromatogram and finds its peaks.
        cols = [m - run.mz_min for m in (43, 57, 71, 85) if 0 <= m - run.mz_min < run.spectra.shape[1]]
        if not cols:
            continue
        signal = np.asarray(run.spectra[:, cols].sum(axis=1)).ravel()
        trace = process_trace(run.rt_min, signal, baseline_window_min, smooth_points, 0.01, 30.0)
        for peak in pick_peaks(trace, 0.01, 30.0, 0.0, 1e9):
            spectrum = peak_spectrum(run, peak.apex, peak.start, peak.end, axis)
            if not all(m in ALKANE_IONS for m, _ in top_ions(spectrum, axis, 3)):
                continue
            carbons = [n for n in range(carbon_range[0], carbon_range[1] + 1)
                       if axis.lo <= 14 * n + 2 <= axis.hi and spectrum[14 * n + 2 - axis.lo] >= 0.3]
            if carbons:
                candidates.append((peak.rt, max(carbons), peak.height, run.name))

    # This keeps the largest candidate per carbon number and run.
    best: dict[tuple[str, int], tuple] = {}
    for c in candidates:
        key = (c[3], c[1])
        if key not in best or best[key][2] < c[2]:
            best[key] = c
    items = sorted(best.values())
    if not items:
        return []

    # This chooses the best increasing chain (RT and carbon number both increase).
    score = [math.log(max(c[2], 1.0)) for c in items]
    total = score[:]
    previous = [-1] * len(items)
    for i in range(len(items)):
        for j in range(i):
            if items[j][0] < items[i][0] and items[j][1] < items[i][1] and total[j] + score[i] > total[i]:
                total[i] = total[j] + score[i]
                previous[i] = j
    i = int(np.argmax(total))
    chain = []
    while i >= 0:
        chain.append(items[i])
        i = previous[i]
    return [Alkane(c[1], round(c[0], 4), f"auto ({c[3]})") for c in reversed(chain)]

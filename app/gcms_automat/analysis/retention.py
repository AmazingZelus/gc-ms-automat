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


def check_alkanes(alkanes: list[Alkane]) -> str:
    """'' if usable for RI, else a Czech explanation of what is wrong.

    Carbon numbers must be unique and increase together with the retention time.
    """
    points = sorted(alkanes, key=lambda a: a.rt)
    carbons = [a.carbons for a in points]
    if len(set(carbons)) != len(carbons):
        dup = sorted({c for c in carbons if carbons.count(c) > 1})
        return "Počet uhlíků se opakuje: " + ", ".join(f"C{c}" for c in dup) + "."
    for a, b in zip(points, points[1:]):
        if b.carbons <= a.carbons:
            return f"C{b.carbons} ({b.rt:.3f} min) eluuje po C{a.carbons} ({a.rt:.3f} min): počty uhlíků musí s RT stoupat."
        if b.rt == a.rt:
            return f"C{a.carbons} a C{b.carbons} mají stejný RT."
    return ""


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


# Natural abundance of 13C [fraction] (IUPAC representative value 1.07 %).
C13_ABUNDANCE = 0.0107
# Peak search in the alkane-ion chromatogram: alkane standards give large, clean
# peaks, so a strict S/N (30) and a low height limit (0.01 % of the largest) are used.
ALKANE_PEAK_SNR = 30.0
ALKANE_PEAK_HEIGHT_PCT = 0.01


def molecular_ion_excess(spectrum: np.ndarray, axis: MzAxis, carbons: int) -> float:
    """Signal at M+ = 14n + 2 not explained by the 13C isotope of the ion at 14n + 1 [%].

    The fragment CnH2n+1+ (m/z 14n + 1; [M-H]+ of this alkane, but also an ordinary
    fragment of every LONGER alkane) has a 13C isotope peak exactly at 14n + 2:
    I_iso = I(14n + 1) * n * 0.0107. Without subtracting it, a fragment of a long
    alkane would be read as the molecular ion of a short one.
    """
    m = 14 * carbons + 2
    if not (axis.lo <= m - 1 and m <= axis.hi):
        return 0.0
    observed = float(spectrum[m - axis.lo])
    isotope = float(spectrum[m - 1 - axis.lo]) * carbons * C13_ABUNDANCE
    return observed - isotope


def find_alkanes(runs: list[Run], axis: MzAxis, baseline_log_lambda: float, smooth_points: int,
                 min_molecular_ion_pct: float = 0.3, carbon_range: tuple[int, int] = (5, 40)) -> list[Alkane]:
    """Suggest n-alkane retention times from alkane-standard runs (user checks them).

    1. Peaks in the summed ion chromatogram of m/z 43+57+71+85.
    2. Keep peaks whose 3 strongest ions are typical alkane ions.
    3. Carbon number = largest n whose molecular ion M+ = 14n + 2 exceeds the
       13C isotope contribution by >= min_molecular_ion_pct % (molecular_ion_excess).
    4. Pick the longest chain with increasing RT and increasing carbon number,
       preferring large peaks (dynamic programming over log peak heights).
    Alkanes whose molecular ion is too weak are NOT guessed; add them by hand.
    """
    candidates = []
    for run in runs:
        # This builds the alkane-ion chromatogram and finds its peaks.
        cols = [m - run.mz_min for m in (43, 57, 71, 85) if 0 <= m - run.mz_min < run.spectra.shape[1]]
        if not cols:
            continue
        signal = np.asarray(run.spectra[:, cols].sum(axis=1)).ravel()
        trace = process_trace(run.rt_min, signal, baseline_log_lambda, smooth_points)
        for peak in pick_peaks(trace, ALKANE_PEAK_HEIGHT_PCT, ALKANE_PEAK_SNR, 0.0, 1e9):
            spectrum = peak_spectrum(run, peak.apex, peak.start, peak.end, axis)
            if not all(m in ALKANE_IONS for m, _ in top_ions(spectrum, axis, 3)):
                continue
            carbons = [n for n in range(carbon_range[0], carbon_range[1] + 1)
                       if molecular_ion_excess(spectrum, axis, n) >= min_molecular_ion_pct]
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

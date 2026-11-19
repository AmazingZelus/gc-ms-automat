"""Chromatogram processing: baseline, smoothing, noise, peak picking, integration.

All numerical work uses established library functions:
  * pybaselines Baseline.arpls  (asymmetrically reweighted penalized least squares,
    Baek, Park, Ahn & Choo 2015, Analyst 140, 250-257; library: D. Erb, pybaselines)
  * scipy.signal.savgol_filter  (Savitzky & Golay 1964, Anal. Chem. 36, 1627)
  * scipy.signal.find_peaks       (peak detection by prominence)
  * scipy.stats.median_abs_deviation (robust noise estimate)
  * scipy.integrate.trapezoid   (trapezoidal rule)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pybaselines import Baseline
from scipy.integrate import trapezoid
from scipy.signal import find_peaks, savgol_filter
from scipy.stats import median_abs_deviation


@dataclass
class ProcessedTrace:
    """A baseline-corrected chromatogram of one run."""

    rt_min: np.ndarray      # [min]
    raw: np.ndarray         # TIC as measured [counts]
    baseline: np.ndarray    # estimated baseline [counts]
    corrected: np.ndarray   # raw - baseline, smoothed [counts] (may be slightly negative: noise)
    noise: float            # noise standard deviation of the unsmoothed raw - baseline [counts]


@dataclass
class Peak:
    """One detected peak in one run. Indices are scan numbers."""

    apex: int
    start: int
    end: int
    rt: float        # apex retention time, refined between scans [min]
    t0: float        # integration window start [min]
    t1: float        # integration window end [min]
    height: float    # corrected signal at the apex [counts]
    snr: float       # height / noise [-]
    area: float      # integrated corrected signal [counts * s]


@dataclass(frozen=True)
class WindowRule:
    """Where a peak's integration window ends (both user parameters).

    The window ends, on each side, where the signal falls to the HIGHER of
      end_pct     % of the peak's height above the baseline (1 % = 2.9 sigma for
                  a Gaussian peak, which leaves out 0.4 % of its area), and
      noise_sigma x noise (the peak has disappeared into the noise; stops small
                  peaks from wandering into the noise, which would bias them).
    """

    end_pct: float = 1.0
    noise_sigma: float = 1.0


def estimate_noise(y: np.ndarray) -> float:
    """Noise standard deviation from point-to-point differences.

    sigma = MAD(diff(y)) * 1.4826 / sqrt(2)   [same unit as y]
    The MAD (scaled to a normal distribution by scipy, scale="normal") ignores
    peaks; differences remove slow drift; dividing by sqrt(2) converts the spread
    of a difference of two noisy points back to the spread of one point.
    Must be applied to UNSMOOTHED data (smoothing makes neighbours similar).
    """
    if y.size < 3:
        return 1e-9
    sigma = float(median_abs_deviation(np.diff(y), scale="normal")) / np.sqrt(2.0)
    return max(sigma, 1e-9)


def _smooth(y: np.ndarray, smooth_points: int) -> np.ndarray:
    """Savitzky-Golay smoothing (2nd order); window forced odd; <3 = no smoothing."""
    if smooth_points >= 3 and y.size > smooth_points:
        points = smooth_points if smooth_points % 2 else smooth_points + 1
        return savgol_filter(y, window_length=points, polyorder=2, mode="interp")
    return y.copy()


def process_trace(rt_min: np.ndarray, raw: np.ndarray, baseline_log_lambda: float,
                  smooth_points: int) -> ProcessedTrace:
    """Subtract the baseline (arPLS) and smooth the chromatogram.

    arPLS fits a smooth curve that follows the signal where there are no peaks and
    goes under the peaks; the weights take the noise into account, so the baseline
    runs through the MIDDLE of the noise (no bias of small peaks) and also stays
    under peak tails and crowded regions. lambda = 10^baseline_log_lambda sets the
    stiffness (higher = stiffer). Tests: results change < 1 % between 10^6 and 10^8.
    The corrected signal is not clipped at 0: noise is symmetric and cancels out.
    """
    raw = np.asarray(raw, dtype=float)
    if raw.size < 10:
        baseline = np.full(raw.size, float(np.median(raw)) if raw.size else 0.0)
    else:
        baseline = Baseline(np.arange(raw.size)).arpls(raw, lam=10.0 ** baseline_log_lambda)[0]
    corrected = _smooth(raw - baseline, smooth_points)
    return ProcessedTrace(rt_min, raw, baseline, corrected, estimate_noise(raw - baseline))


def _peak_windows(y: np.ndarray, threshold: float, rule: WindowRule, noise: float) -> list[tuple[int, int, int]]:
    """(start, apex, end) scan indices of peaks with prominence >= threshold.

    Peaks are found with scipy.signal.find_peaks (prominence). The window is then
    found like in a classical integrator, separately on each side of the apex:
    walk away from the apex until EITHER the signal (already baseline-corrected,
    so measured from the baseline) falls below the end level (WindowRule) OR the
    lowest point towards the neighbouring peak is reached ("drop line" at the
    valley). So unresolved neighbours share the valley exactly: no gap, no overlap.
    """
    apexes, _ = find_peaks(y, prominence=threshold)
    windows = []
    for k, apex in enumerate(apexes):
        level = max(rule.end_pct / 100.0 * float(y[apex]), rule.noise_sigma * noise)
        # Right side: search up to the next apex (or the end of the run).
        stop = int(apexes[k + 1]) if k < apexes.size - 1 else y.size - 1
        segment = y[apex:stop + 1]
        valley = int(np.argmin(segment))
        below = np.flatnonzero(segment[:valley + 1] < level)
        end = apex + (int(below[0]) if below.size else valley)
        # Left side: search back to the previous apex (or the start of the run).
        stop = int(apexes[k - 1]) if k > 0 else 0
        segment = y[stop:apex + 1][::-1]
        valley = int(np.argmin(segment))
        below = np.flatnonzero(segment[:valley + 1] < level)
        start = apex - (int(below[0]) if below.size else valley)
        if end - start >= 2:
            windows.append((int(start), int(apex), int(end)))
    return windows


def refine_apex(rt_min: np.ndarray, y: np.ndarray, i: int) -> float:
    """Apex time between scans from a parabola through 3 points [min].

    For points (i-1, i, i+1) with values a, b, c the vertex lies at
    i + 0.5 * (a - c) / (a - 2b + c)   (in scans), converted to minutes.
    """
    if 0 < i < y.size - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        curvature = a - 2 * b + c
        if curvature < 0:
            offset = 0.5 * (a - c) / curvature
            return float(rt_min[i] + offset * (rt_min[i + 1] - rt_min[i]))
    return float(rt_min[i])


def integrate_window(trace: ProcessedTrace, t0: float, t1: float) -> float:
    """Area of the corrected signal between t0 and t1 [counts * s].

    Trapezoidal rule; the window edges are linearly interpolated, so the area
    does not jump when an edge moves between two scans. Time converted min -> s.
    """
    if not t1 > t0:
        return 0.0
    rt, y = trace.rt_min, trace.corrected
    # This takes the scans inside the window plus interpolated edge points.
    inside = (rt > t0) & (rt < t1)
    t = np.concatenate(([t0], rt[inside], [t1]))
    v = np.concatenate(([np.interp(t0, rt, y)], y[inside], [np.interp(t1, rt, y)]))
    return float(trapezoid(v, t * 60.0))


def pick_peaks(trace: ProcessedTrace, min_height_pct: float, min_snr: float,
               rt_min: float, rt_max: float, rule: WindowRule = WindowRule()) -> list[Peak]:
    """Find peaks in the corrected chromatogram inside [rt_min, rt_max].

    A peak is kept when its prominence is at least BOTH min_height_pct % of the
    largest signal INSIDE the evaluated RT range (a huge solvent peak outside the
    range does not raise the threshold) AND min_snr x noise.
    """
    y, rt = trace.corrected, trace.rt_min
    inside = (rt >= rt_min) & (rt <= rt_max)
    if y.size < 5 or not inside.any() or float(y[inside].max()) <= 0:
        return []
    threshold = max(min_height_pct / 100.0 * float(y[inside].max()), min_snr * trace.noise)
    peaks: list[Peak] = []
    for start, apex, end in _peak_windows(y, threshold, rule, trace.noise):
        apex_rt = refine_apex(rt, y, apex)
        if not (rt_min <= apex_rt <= rt_max):
            continue
        t0, t1 = float(rt[start]), float(rt[end])
        peaks.append(Peak(apex=apex, start=start, end=end, rt=apex_rt, t0=t0, t1=t1,
                          height=float(y[apex]), snr=float(y[apex] / trace.noise),
                          area=integrate_window(trace, t0, t1)))
    return peaks


def apex_in_window(trace: ProcessedTrace, t0: float, t1: float) -> tuple[int, bool]:
    """Highest scan inside [t0, t1] and whether it is a real local maximum.

    "Real" = not on the window edge (otherwise the window only catches the slope
    of a neighbouring peak).
    """
    rt, y = trace.rt_min, trace.corrected
    idx = np.flatnonzero((rt >= t0) & (rt <= t1))
    if idx.size < 3:
        return (int(idx[0]) if idx.size else int(np.searchsorted(rt, t0))), False
    k = int(idx[np.argmax(y[idx])])
    inside = idx[0] < k < idx[-1] and y[k] > y[k - 1] and y[k] >= y[k + 1]
    return k, bool(inside)

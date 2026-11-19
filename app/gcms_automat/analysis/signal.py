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
    """How a peak's integration window and its baseline are set (user parameters).

    The window ends, on each side, at the FIRST of:
      * the signal falls below max(end_pct % of the peak height, noise_sigma x noise),
      * the signal flattens: its slope falls below slope_pct % of the peak's
        steepest slope on that side (checked only after the steepest point).
        For a Gaussian, 5 % of the maximum slope is reached at 2.9 sigma, the same
        place as 1 % of the height; on a broad hump the peak ends at its own foot
        instead of running down the hump's flank,
      * the lowest point towards the neighbouring peak (valley).
    Area (see cluster_areas): peaks whose windows touch form a cluster; the area
    is measured above a straight line from the cluster start to its end, with
    perpendicular drops at the valleys inside. baseline_mode decides where the
    line starts/ends: "auto" = on the common baseline, unless the cluster ends
    clearly above it (above the end level, i.e. on a hump), then on the signal;
    "drop" = always on the common baseline (humps are counted in the peaks);
    "chord" = always on the signal at the window edges.
    """

    end_pct: float = 1.0
    noise_sigma: float = 1.0
    slope_pct: float = 5.0
    baseline_mode: str = "auto"
    lift_factor: float = 5.0

    def level(self, height: float, noise: float) -> float:
        """End level [counts]: max(end_pct % of the height, noise_sigma x noise)."""
        return max(self.end_pct / 100.0 * height, self.noise_sigma * noise)


# Scan interval the default baseline stiffness was tested with [s] (user's instrument).
REFERENCE_SCAN_S = 0.35


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
        # lambda acts per scan; the smoothing span of a 2nd-order penalty scales as
        # lambda^(1/4) scans, so lambda is scaled by (REFERENCE_SCAN_S / scan interval)^4
        # to mean the same stiffness IN TIME on instruments with other scan rates.
        scan_s = float(np.median(np.diff(rt_min))) * 60.0 if rt_min.size > 1 else REFERENCE_SCAN_S
        lam = 10.0 ** baseline_log_lambda * (REFERENCE_SCAN_S / scan_s) ** 4
        baseline = Baseline(np.arange(raw.size)).arpls(raw, lam=lam)[0]
    corrected = _smooth(raw - baseline, smooth_points)
    return ProcessedTrace(rt_min, raw, baseline, corrected, estimate_noise(raw - baseline))


def _side_end(y: np.ndarray, slope: np.ndarray, level: float, slope_pct: float) -> int:
    """Index (from 0 = apex) where one side of a peak ends; y/slope run from the apex
    outwards, up to the neighbouring apex; slope > 0 means falling away from the apex."""
    valley = int(np.argmin(y))
    candidates = [valley]
    below = np.flatnonzero(y[:valley + 1] < level)
    if below.size:
        candidates.append(int(below[0]))
    if slope_pct > 0 and valley > 1:
        steepest = int(np.argmax(slope[:valley + 1]))
        flat = np.flatnonzero(slope[steepest:valley + 1] < slope_pct / 100.0 * slope[steepest])
        if flat.size:
            candidates.append(steepest + int(flat[0]))
    return min(candidates)


def _peak_windows(y: np.ndarray, threshold: float, rule: WindowRule, noise: float) -> list[tuple[int, int, int]]:
    """(start, apex, end) scan indices of peaks with prominence >= threshold.

    Peaks are found with scipy.signal.find_peaks (prominence); window ends: see
    WindowRule. Neighbouring windows meet at most at the valley: never overlap.
    """
    apexes, _ = find_peaks(y, prominence=threshold)
    slope = np.gradient(y)  # [counts per scan]
    windows = []
    for k, apex in enumerate(apexes):
        level = rule.level(float(y[apex]), noise)
        # Right side: from the apex to the next apex (or the end of the run).
        stop = int(apexes[k + 1]) if k < apexes.size - 1 else y.size - 1
        end = apex + _side_end(y[apex:stop + 1], -slope[apex:stop + 1], level, rule.slope_pct)
        # Left side: from the apex back to the previous apex (or the start).
        stop = int(apexes[k - 1]) if k > 0 else 0
        start = apex - _side_end(y[stop:apex + 1][::-1], slope[stop:apex + 1][::-1], level, rule.slope_pct)
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


def _area_above(trace: ProcessedTrace, t0: float, t1: float, line) -> float:
    """Area of (corrected signal - line(t)) between t0 and t1 [counts * s].

    Trapezoidal rule; the window edges are linearly interpolated, so the area does
    not jump when an edge moves between two scans. Time converted min -> s.
    """
    if not t1 > t0:
        return 0.0
    rt, y = trace.rt_min, trace.corrected
    inside = (rt > t0) & (rt < t1)
    t = np.concatenate(([t0], rt[inside], [t1]))
    v = np.concatenate(([np.interp(t0, rt, y)], y[inside], [np.interp(t1, rt, y)]))
    return float(trapezoid(v - line(t), t * 60.0))


def cluster_areas(trace: ProcessedTrace, windows: list[tuple[float, float]], rule: WindowRule,
                  lines: list | None = None) -> list[float]:
    """Areas of several windows of ONE run, as a classical integrator does it [counts * s].

    Windows that touch (end of one = start of the next) form a cluster. Under a
    cluster a straight baseline runs from its start T0 to its end T1; inside, the
    peaks are separated by perpendicular drops at the shared edges. Line ends:
        a = signal(T) if baseline_mode == "chord", or ("auto" and signal(T) > lift_factor * level)
        a = 0         otherwise (= the common arPLS baseline)
    level = rule.level(highest point of the cluster, noise). So an isolated peak or
    a cluster that returns to the baseline is measured from the baseline, and one
    that ends on a hump is measured above the hump.
    If `lines` is a list, it receives for each window the baseline height at its
    start and end [counts] (to draw it in the chromatogram).
    """
    order = sorted(range(len(windows)), key=lambda i: windows[i][0])
    areas = [0.0] * len(windows)
    ends = [(0.0, 0.0)] * len(windows)
    rt, y = trace.rt_min, trace.corrected
    group: list[int] = []

    def close(group: list[int]) -> None:
        # This computes the cluster's baseline line and the area of each member.
        t_start, t_end = windows[group[0]][0], windows[group[-1]][1]
        inside = (rt >= t_start) & (rt <= t_end)
        height = float(y[inside].max()) if inside.any() else 0.0
        level = rule.level(height, trace.noise)

        def anchor(t: float) -> float:
            value = float(np.interp(t, rt, y))
            if rule.baseline_mode == "chord" or (rule.baseline_mode == "auto" and value > rule.lift_factor * level):
                return value
            return 0.0
        a0, a1 = anchor(t_start), anchor(t_end)
        span = (t_end - t_start) or 1.0
        line = lambda t: a0 + (a1 - a0) * (t - t_start) / span  # noqa: E731
        for i in group:
            areas[i] = _area_above(trace, windows[i][0], windows[i][1], line)
            ends[i] = (float(line(windows[i][0])), float(line(windows[i][1])))

    for i in order:
        if group and windows[i][0] > windows[group[-1]][1] + 1e-6:
            close(group)
            group = []
        group.append(i)
    if group:
        close(group)
    if lines is not None:
        lines[:] = ends
    return areas


def integrate_window(trace: ProcessedTrace, t0: float, t1: float, rule: WindowRule = WindowRule()) -> float:
    """Area of a single window (a cluster of one), see cluster_areas [counts * s]."""
    return cluster_areas(trace, [(t0, t1)], rule)[0] if t1 > t0 else 0.0


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
        peaks.append(Peak(apex=apex, start=start, end=end, rt=apex_rt, t0=float(rt[start]),
                          t1=float(rt[end]), height=float(y[apex]), snr=float(y[apex] / trace.noise), area=0.0))
    # This integrates all peaks of the run together (clusters share one baseline line).
    for peak, area in zip(peaks, cluster_areas(trace, [(p.t0, p.t1) for p in peaks], rule)):
        peak.area = area
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

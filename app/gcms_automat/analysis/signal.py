"""Chromatogram processing: baseline, smoothing, noise, peak picking, integration.

All numerical work uses established library functions:
  * scipy.ndimage.minimum_filter1d / uniform_filter1d  (rolling-minimum baseline)
  * scipy.signal.savgol_filter      (Savitzky & Golay 1964, Anal. Chem. 36, 1627)
  * scipy.signal.find_peaks / peak_widths
  * scipy.stats.median_abs_deviation (robust noise estimate)
  * scipy.integrate.trapezoid       (trapezoidal rule)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.integrate import trapezoid
from scipy.ndimage import median_filter, minimum_filter1d, uniform_filter1d
from scipy.signal import find_peaks, peak_widths, savgol_filter
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


def scans_for_minutes(rt_min: np.ndarray, minutes: float) -> int:
    """Convert a time span [min] to an odd number of scans (at least 3)."""
    # This uses the median scan interval, robust against single irregular scans.
    step = float(np.median(np.diff(rt_min))) if rt_min.size > 1 else 1.0
    n = max(3, int(round(minutes / step)))
    return n if n % 2 else n + 1


def estimate_noise(y: np.ndarray) -> float:
    """Noise standard deviation from point-to-point differences.

    sigma = MAD(diff(y)) * 1.4826 / sqrt(2)   [same unit as y]
    The MAD (scaled to a normal distribution by scipy, scale="normal") ignores
    peaks; differences remove slow drift; dividing by sqrt(2) converts the spread
    of a difference of two noisy points back to the spread of one point.
    """
    if y.size < 3:
        return 1e-9
    sigma = float(median_abs_deviation(np.diff(y), scale="normal")) / np.sqrt(2.0)
    return max(sigma, 1e-9)


# Peaks interpolated under the baseline must have at least this S/N. 10 = the usual
# limit of quantification convention (ICH Q2): only certain peaks, never noise.
BASELINE_PEAK_SNR = 10.0


# Region masked out under a peak for the baseline, in half widths at half maximum.
# A Gaussian at 5 HWHM (5.9 sigma) is below 1e-7 of its height: fully at baseline.
MASK_HALF_WIDTHS = 5.0

# Max. window extent from the apex, in half widths at half maximum (HWHM). For a
# Gaussian peak 3 HWHM = 3.5 sigma, which contains > 99.9 % of the area.
WINDOW_HALF_WIDTHS = 3.0


def _smooth(y: np.ndarray, smooth_points: int) -> np.ndarray:
    """Savitzky-Golay smoothing (2nd order); window forced odd; <3 = no smoothing."""
    if smooth_points >= 3 and y.size > smooth_points:
        points = smooth_points if smooth_points % 2 else smooth_points + 1
        return savgol_filter(y, window_length=points, polyorder=2, mode="interp")
    return y.copy()


def _peak_windows(y: np.ndarray, threshold: float) -> list[tuple[int, int, int]]:
    """(start, apex, end) scan indices of peaks with prominence >= threshold.

    A window runs from where the signal falls to 5 % of the prominence
    (scipy.signal.peak_widths, rel_height 0.95), but
      * at most WINDOW_HALF_WIDTHS x the half width at half maximum from the apex
        on each side (otherwise, for small peaks, the window wanders off into the
        noise, which keeps the signal above the 5 % level by chance), and
      * never past the lowest point between the peak and a neighbouring peak,
        so windows never overlap.
    """
    apexes, props = find_peaks(y, prominence=threshold)
    if apexes.size == 0:
        return []
    base = (props["prominences"], props["left_bases"], props["right_bases"])
    _, _, left, right = peak_widths(y, apexes, rel_height=0.95, prominence_data=base)
    _, _, left_half, right_half = peak_widths(y, apexes, rel_height=0.5, prominence_data=base)
    windows = []
    for k, apex in enumerate(apexes):
        # This limits the window by the peak's own shape (left and right separately,
        # so a tailing peak keeps its longer tail).
        left_limit = apex - WINDOW_HALF_WIDTHS * (apex - left_half[k])
        right_limit = apex + WINDOW_HALF_WIDTHS * (right_half[k] - apex)
        start = int(np.floor(max(left[k], left_limit)))
        end = int(np.ceil(min(right[k], right_limit)))
        if k > 0:
            prev = apexes[k - 1]
            start = max(start, int(prev + np.argmin(y[prev:apex + 1])))
        if k < apexes.size - 1:
            nxt = apexes[k + 1]
            end = min(end, int(apex + np.argmin(y[apex:nxt + 1])))
        end = min(end, y.size - 1)
        if end - start >= 2:
            windows.append((start, int(apex), end))
    return windows


def _threshold(y: np.ndarray, noise: float, min_height_pct: float, min_snr: float) -> float:
    """Peak prominence threshold: both % of the largest signal AND S/N must be met."""
    return max(min_height_pct / 100.0 * float(np.max(y, initial=0.0)), min_snr * noise)


def process_trace(rt_min: np.ndarray, raw: np.ndarray, baseline_window_min: float,
                  smooth_points: int, min_height_pct: float = 0.2, min_snr: float = 10.0) -> ProcessedTrace:
    """Subtract the baseline and smooth the chromatogram (two passes).

    Pass 1 (only to find where the peaks are): rolling minimum, then rolling mean
        of it. This lies at the LOWER edge of the noise, so the rolling median of
        what is left is added (peaks are a minority of the points in a window, so
        the median is the middle of the noise).
    Pass 2 (the baseline actually used): the raw signal around every clear peak
        found in pass 1 (apex +- MASK_HALF_WIDTHS half widths, where the peak has
        fully returned to the baseline) is replaced by straight lines between the
        surrounding peak-free points; the rolling mean of this peak-free signal is
        the baseline. It runs through the MIDDLE of the noise, so small peaks are
        not inflated by the noise offset (with the pass-1 baseline a peak 10x above
        the noise came out ~70 % too large in the tests).
    Only clear peaks (S/N >= BASELINE_PEAK_SNR) are masked: with a low limit,
    noise maxima would be cut out too and the baseline would sink again.
    The corrected signal is not clipped at 0: noise is symmetric and cancels out.
    """
    window = scans_for_minutes(rt_min, baseline_window_min)

    # ---- Pass 1: rough baseline, then where the clear peaks are ----
    rough = uniform_filter1d(minimum_filter1d(raw, size=window, mode="nearest"), size=window, mode="nearest")
    rough = rough + median_filter(raw - rough, size=window, mode="nearest")
    first = _smooth(raw - rough, smooth_points)
    # Noise is estimated from the UNSMOOTHED signal: smoothing makes neighbouring
    # points similar, so the point-to-point estimate would come out too low.
    snr = max(min_snr, BASELINE_PEAK_SNR)
    mask = _peak_mask(first, _threshold(first, estimate_noise(raw - rough), min_height_pct, snr))

    # ---- Pass 2: interpolate under the masked peaks, then rolling mean ----
    index = np.arange(raw.size)
    peak_free = raw.astype(float)
    if mask.any() and not mask.all():
        peak_free = np.interp(index, index[~mask], _smooth(raw, smooth_points)[~mask])
    baseline = uniform_filter1d(peak_free, size=window, mode="nearest")
    corrected = _smooth(raw - baseline, smooth_points)
    return ProcessedTrace(rt_min, raw, baseline, corrected, estimate_noise(raw - baseline))


def _peak_mask(y: np.ndarray, threshold: float) -> np.ndarray:
    """True for scans within MASK_HALF_WIDTHS half widths of a clear peak's apex."""
    mask = np.zeros(y.size, dtype=bool)
    apexes, props = find_peaks(y, prominence=threshold)
    if apexes.size == 0:
        return mask
    base = (props["prominences"], props["left_bases"], props["right_bases"])
    _, _, left_half, right_half = peak_widths(y, apexes, rel_height=0.5, prominence_data=base)
    for apex, lh, rh in zip(apexes, left_half, right_half):
        start = int(np.floor(apex - MASK_HALF_WIDTHS * (apex - lh)))
        end = int(np.ceil(apex + MASK_HALF_WIDTHS * (rh - apex)))
        mask[max(start, 0):min(end, y.size - 1) + 1] = True
    return mask


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
               rt_min: float, rt_max: float) -> list[Peak]:
    """Find peaks in the corrected chromatogram (thresholds and windows: see _peak_windows)."""
    y = trace.corrected
    if y.size < 5 or float(y.max()) <= 0:
        return []
    peaks: list[Peak] = []
    for start, apex, end in _peak_windows(y, _threshold(y, trace.noise, min_height_pct, min_snr)):
        rt = refine_apex(trace.rt_min, y, apex)
        if not (rt_min <= rt <= rt_max):
            continue
        t0, t1 = float(trace.rt_min[start]), float(trace.rt_min[end])
        peaks.append(Peak(apex=apex, start=start, end=end, rt=rt, t0=t0, t1=t1,
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

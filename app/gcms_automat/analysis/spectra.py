"""Mass spectra of peaks and their similarity."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .cdf import Run


@dataclass(frozen=True)
class MzAxis:
    """Common nominal m/z axis for comparing spectra of different runs."""

    lo: int
    hi: int

    @property
    def values(self) -> np.ndarray:
        return np.arange(self.lo, self.hi + 1)

    @property
    def size(self) -> int:
        return self.hi - self.lo + 1

    @classmethod
    def covering(cls, runs: list[Run]) -> "MzAxis":
        """Smallest axis that contains the m/z range of every run."""
        lo = min(r.mz_min for r in runs)
        hi = max(r.mz_min + r.spectra.shape[1] - 1 for r in runs)
        return cls(lo, hi)


def _rows_mean(run: Run, scans: list[int], axis: MzAxis) -> np.ndarray:
    """Mean spectrum of the given scans, placed on the common m/z axis [counts]."""
    out = np.zeros(axis.size)
    if not scans:
        return out
    block = np.asarray(run.spectra[scans].mean(axis=0)).ravel()
    offset = run.mz_min - axis.lo
    out[offset:offset + block.size] = block
    return out


def peak_spectrum(run: Run, apex: int, start: int, end: int, axis: MzAxis,
                  background_scans: int = 3) -> np.ndarray:
    """Background-subtracted spectrum at a peak apex, scaled to 100 % [%].

    spectrum = mean(scans apex-1 .. apex+1) - mean(background scans)
    Background = up to `background_scans` scans just before the window start and
    just after the window end (0 = no background subtraction). Negative values are
    set to 0; the result is scaled so the most intense ion is 100.
    """
    n = run.n_scans
    # This averages 3 scans around the apex (less noise than a single scan).
    top = list(range(max(apex - 1, 0), min(apex + 2, n)))
    # This averages the scans just outside the integration window as background.
    before = list(range(max(start - background_scans, 0), max(start, 0) + 1)) if background_scans > 0 else []
    after = list(range(min(end, n - 1), min(end + background_scans + 1, n))) if background_scans > 0 else []
    background = sorted(set(before + after) - set(top))
    spectrum = _rows_mean(run, top, axis) - _rows_mean(run, background, axis)
    spectrum = np.clip(spectrum, 0.0, None)
    peak = float(spectrum.max())
    return spectrum / peak * 100.0 if peak > 0 else spectrum


def similarity(a: np.ndarray, b: np.ndarray, axis: MzAxis,
               intensity_power: float = 0.5, mz_power: float = 1.0) -> float:
    """Spectral similarity 0..1: cosine of weighted spectra.

    w(m) = I(m)^a * m^b ;  similarity = sum(wa*wb) / (|wa| * |wb|)
    1 = identical relative spectra, 0 = no common ions.
    """
    mz = axis.values.astype(float)
    wa = np.power(a, intensity_power) * np.power(mz, mz_power)
    wb = np.power(b, intensity_power) * np.power(mz, mz_power)
    denominator = float(np.linalg.norm(wa) * np.linalg.norm(wb))
    return float(np.dot(wa, wb) / denominator) if denominator > 0 else 0.0


def top_ions(spectrum: np.ndarray, axis: MzAxis, count: int = 5,
             min_percent: float = 1.0) -> list[tuple[int, float]]:
    """Most intense ions as (m/z, relative intensity %), strongest first.

    Ions below `min_percent` % are left out (they would show as "0 %").
    """
    order = np.argsort(-spectrum, kind="stable")[:count]
    return [(int(axis.lo + i), float(spectrum[i])) for i in order if spectrum[i] >= min_percent]


def base_ion(spectrum: np.ndarray, axis: MzAxis) -> int | None:
    """m/z of the most intense ion (the 100 % ion), None for an empty spectrum."""
    if not spectrum.size or spectrum.max() <= 0:
        return None
    return int(axis.lo + int(np.argmax(spectrum)))


def is_co2_noise(spectrum: np.ndarray, axis: MzAxis, ion_pct: float = 10.0, min_other_ions: int = 3) -> bool:
    """CO2 noise: base ion m/z 44 and fewer than `min_other_ions` other ions above `ion_pct` %."""
    if base_ion(spectrum, axis) != 44:
        return False
    others = np.flatnonzero(spectrum >= ion_pct)
    return int(np.sum(axis.lo + others != 44)) < min_other_ions

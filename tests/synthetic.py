"""Synthetic GC-MS runs with exactly known peaks (for tests; no real data needed)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import sparse

from gcms_automat.analysis.cdf import Run

SCAN_S = 0.35                  # scan interval [s] (like the user's instrument)
MZ_LO, MZ_HI = 35, 300         # nominal m/z range of the synthetic runs


@dataclass
class Compound:
    """A compound: relative spectrum {m/z: %} with the base ion at 100."""

    spectrum: dict[int, float]

    @property
    def tic_factor(self) -> float:
        """TIC height / base-ion height = sum of relative intensities / 100."""
        return sum(self.spectrum.values()) / 100.0


# Distinct spectra (no ion in common between A, B and C).
A = Compound({43: 100, 57: 60, 71: 30})
B = Compound({91: 100, 92: 60, 65: 10})
C = Compound({105: 100, 77: 80, 51: 30})
CO2 = Compound({44: 100})


def gaussian_area(height: float, sigma_min: float, compound: Compound) -> float:
    """Exact TIC area of a Gaussian peak [counts * s].

    area = H * S * sigma * sqrt(2 pi) * 60 ; H = base-ion height [counts],
    S = TIC factor of the spectrum, sigma [min], * 60 converts min -> s.
    """
    return height * compound.tic_factor * sigma_min * math.sqrt(2 * math.pi) * 60.0


def make_run(name: str, peaks: list[tuple[Compound, float, float, float]], minutes: float = 10.0,
             noise: float = 20.0, baseline: float = 1000.0, seed: int = 0) -> Run:
    """Build a run. peaks: (compound, rt [min], base-ion height [counts], sigma [min]).

    A constant baseline with Gaussian noise (sd `noise` counts) is put on m/z 40
    (like argon); it is removed by the baseline correction.
    """
    rng = np.random.default_rng(seed)
    rt = np.arange(0.0, minutes, SCAN_S / 60.0)
    n_mz = MZ_HI - MZ_LO + 1
    dense = np.zeros((rt.size, n_mz))
    # This adds the background ion and the peaks.
    dense[:, 40 - MZ_LO] = baseline + rng.normal(0.0, noise, rt.size)
    for compound, centre, height, sigma in peaks:
        shape = height * np.exp(-0.5 * ((rt - centre) / sigma) ** 2)
        for mz, rel in compound.spectrum.items():
            dense[:, mz - MZ_LO] += shape * rel / 100.0
    dense = np.clip(dense, 0.0, None)
    return Run(name=name, rt_min=rt, mz_min=MZ_LO, spectra=sparse.csr_matrix(dense))


def alkane_compound(carbons: int) -> Compound:
    """Simplified n-alkane spectrum with its molecular ion M+ = 14 n + 2 at 2 %."""
    return Compound({57: 100, 43: 80, 71: 55, 85: 30, 14 * carbons + 2: 2.0})

"""Reading GC-MS runs from ANDI/AIA netCDF files (.CDF).

Format: ASTM E2077 "Analytical Data Interchange Protocol for Mass Spectrometric
Data" (ANDI-MS / AIA). Exported e.g. by Agilent ChemStation (File -> Export Data
to AIA Format). The file is netCDF-3 "classic", read with scipy.io.netcdf_file.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.io import netcdf_file


# Plausible nominal m/z range of GC-MS data (EI quadrupoles scan ~10-1050).
MZ_LIMITS = (1, 2000)


@dataclass
class Run:
    """One GC-MS run (one injected sample), with nominal-mass spectra.

    rt_min      retention time of each scan [min], shape (n_scans,)
    mz_min      smallest nominal m/z stored (column 0 of `spectra`)
    spectra     sparse matrix (n_scans x n_mz), intensity [counts] per nominal m/z
    """

    name: str
    rt_min: np.ndarray
    mz_min: int
    spectra: sparse.csr_matrix
    title: str = ""

    @property
    def n_scans(self) -> int:
        return int(self.rt_min.size)

    @property
    def mz_values(self) -> np.ndarray:
        """Nominal m/z of each column of `spectra`."""
        return np.arange(self.mz_min, self.mz_min + self.spectra.shape[1])

    def tic(self) -> np.ndarray:
        """Total ion current: sum of all intensities in each scan [counts]."""
        return np.asarray(self.spectra.sum(axis=1)).ravel()


def read_cdf(source, name: str) -> Run:
    """Read an AIA .CDF file (path or bytes) into a Run.

    Masses are rounded to nominal m/z (e.g. 43.1 -> 43); intensities that fall on
    the same nominal mass within one scan are summed.
    """
    # This opens the file from bytes (upload) or from a path; mmap=False copies
    # the data, so the file can be closed right away.
    handle = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    try:
        nc = netcdf_file(handle, "r", mmap=False)
    except Exception as exc:  # scipy raises TypeError/ValueError for non-netCDF files
        raise ValueError("Soubor není platný AIA/netCDF (.CDF).") from exc

    # This reads the ANDI-MS variables we need (names fixed by ASTM E2077).
    try:
        variables = nc.variables
        scan_time_s = np.asarray(variables["scan_acquisition_time"].data, dtype=float)
        point_count = np.asarray(variables["point_count"].data, dtype=np.int64)
        masses = np.asarray(variables["mass_values"].data, dtype=float)
        intensities = np.asarray(variables["intensity_values"].data, dtype=float)
        title = _attribute_text(nc, "experiment_title")
    except KeyError as exc:
        raise ValueError(f"V souboru chybí proměnná {exc.args[0]} (není to GC-MS AIA soubor?).") from exc
    finally:
        nc.close()

    # This checks that the per-scan point counts match the stored points.
    if point_count.sum() != masses.size or masses.size != intensities.size:
        raise ValueError("Poškozený soubor: počty bodů ve skenech nesedí s daty.")
    if scan_time_s.size == 0 or masses.size == 0:
        raise ValueError("Soubor neobsahuje žádné skeny.")
    # This rejects damaged values (they would break the m/z axis or the time axis).
    if not (np.all(np.isfinite(masses)) and np.all(np.isfinite(intensities)) and np.all(np.isfinite(scan_time_s))):
        raise ValueError("Poškozený soubor: neplatné číslo (NaN/nekonečno) v datech.")
    if masses.min() < MZ_LIMITS[0] or masses.max() > MZ_LIMITS[1]:
        raise ValueError(f"Hodnoty m/z mimo rozsah {MZ_LIMITS[0]}–{MZ_LIMITS[1]} (poškozený soubor?).")
    if np.any(np.diff(scan_time_s) <= 0):
        raise ValueError("Časy skenů nejsou rostoucí (poškozený soubor?).")

    # This builds a sparse scans x nominal-m/z matrix (duplicates are summed).
    nominal = np.rint(masses).astype(np.int64)
    mz_min = int(nominal.min())
    mz_max = int(nominal.max())
    scan_index = np.repeat(np.arange(scan_time_s.size), point_count)
    matrix = sparse.coo_matrix(
        (intensities, (scan_index, nominal - mz_min)),
        shape=(scan_time_s.size, mz_max - mz_min + 1),
    ).tocsr()
    matrix.sum_duplicates()

    # Retention time: seconds -> minutes.
    return Run(name=name, rt_min=scan_time_s / 60.0, mz_min=mz_min, spectra=matrix, title=title)


def _attribute_text(nc: netcdf_file, key: str) -> str:
    """Read a global text attribute, '' if missing."""
    value = getattr(nc, "_attributes", {}).get(key, b"")
    if isinstance(value, bytes):
        return value.decode("latin-1", "replace").strip("\x00 ").strip()
    return str(value)


def write_cdf(path, rt_min: np.ndarray, scans: list[tuple[np.ndarray, np.ndarray]], title: str = "") -> None:
    """Write a minimal AIA .CDF file (used by the tests to create synthetic runs).

    scans: list of (masses, intensities) per scan, same length as rt_min.
    """
    # This writes only the variables read_cdf() needs, in the ANDI-MS layout.
    counts = np.array([len(m) for m, _ in scans], dtype=np.int32)
    masses = np.concatenate([np.asarray(m, dtype=np.float32) for m, _ in scans])
    values = np.concatenate([np.asarray(v, dtype=np.float32) for _, v in scans])
    with netcdf_file(path, "w", version=1) as nc:
        nc.experiment_title = title.encode("latin-1", "replace")
        nc.createDimension("scan_number", len(scans))
        nc.createDimension("point_number", masses.size)
        nc.createVariable("scan_acquisition_time", "d", ("scan_number",))[:] = np.asarray(rt_min) * 60.0
        nc.createVariable("point_count", "i", ("scan_number",))[:] = counts
        nc.createVariable("mass_values", "f", ("point_number",))[:] = masses
        nc.createVariable("intensity_values", "f", ("point_number",))[:] = values

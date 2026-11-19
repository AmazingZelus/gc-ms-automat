"""CSV export with a provenance header.

Every export written by the application MUST go through write_csv_export(),
so that every file says which program and which version produced it, and when.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

import pandas as pd

from . import APP_NAME, __version__

# This lists the scientific libraries whose versions are written into each export.
# Library versions matter for reproducibility (results can change between versions).
RECORDED_LIBRARIES = ("numpy", "scipy", "pandas", "statsmodels", "scikit-learn", "pybaselines")


@dataclass(frozen=True)
class CsvFormat:
    """How numbers and columns are separated in the CSV file."""

    key: str
    label: str
    separator: str
    decimal: str


# These are the CSV formats the user can choose in the UI.
# Czech Excel expects ";" between columns and "," as the decimal mark;
# Python, R and English Excel expect "," between columns and "." as decimal mark.
CSV_FORMATS = {
    "cz": CsvFormat("cz", "Excel (česky): oddělovač ; a desetinná čárka", ";", ","),
    "intl": CsvFormat("intl", "Mezinárodní (Python, R): oddělovač , a desetinná tečka", ",", "."),
}
DEFAULT_CSV_FORMAT = "cz"


def library_versions() -> dict[str, str]:
    """Return installed versions of the recorded libraries (without importing them)."""
    # This reads versions from package metadata, which is fast (no heavy imports).
    versions = {}
    for name in RECORDED_LIBRARIES:
        try:
            versions[name] = package_version(name)
        except PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def build_header_lines(processed_at: datetime, csv_format: CsvFormat) -> list[str]:
    """Build the provenance header (comment lines starting with '#')."""
    # This builds the header. Keys are in English so that any tool can parse them.
    # Values never contain the column separator, so the header stays in column A.
    lines = [
        f"# app: {APP_NAME}",
        f"# version: {__version__}",
        f"# processed_at: {processed_at.isoformat(timespec='seconds')}",
        f"# python: {platform.python_version()}",
    ]
    lines += [f"# lib.{name}: {ver}" for name, ver in library_versions().items()]
    lines.append(f"# csv_format: {csv_format.key}")
    return lines


def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    """Return folder/stem+suffix, adding _2, _3 ... if the file already exists."""
    # This prevents overwriting an earlier export with the same timestamp.
    candidate = folder / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def write_csv_export(
    table: pd.DataFrame,
    folder: Path,
    name_prefix: str,
    csv_format_key: str = DEFAULT_CSV_FORMAT,
    now: datetime | None = None,
) -> Path:
    """Write `table` as CSV with the provenance header and return the file path."""
    # This picks the CSV format (unknown keys are an error, not silently replaced).
    if csv_format_key not in CSV_FORMATS:
        raise ValueError(f"Unknown CSV format: {csv_format_key!r}")
    csv_format = CSV_FORMATS[csv_format_key]

    # This takes the local time WITH the UTC offset, e.g. 2026-11-19T10:15:03+01:00.
    # (A time that already has a time zone, e.g. from tests, is kept unchanged.)
    if now is not None and now.tzinfo is not None:
        processed_at = now
    else:
        processed_at = (now or datetime.now()).astimezone()

    # This creates the output folder and a unique file name with a timestamp.
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{name_prefix}_{processed_at.strftime('%Y%m%d_%H%M%S')}"
    path = unique_path(folder, stem, ".csv")

    # This writes the header and then the table.
    # Encoding "utf-8-sig" (UTF-8 with BOM) makes Excel show Czech characters correctly.
    header = "\n".join(build_header_lines(processed_at, csv_format)) + "\n"
    body = table.to_csv(sep=csv_format.separator, decimal=csv_format.decimal,
                        index=False, lineterminator="\n")
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write(header)
        handle.write(body)
    return path


def make_test_table() -> pd.DataFrame:
    """Small synthetic table with known values, used by the 'Export test' button."""
    # This creates x = 0..4 and two columns with exactly known results:
    # y = x^2 (dimensionless) and z = x / 2 (dimensionless, to show decimals).
    x = pd.Series(range(5), name="x")
    return pd.DataFrame({"x": x, "x_squared": x ** 2, "x_half": x / 2})

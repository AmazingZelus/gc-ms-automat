"""Export of the result table to Excel (.xlsx), written with openpyxl.

Sheets (the user chooses which):
  * "Info" (always first): app name, version, date/time with time zone, data
    files, alkanes, ALL parameters, the integration methods with their standard
    English names and citations, library versions.
  * "Plochy (ND)", "Plochy (0)", "Plochy (prázdné)", "Plochy (<vlastní text>)":
    the same table, missing values marked differently on each sheet.
  * Replicate means: "Průměry", "Průměr ± SD", "Průměr a SD" (separate columns).
    A mean is given only if the compound was found in ALL replicates of the group,
    otherwise it is marked as missing (the analyst's rule).
  * "Původ hodnot": for every cell how it was obtained (window, S/N, similarity).
"""

from __future__ import annotations

import math
import os
import platform
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import APP_NAME, __version__
from .analysis.params import PARAMETERS, AnalysisParams
from .analysis.retention import Alkane
from .analysis.table import STATUS_LABELS, Analysis, Row, replicate_group, view_filter
from .export import library_versions, unique_path

# ---- This lists the possible markings of a missing value (one sheet each) ----
MISSING_MARKERS = {
    "nd": ("ND", "ND"),        # key: (sheet suffix, cell value)
    "zero": ("0", 0),
    "blank": ("prázdné", None),
}
MEAN_FORMATS = ("mean", "mean_pm_sd", "mean_sd_columns")
CUSTOM_TEXT_MAX = 20
# Characters Excel does not allow in sheet names.
SHEET_NAME_FORBIDDEN = set('[]:*?/\\')

HEADER_FONT = Font(bold=True)
TITLE_FONT = Font(bold=True, size=13)
POOR_FILL = PatternFill("solid", fgColor="FDE8E6")   # same light red as in the app


@dataclass
class ExportOptions:
    """What the user ticked in the export dialog."""

    markers: list[str] = field(default_factory=lambda: ["nd"])   # nd | zero | blank | custom
    custom_text: str = ""
    mean_formats: list[str] = field(default_factory=list)        # subset of MEAN_FORMATS
    mean_missing: str = "nd"                                      # how a missing mean is marked
    only_visible: bool = True
    provenance: bool = True

    def validate(self) -> None:
        """Raise ValueError with a Czech message if the choice cannot be exported."""
        allowed = set(MISSING_MARKERS) | {"custom"}
        if not self.markers and not self.mean_formats:
            raise ValueError("Vyber aspoň jeden list s plochami nebo s průměry.")
        if any(m not in allowed for m in self.markers) or self.mean_missing not in allowed:
            raise ValueError("Neznámé označení chybějící hodnoty.")
        if any(f not in MEAN_FORMATS for f in self.mean_formats):
            raise ValueError("Neznámý formát průměrů.")
        if "custom" in self.markers or self.mean_missing == "custom":
            text = self.custom_text.strip()
            if not text or len(text) > CUSTOM_TEXT_MAX or ILLEGAL_CHARACTERS_RE.search(text):
                raise ValueError(f"Vlastní text pro chybějící hodnotu: 1–{CUSTOM_TEXT_MAX} běžných znaků.")
            if text.upper() == "ND" or text == "0":
                raise ValueError(f"Pro „{text}“ použij zaškrtávátko {text} (vlastní text „{text}“ by byl text, ne stejná hodnota).")


# ---------------------------------------------------------------- methods, citations
# This describes HOW the numbers were obtained: (step, standard English name,
# implementation, citation). Citations only where we are sure of them.
def methods_table(params: AnalysisParams) -> list[tuple[str, str, str, str]]:
    # Note: NOT "valley-to-valley" - that name means a baseline redrawn through every
    # valley (each peak its own segment); here one straight line spans a whole cluster
    # of touching peaks and the peaks are separated by perpendicular drops.
    cluster_line = ("straight baseline from the start to the end of each cluster of touching peaks, "
                    "peaks separated by perpendicular drops (drop-line)")
    baseline_mode = {
        "auto": "perpendicular drop (drop-line) to the common baseline; when a cluster ends on a hump "
                "(edge > lift factor x end level): " + cluster_line,
        "drop": "perpendicular drop (drop-line) to the common baseline",
        "chord": cluster_line,
    }[params.integration_baseline]
    return [
        ("Formát dat", "ANDI-MS / AIA netCDF (ASTM E2077)", "scipy.io.netcdf_file", ""),
        ("Baseline chromatogramu", "asymmetrically reweighted penalized least squares (arPLS)",
         f"pybaselines Baseline.arpls, lambda = 10^{params.baseline_log_lambda:g} (scaled to scan interval)",
         "Baek S.-J., Park A., Ahn Y.-J., Choo J. (2015) Analyst 140, 250–257"),
        ("Vyhlazení", "Savitzky–Golay filter (2nd order polynomial)",
         f"scipy.signal.savgol_filter, {params.smooth_points} points",
         "Savitzky A., Golay M. J. E. (1964) Anal. Chem. 36, 1627–1639"),
        ("Šum (pro S/N)", "robust noise SD: MAD of first differences × 1.4826 / sqrt(2)",
         "scipy.stats.median_abs_deviation(scale='normal') of the unsmoothed baseline-corrected TIC", ""),
        ("Detekce píků", "local maxima with a prominence threshold",
         f"scipy.signal.find_peaks; prominence >= max({params.min_height_pct:g} % of largest, S/N {params.min_snr:g})", ""),
        ("Začátek a konec píku", "level threshold and slope criterion (peak start/end detection)",
         f"this application: first of signal < max({params.window_end_pct:g} % height, "
         f"{params.window_end_noise_sigma:g} sigma), slope < {params.window_end_slope_pct:g} % of max slope, valley", ""),
        ("Dělení sousedních píků", "perpendicular drop (drop-line) at the valley", "this application", ""),
        ("Baseline pod píkem", baseline_mode,
         f"this application, mode '{params.integration_baseline}', lift factor {params.integration_lift_factor:g}", ""),
        ("Výpočet plochy", "trapezoidal rule (numerical integration)",
         "scipy.integrate.trapezoid; area in counts × s on the baseline-corrected TIC", ""),
        ("Spektrum píku", "apex spectrum (mean of 3 scans) with background subtraction",
         f"this application; background {params.spectrum_background_scans} scans each side", ""),
        ("Shoda spekter", "weighted cosine similarity (dot product)",
         f"intensity^{params.weight_intensity_power:g} × (m/z)^{params.weight_mz_power:g}",
         "váhy: TODO ověřit zdroj (Stein S. E., Scott D. R. (1994) J. Am. Soc. Mass Spectrom. 5, 859–866 studují váhy tohoto typu)"),
        ("Zarovnání mezi záznamy", "retention-time window + spectral similarity (greedy clustering)",
         f"this application; RT ± {params.rt_tolerance_min:g} min, similarity >= {params.min_similarity:g}", ""),
        ("Retenční index", "linear (temperature-programmed) retention index",
         "this application", "van den Dool H., Kratz P. D. (1963) J. Chromatogr. 11, 463–471"),
        ("Průměr a SD paralelek", "arithmetic mean; sample standard deviation (n − 1)",
         "numpy.mean, numpy.std(ddof=1)", ""),
        ("Zaokrouhlení „průměr ± SD“", "SD to 2 significant digits, mean to the same decimal place",
         "this application (text cells)", ""),
    ]


# This lists the libraries to cite: (package name for version lookup, citation).
LIBRARY_CITATIONS = [
    ("numpy", "Harris C. R. et al. (2020) Array programming with NumPy. Nature 585, 357–362"),
    ("scipy", "Virtanen P. et al. (2020) SciPy 1.0: fundamental algorithms for scientific computing "
              "in Python. Nature Methods 17, 261–272"),
    ("pandas", "McKinney W. (2010) Data structures for statistical computing in Python. "
               "Proc. 9th Python in Science Conference (SciPy 2010)"),
    ("pybaselines", "Erb D. pybaselines: A Python library of algorithms for the baseline correction of "
                    "experimental data. https://doi.org/10.5281/zenodo.5608581"),
    ("openpyxl", "Gazoni E., Clark C., openpyxl (software)"),
    ("flask", "(uživatelské rozhraní, výpočty neovlivňuje)"),
    ("waitress", "(uživatelské rozhraní, výpočty neovlivňuje)"),
]


# ---------------------------------------------------------------- helpers
def safe_text(cell, value: str) -> None:
    """Write text so Excel never treats it as a formula (=, +, -, @ at the start).

    Control characters that an .xlsx cannot hold (e.g. from pasted text) are removed.
    """
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)
    cell.value = value
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        cell.data_type = "s"


def sheet_title(base: str, used: set[str]) -> str:
    """A valid, unique Excel sheet name (max 31 characters, no []:*?/\\)."""
    clean = "".join("_" if ch in SHEET_NAME_FORBIDDEN else ch for ch in base).strip("' ")[:31] or "List"
    title, n = clean, 2
    while title.lower() in used:
        suffix = f" ({n})"
        title, n = clean[:31 - len(suffix)] + suffix, n + 1
    used.add(title.lower())
    return title


def format_mean_sd(mean: float, sd: float | None) -> str:
    """'mean ± SD' text: SD rounded to 2 significant digits, mean to the same place.

    decimals = 1 - floor(log10(SD)); e.g. SD 45 678 -> 46 000 and mean to thousands,
    SD 0.0123 -> 0.012 and mean to 3 decimals. Czech style: space thousands
    separator, decimal comma.
    """
    def fmt(value: float, decimals: int) -> str:
        text = f"{round(value, decimals):,.{max(decimals, 0)}f}"
        return text.replace(",", " ").replace(".", ",")
    if sd is None or not math.isfinite(sd) or sd <= 0:
        return fmt(mean, 0)
    decimals = 1 - int(math.floor(math.log10(sd)))
    # Rounding can carry into the next decade (99.6 -> 100): recount from the rounded SD.
    rounded = round(sd, decimals)
    decimals = 1 - int(math.floor(math.log10(rounded)))
    return f"{fmt(mean, decimals)} ± {fmt(sd, decimals)}"


def replicate_stats(values: list[float | None]) -> tuple[float | None, float | None]:
    """(mean, SD) of the replicates; (None, None) if any replicate is missing.

    mean = sum(x) / n ; SD = sqrt(sum((x - mean)^2) / (n - 1)) (numpy, ddof=1);
    SD is None for a single replicate.
    """
    if not values or any(v is None for v in values):
        return None, None
    data = np.asarray(values, dtype=float)
    return float(np.mean(data)), (float(np.std(data, ddof=1)) if data.size > 1 else None)


def _autosize(ws, widths: dict[int, float] | None = None) -> None:
    """Set column widths from the content (approximate, max 45 characters)."""
    for col_cells in ws.columns:
        idx = col_cells[0].column
        longest = max((len(str(c.value)) for c in col_cells if c.value is not None), default=6)
        ws.column_dimensions[get_column_letter(idx)].width = (widths or {}).get(idx, min(max(8, longest + 2), 45))


# ---------------------------------------------------------------- sheets
ROW_COLUMNS = ["ID", "RT [min]", "RI", "Top ionty m/z (rel. %)", "Shoda spekter", "n", "Poznámka"]


def _row_cells(r: Row, n_total: int) -> list:
    """The descriptive columns of one row (same order as in the app)."""
    ions = ", ".join(f"{m} ({i:.0f})" for m, i in r.ions)
    note = "; ".join(x for x in [r.note] + r.edits if x)
    # A plain number ID is written as a number (Excel would warn "number stored as
    # text"); IDs of split/merged rows (5_1, 5+6) stay text.
    label = int(r.label) if r.label.isdigit() else r.label
    return [label, round(r.rt, 3) if math.isfinite(r.rt) else None,
            round(r.ri) if math.isfinite(r.ri) else None, ions,
            round(r.min_similarity, 2) if math.isfinite(r.min_similarity) else None, r.n_found, note]


def _write_header(ws, headers: list[str]) -> None:
    for j, text in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=j)
        safe_text(cell, text)
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"


def _write_rows(ws, rows: list[Row], values_per_row, poor_below: float) -> None:
    """Write data rows; values_per_row(row) -> list of extra cell values."""
    for i, r in enumerate(rows, start=2):
        values = _row_cells(r, 0) + values_per_row(r)
        for j, value in enumerate(values, start=1):
            cell = ws.cell(row=i, column=j)
            safe_text(cell, value) if isinstance(value, str) else setattr(cell, "value", value)
            if j == 2 and value is not None:
                cell.number_format = "0.000"
            elif j == 5 and value is not None:
                cell.number_format = "0.00"
            elif j > len(ROW_COLUMNS) and isinstance(value, (int, float)):
                cell.number_format = "0"
        # The same light-red flag as in the app for a poor spectral match.
        if math.isfinite(r.min_similarity) and r.min_similarity < poor_below:
            for j in range(1, len(ROW_COLUMNS) + 1):
                ws.cell(row=i, column=j).fill = POOR_FILL


def _marker_value(key: str, custom: str):
    return custom.strip() if key == "custom" else MISSING_MARKERS[key][1]


def _marker_suffix(key: str, custom: str) -> str:
    return custom.strip() if key == "custom" else MISSING_MARKERS[key][0]


def build_workbook(analysis: Analysis, params: AnalysisParams, alkanes: list[Alkane],
                   files: list[dict], options: ExportOptions, now: datetime | None = None,
                   computed_at: datetime | None = None, changed_since: bool = False) -> Workbook:
    """Create the workbook (not saved).

    params: the parameters the result was COMPUTED with (+ current view filters);
    files: [{"name", "role"}] as they were at computation time; computed_at: when
    Vyhodnotit ran (= processing time); now: export time.
    """
    options.validate()
    exported_at = (now if now is not None and now.tzinfo else (now or datetime.now()).astimezone())
    processed_at = computed_at or exported_at
    names = analysis.names
    reasons = view_filter(analysis.rows, params)
    rows = [r for r in analysis.rows if not r.deleted and (not options.only_visible or not reasons[r.uid])]
    wb = Workbook()
    used: set[str] = set()

    # ---- Sheet 1: Info (provenance, parameters, methods, libraries) ----
    ws = wb.active
    ws.title = sheet_title("Info", used)
    lines: list[list] = [
        [APP_NAME], ["Verze", __version__],
        ["Zpracováno (Vyhodnotit)", processed_at.isoformat(timespec="seconds")],
        ["Exportováno", exported_at.isoformat(timespec="seconds")],
        ["Python", platform.python_version()],
        ["Exportované řádky", f"{len(rows)} ({'jen viditelné v tabulce' if options.only_visible else 'všechny nesmazané'})"],
    ]
    if changed_since:
        lines.append(["Pozor", "Po výpočtu se změnily soubory nebo nastavení. Tento export odpovídá POSLEDNÍMU "
                               "výpočtu (soubory a parametry níže); změny se projeví po novém Vyhodnotit."])
    lines += [[], ["Soubory (při výpočtu)", "Role"]]
    role_names = {"sample": "vzorek", "alk": "alkany", "off": "nepoužit"}
    lines += [[f["name"], role_names.get(f["role"], f["role"])] for f in files]
    lines += [[], ["Alkany (C)", "RT [min]", "Zdroj"]]
    lines += [[f"C{a.carbons}", a.rt, a.source] for a in alkanes] or [["(žádné – RI se nepočítá)"]]
    lines += [[], ["Parametr", "Hodnota", "Jednotka", "Klíč"]]
    for info in PARAMETERS:
        value = getattr(params, info.key)
        if isinstance(value, list):
            value = " ".join(str(v) for v in value) or "(nic)"
        elif isinstance(value, bool):
            value = "ano" if value else "ne"
        lines.append([info.label, value, info.unit, info.key])
    lines += [[], ["Krok", "Metoda (standardní název)", "Implementace / nastavení", "Citace"]]
    lines += [list(m) for m in methods_table(params)]
    lines += [[], ["Knihovna", "Verze", "Citace"]]
    versions = library_versions()
    from importlib.metadata import PackageNotFoundError, version as package_version
    for package, citation in LIBRARY_CITATIONS:
        try:
            ver = versions.get(package) or package_version(package)
        except PackageNotFoundError:
            ver = "nenainstalováno"
        lines.append([package, ver, citation])
    bold_rows = {1}
    for i, line in enumerate(lines, start=1):
        for j, value in enumerate(line, start=1):
            cell = ws.cell(row=i, column=j)
            safe_text(cell, value) if isinstance(value, str) else setattr(cell, "value", value)
        if line and line[0] in ("Soubory (při výpočtu)", "Alkany (C)", "Parametr", "Krok", "Knihovna", "Pozor"):
            bold_rows.add(i)
    for i in bold_rows:
        for c in ws[i]:
            c.font = HEADER_FONT
    ws["A1"].font = TITLE_FONT
    _autosize(ws, {1: 34, 2: 48, 3: 48, 4: 60})

    # ---- Area sheets: one per chosen marking of missing values ----
    n_header = f"n (z {len(names)})"
    headers = ROW_COLUMNS[:5] + [n_header, ROW_COLUMNS[6]] + names
    for key in options.markers:
        missing = _marker_value(key, options.custom_text)
        ws = wb.create_sheet(sheet_title(f"Plochy ({_marker_suffix(key, options.custom_text)})", used))
        _write_header(ws, headers)
        _write_rows(ws, rows, lambda r, m=missing: [round(r.cells[n].area) if r.cells[n].area is not None else m
                                                    for n in names], params.poor_match_below)
        _autosize(ws)

    # ---- Replicate means ----
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(replicate_group(n), []).append(n)
    missing_mean = _marker_value(options.mean_missing, options.custom_text)

    def group_values(r: Row, g: str) -> list:
        return [r.cells[n].area for n in groups[g]]

    for fmt in options.mean_formats:
        if fmt == "mean":
            title, extra_headers = "Průměry", [f"{g} (n={len(m)})" for g, m in groups.items()]

            def cells(r: Row) -> list:
                out = []
                for g in groups:
                    mean, _ = replicate_stats(group_values(r, g))
                    out.append(round(mean) if mean is not None else missing_mean)
                return out
        elif fmt == "mean_pm_sd":
            title, extra_headers = "Průměr ± SD", [f"{g} (n={len(m)})" for g, m in groups.items()]

            def cells(r: Row) -> list:
                out = []
                for g in groups:
                    mean, sd = replicate_stats(group_values(r, g))
                    out.append(format_mean_sd(mean, sd) if mean is not None else missing_mean)
                return out
        else:
            title = "Průměr a SD"
            extra_headers = [h for g, m in groups.items() for h in (f"{g} průměr (n={len(m)})", f"{g} SD")]

            def cells(r: Row) -> list:
                out = []
                for g in groups:
                    mean, sd = replicate_stats(group_values(r, g))
                    if mean is None:
                        out += [missing_mean, missing_mean]
                    else:
                        out += [round(mean), round(sd) if sd is not None else None]
                return out
        ws = wb.create_sheet(sheet_title(title, used))
        _write_header(ws, ROW_COLUMNS[:5] + [n_header, ROW_COLUMNS[6]] + extra_headers)
        _write_rows(ws, rows, cells, params.poor_match_below)
        _autosize(ws)

    # ---- Provenance of every value (for checking/validation) ----
    if options.provenance:
        ws = wb.create_sheet(sheet_title("Původ hodnot", used))
        _write_header(ws, ["ID", "Vzorek", "Stav", "Okno od [min]", "Okno do [min]", "Vrchol [min]", "S/N",
                           "Shoda spektra", "Plocha [counts·s]", "Poznámka", "Úpravy řádku"])
        i = 2
        for r in rows:
            for n in names:
                c = r.cells[n]
                values = [int(r.label) if r.label.isdigit() else r.label, n, STATUS_LABELS[c.status],
                          round(c.t0, 4) if c.has_window else None, round(c.t1, 4) if c.has_window else None,
                          round(c.apex_rt, 4) if math.isfinite(c.apex_rt) else None,
                          round(c.snr, 1) if math.isfinite(c.snr) else None,
                          round(c.similarity, 3) if math.isfinite(c.similarity) else None,
                          round(c.area) if c.area is not None else None,
                          "; ".join(x for x in (c.source, c.reason) if x), "; ".join(r.edits)]
                for j, value in enumerate(values, start=1):
                    cell = ws.cell(row=i, column=j)
                    safe_text(cell, value) if isinstance(value, str) else setattr(cell, "value", value)
                i += 1
        _autosize(ws)
    return wb


def save_workbook(wb: Workbook, folder: Path, now: datetime | None = None) -> Path:
    """Save into `folder` under a unique, timestamped name; written to a temporary
    file first and then renamed, so an interrupted export never leaves half a file."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    path = unique_path(folder, f"GC-MS_vysledky_{stamp}", ".xlsx")
    temp = path.with_suffix(".xlsx.part")
    wb.save(temp)
    os.replace(temp, path)
    return path

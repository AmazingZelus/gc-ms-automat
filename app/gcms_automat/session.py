"""State of the running app: loaded files, alkanes, parameters, current result.

There is one session per app instance (the app is used by one person at a time,
on their own computer). All access goes through `lock`, because the web server
answers requests in several threads.
"""

from __future__ import annotations

import math
import re
import threading
from datetime import datetime
from dataclasses import dataclass

import numpy as np

from .analysis.cdf import Run, read_cdf
from .analysis.params import PARAMETERS, AnalysisParams
from .analysis.retention import Alkane, check_alkanes, find_alkanes, parse_alkane_table
from .analysis.spectra import MzAxis
from .analysis.table import STATUS_LABELS, Analysis, Cell, EditError, Row, replicate_group, view_filter

ROLES = ("sample", "alk", "off")
MAX_TRACE_POINTS = 3000  # per trace sent to the browser (enough for a sharp plot)


@dataclass
class LoadedFile:
    run: Run
    role: str


def clean_name(filename: str) -> str:
    """'C:/data/ryby313_RK6_0M_A.CDF' -> 'ryby313_RK6_0M_A'."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return base[:-4] if base.lower().endswith(".cdf") else base


class Session:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.files: dict[str, LoadedFile] = {}
        self.alkanes: list[Alkane] = []
        self.params = AnalysisParams()
        self.analysis: Analysis | None = None
        self.result_files: list[dict] = []
        self.computed_at: datetime | None = None
        self.dirty = False  # files/parameters changed since the last computation

    # ------------------------------------------------------------ files
    def add_file(self, filename: str, data: bytes) -> tuple[str, bool]:
        """Read one .CDF file; returns (name, replaced). Same name replaces the old file."""
        name = clean_name(filename)
        run = read_cdf(data, name)
        replaced = name in self.files
        # "alkany_std", "alk-mix", "C8-C20_alkanes" -> alkane standard; "alkohol_1" is not.
        role = "alk" if re.search(r"(^|[_\-\s])alk(an\w*)?([_\-\s\d]|$)|alkan", name, re.IGNORECASE) else "sample"
        self.files[name] = LoadedFile(run, role)
        self.dirty = True
        return name, replaced

    def set_role(self, name: str, role: str) -> None:
        if name not in self.files or role not in ROLES:
            raise EditError("Neznámý soubor nebo role.")
        self.files[name].role = role
        self.dirty = True

    def remove_file(self, name: str) -> None:
        self.files.pop(name, None)
        self.dirty = True

    def files_json(self) -> list[dict]:
        out = []
        for name in sorted(self.files, key=_natural_key):
            f = self.files[name]
            out.append({"name": name, "role": f.role, "group": replicate_group(name), "scans": f.run.n_scans,
                        "rt_end": round(float(f.run.rt_min[-1]), 2), "title": f.run.title})
        return out

    # ------------------------------------------------------------ alkanes
    def set_alkanes(self, items: list[dict]) -> None:
        alkanes = []
        for i, item in enumerate(items, start=1):
            try:
                carbons, rt = int(item["carbons"]), float(item["rt"])
            except (KeyError, TypeError, ValueError):
                carbons, rt = 0, math.nan
            if not (carbons > 0 and rt > 0 and math.isfinite(rt)):
                raise EditError(f"Alkan na řádku {i}: zadej kladný počet uhlíků a RT.")
            alkanes.append(Alkane(carbons, rt, str(item.get("source") or "ručně")))
        self._apply_alkanes(alkanes)

    def import_alkanes(self, text: str) -> int:
        alkanes = parse_alkane_table(text)
        if not alkanes:
            raise EditError("V textu jsem nenašel žádné dvojice „počet uhlíků; RT“.")
        self._apply_alkanes(alkanes)
        return len(alkanes)

    def auto_alkanes(self) -> int:
        runs = [f.run for f in self.files.values() if f.role == "alk"]
        if not runs:
            raise EditError("Označ aspoň jeden soubor jako „Alkany“.")
        found = find_alkanes(runs, MzAxis.covering(runs), self.params.baseline_log_lambda, self.params.smooth_points,
                             self.params.alkane_min_molecular_ion_pct)
        if not found:
            raise EditError("V souborech alkanů jsem žádné n-alkany nenašel. Zadej časy ručně.")
        self._apply_alkanes(found)
        return len(found)

    def _apply_alkanes(self, alkanes: list[Alkane]) -> None:
        # This refuses an inconsistent alkane list (it would give wrong RI silently).
        problem = check_alkanes(alkanes)
        if problem:
            raise EditError("Alkany nepoužity: " + problem)
        # This recomputes RI of the current result at once (no full re-run needed).
        self.alkanes = sorted(alkanes, key=lambda a: a.rt)
        if self.analysis is not None:
            self.analysis.alkanes = self.alkanes
            for row in self.analysis.rows:
                self.analysis.refresh(row)

    def alkanes_json(self) -> list[dict]:
        return [{"carbons": a.carbons, "rt": a.rt, "source": a.source} for a in self.alkanes]

    # ------------------------------------------------------------ computation
    def update_params(self, values: dict, stage: str | None = None) -> list[str]:
        """Take over parameter values (only those of `stage`, if given).

        Returns the labels of rejected (invalid) values; those keep their old value.
        """
        wanted = {i.key: values[i.key] for i in PARAMETERS
                  if i.key in values and (stage is None or i.stage == stage)}
        rejected: list[str] = []
        new = AnalysisParams.from_dict(wanted, base=self.params, rejected=rejected)
        if any(getattr(new, i.key) != getattr(self.params, i.key) for i in PARAMETERS if i.stage == "pipeline"):
            self.dirty = True
        self.params = new
        return rejected

    def run(self) -> None:
        runs = [f.run for name, f in sorted(self.files.items(), key=lambda x: _natural_key(x[0])) if f.role == "sample"]
        if not runs:
            raise EditError("Nahraj aspoň jeden vzorek (role „Vzorek“).")
        if self.params.rt_max <= self.params.rt_min:
            raise EditError("„RT do“ musí být větší než „RT od“.")
        self.analysis = Analysis(runs, self.alkanes, self.params)
        # This remembers exactly which files and when, for the export's Info sheet
        # (the parameters themselves are kept by the Analysis: analysis.params).
        self.result_files = [{"name": f["name"], "role": f["role"]} for f in self.files_json()]
        self.computed_at = datetime.now().astimezone()
        self.dirty = False

    @property
    def has_work(self) -> bool:
        """True when there is a computed result (losing it would cost the user work)."""
        return self.analysis is not None

    def export_params(self) -> AnalysisParams:
        """Parameters for an export: computation parameters as USED for the result,
        view filters as they are set now (they decide which rows are exported)."""
        a = self.require()
        values = a.params.to_dict()
        values.update({i.key: getattr(self.params, i.key) for i in PARAMETERS if i.stage == "view"})
        return AnalysisParams(**values)

    def require(self) -> Analysis:
        if self.analysis is None:
            raise EditError("Nejdřív klikni na Vyhodnotit.")
        return self.analysis

    # ------------------------------------------------------------ JSON for the UI
    def table_json(self) -> dict:
        a = self.require()
        reasons = view_filter(a.rows, self.params)
        rows = [self._row_json(a, r, reasons[r.uid]) for r in a.rows]
        return {
            "names": a.names, "groups": [replicate_group(n) for n in a.names], "rows": rows,
            "stats": a.stats, "can_undo": a.can_undo, "dirty": self.dirty,
            "n_visible": sum(1 for r in rows if not r["hidden"]),
            "has_alkanes": len(self.alkanes) >= 2,
        }

    def _row_json(self, a: Analysis, r: Row, hidden: str) -> dict:
        cells = {}
        for name in a.names:
            c = r.cells[name]
            cells[name] = {"v": None if c.area is None else round(c.area), "s": c.status, "title": _cell_title(name, c)}
        notes = []
        if any(c.area is not None and not c.inside for c in r.cells.values()):
            notes.append("vrchol na okraji okna")
        return {
            "uid": r.uid, "label": r.label, "rt": _num(r.rt, 3), "ri": None if not math.isfinite(r.ri) else round(r.ri),
            "ions": ", ".join(f"{m} ({i:.0f})" for m, i in r.ions), "base_ion": r.base_ion,
            "sim_min": _num(r.min_similarity, 2), "n": r.n_found, "max_area": round(r.max_area),
            "poor": math.isfinite(r.min_similarity) and r.min_similarity < self.params.poor_match_below,
            "note": r.note, "auto_notes": notes, "edits": r.edits, "deleted": r.deleted,
            "hidden": hidden, "cells": cells, "ref_run": r.ref_run,
        }

    def detail_json(self, uid: int, t0: float, t1: float) -> dict:
        """Chromatograms around a row, all windows in view, reference spectrum."""
        a = self.require()
        row = a.row(uid)
        traces = []
        for name in a.names:
            tr = a.data[name].trace
            mask = (tr.rt_min >= t0) & (tr.rt_min <= t1)
            idx = np.flatnonzero(mask)
            step = max(1, idx.size // MAX_TRACE_POINTS)
            idx = idx[::step]
            traces.append({"name": name, "group": replicate_group(name),
                           "rt": np.round(tr.rt_min[idx], 5).tolist(),
                           "raw": np.round(tr.raw[idx], 1).tolist(),
                           "baseline": np.round(tr.baseline[idx], 1).tolist(),
                           "corr": np.round(tr.corrected[idx], 1).tolist()})
        windows = []
        for other in a.rows:
            if other.deleted and other is not row:
                continue
            for name in a.names:
                c = other.cells[name]
                if c.has_window and c.t1 >= t0 and c.t0 <= t1:
                    windows.append({"uid": other.uid, "label": other.label, "sample": name,
                                    "t0": c.t0, "t1": c.t1, "own": other is row,
                                    "base0": round(c.base0, 1), "base1": round(c.base1, 1)})
        cw = a.consensus_window(row)
        return {"row": self._row_json(a, row, ""), "traces": traces, "windows": windows,
                "window": [cw[0], cw[1]], "spectrum": _spectrum_json(a.axis, row.ref_spectrum)}

    def spectrum_json(self, uid: int, sample: str) -> dict:
        """Spectrum of one sample at the row (its window, or the row's RT if ND)."""
        a = self.require()
        row = a.row(uid)
        if sample not in a.names:
            raise EditError("Neznámý vzorek.")
        c = row.cells[sample]
        t0, t1 = (c.t0, c.t1) if c.has_window else a.consensus_window(row)
        spectrum, _, _ = a.window_spectrum(sample, t0, t1)
        if spectrum is None:
            raise EditError("V tomto okně nejde spočítat spektrum.")
        return {"sample": sample, "status": STATUS_LABELS[c.status], "similarity": round(a.sim(spectrum, row.ref_spectrum), 3),
                "spectrum": _spectrum_json(a.axis, spectrum)}


def _spectrum_json(axis: MzAxis, spectrum: np.ndarray) -> dict:
    idx = np.flatnonzero(spectrum > 0.05)
    return {"mz": (axis.lo + idx).tolist(), "i": np.round(spectrum[idx], 2).tolist()}


def _cell_title(name: str, c: Cell) -> str:
    """Tooltip of a table cell: where the number comes from."""
    parts = [f"{name}: {STATUS_LABELS[c.status]}"]
    if c.has_window:
        parts.append(f"okno {c.t0:.3f}–{c.t1:.3f} min ({c.source})")
    if math.isfinite(c.snr):
        parts.append(f"S/N {c.snr:.1f}")
    if math.isfinite(c.similarity):
        parts.append(f"shoda spektra {c.similarity:.2f}")
    if c.area is not None and not c.inside:
        parts.append("maximum na okraji okna")
    if c.reason:
        parts.append(c.reason)
    return " · ".join(parts)


def _num(value: float, digits: int):
    return None if value is None or not math.isfinite(value) else round(value, digits)


def _natural_key(text: str):
    """Sort 'vzorek_2' before 'vzorek_10'."""
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]

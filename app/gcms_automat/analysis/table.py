"""The result table: one row = one compound, one cell = its area in one run.

Every number comes from exactly one integration window [t0, t1] on one run's
baseline-corrected TIC. Rule enforced everywhere: within one run, windows of
different (non-deleted) rows never overlap (touching edges are allowed).
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field

import numpy as np

from .align import PeakRef, align_peaks
from .cdf import Run
from .params import AnalysisParams
from .retention import Alkane, retention_index
from .signal import (ProcessedTrace, WindowRule, apex_in_window, cluster_areas, integrate_window, pick_peaks,
                     process_trace, refine_apex)
from .spectra import MzAxis, base_ion, is_co2_noise, peak_spectrum, similarity, top_ions

EPS = 1e-6  # [min] tolerance when comparing window edges

STATUS_LABELS = {"det": "detekováno", "fill": "dointegrováno", "man": "ručně", "ND": "nenalezeno"}


def replicate_group(name: str) -> str:
    """Replicate group of a run: 'vzorek_1_a' and 'vzorek_1_b' -> 'vzorek_1'.

    The last character is a replicate letter only if it follows _ - or a space.
    """
    return re.sub(r"[_\-\s][A-Za-z]$", "", name)


@dataclass
class Cell:
    """Area of one compound in one run."""

    status: str = "ND"            # det | fill | man | ND
    t0: float = math.nan          # window start [min]
    t1: float = math.nan          # window end [min]
    area: float | None = None     # [counts * s]
    apex_rt: float = math.nan     # [min]
    snr: float = math.nan         # [-]
    similarity: float = math.nan  # to the row's reference spectrum [0-1]
    inside: bool = False          # apex is a real local maximum inside the window
    base0: float = 0.0            # integration baseline at t0 [counts above the common baseline]
    base1: float = 0.0            # ... and at t1
    source: str = ""              # where the window came from
    reason: str = ""              # why ND / remarks

    @property
    def has_window(self) -> bool:
        return self.status != "ND" and math.isfinite(self.t0) and math.isfinite(self.t1)


@dataclass
class Row:
    """One compound."""

    uid: int
    label: str
    cells: dict[str, Cell]
    ref_run: str
    ref_spectrum: np.ndarray
    deleted: bool = False
    edits: list[str] = field(default_factory=list)
    note: str = ""                 # the analyst's own note
    # Derived values (refresh()):
    rt: float = math.nan
    ri: float = math.nan
    n_found: int = 0
    max_area: float = 0.0
    min_similarity: float = math.nan
    base_ion: int | None = None
    ions: list[tuple[int, float]] = field(default_factory=list)


@dataclass
class RunData:
    """A run with its processed chromatogram."""

    run: Run
    trace: ProcessedTrace


class EditError(ValueError):
    """A manual edit was refused (message is shown to the user, in Czech)."""


class Analysis:
    """Computed result for a set of runs, plus manual edits with undo."""

    def __init__(self, runs: list[Run], alkanes: list[Alkane], params: AnalysisParams):
        # This prepares the common m/z axis and the baseline-corrected TIC of each run.
        self.params = params
        self.alkanes = sorted(alkanes, key=lambda a: a.rt)
        self.axis = MzAxis.covering(runs)
        self.names = [r.name for r in runs]
        self.data = {r.name: RunData(r, process_trace(r.rt_min, r.tic(), params.baseline_log_lambda,
                                                      params.smooth_points)) for r in runs}
        self.rule = WindowRule(params.window_end_pct, params.window_end_noise_sigma, params.window_end_slope_pct,
                               params.integration_baseline, params.integration_lift_factor)
        self.rows: list[Row] = []
        self.stats: dict[str, int] = {}
        self._undo: list[tuple[list[Row], int, str]] = []
        self._next_uid = 1
        self._compute()

    # ------------------------------------------------------------ helpers
    def sim(self, a: np.ndarray, b: np.ndarray) -> float:
        """Spectral similarity with the user's weighting."""
        return similarity(a, b, self.axis, self.params.weight_intensity_power, self.params.weight_mz_power)

    def window_spectrum(self, name: str, t0: float, t1: float) -> tuple[np.ndarray | None, int, bool]:
        """Spectrum at the highest point of a window (None if the window is too narrow)."""
        data = self.data[name]
        rt = data.trace.rt_min
        apex, inside = apex_in_window(data.trace, t0, t1)
        start = int(np.searchsorted(rt, t0 - EPS))
        end = min(int(np.searchsorted(rt, t1 + EPS)) - 1, rt.size - 1)
        if end - start < 2:
            return None, apex, False
        return peak_spectrum(data.run, apex, start, end, self.axis, self.params.spectrum_background_scans), apex, inside

    def evaluate(self, name: str, t0: float, t1: float, ref: np.ndarray | None, status: str, source: str,
                 min_snr: float | None = None, min_sim: float | None = None) -> Cell:
        """Integrate a window as a cell; with min_snr/min_sim it must hold a real peak."""
        data = self.data[name]
        spectrum, apex, inside = self.window_spectrum(name, t0, t1)
        cell = Cell(status=status, t0=t0, t1=t1, source=source)
        if spectrum is None:
            return Cell(status="ND", source=source, reason="okno je užší než 3 skeny")
        # Apex time refined between scans (same as for detected peaks) [min].
        cell.apex_rt = refine_apex(data.trace.rt_min, data.trace.corrected, apex)
        cell.snr = float(data.trace.corrected[apex] / data.trace.noise)
        cell.inside = inside
        if ref is not None:
            cell.similarity = self.sim(spectrum, ref)
        # This applies the peak criteria (used when filling in missing values).
        if min_snr is not None:
            reason = ""
            if not inside:
                reason = "v okně není vrchol píku (maximum na okraji)"
            elif cell.snr < min_snr:
                reason = f"S/N {cell.snr:.1f} < {min_snr:g}"
            elif min_sim is not None and ref is not None and cell.similarity < min_sim:
                reason = f"shoda spektra {cell.similarity:.2f} < {min_sim:g}"
            if reason:
                return Cell(status="ND", source=source, reason=reason)
        cell.area = integrate_window(data.trace, t0, t1, self.rule)
        return cell

    def live_rows(self, exclude: list[Row] | None = None) -> list[Row]:
        """Rows that take part in the no-overlap rule (not deleted)."""
        exclude = exclude or []
        return [r for r in self.rows if not r.deleted and r not in exclude]

    def overlaps(self, name: str, t0: float, t1: float, exclude: list[Row]) -> list[Row]:
        """Rows whose window in run `name` overlaps [t0, t1] (touching is allowed)."""
        hits = []
        for row in self.live_rows(exclude):
            c = row.cells[name]
            if c.has_window and c.t1 > t0 + EPS and c.t0 < t1 - EPS:
                hits.append(row)
        return hits

    def clip_to_free(self, name: str, t0: float, t1: float, exclude: list[Row],
                     keep: float | None = None) -> tuple[float, float]:
        """Shrink [t0, t1] so it does not overlap other rows' windows in that run.

        `keep` [min]: the time that must stay inside (the row's own apex); by default
        the window centre. A neighbour left of it cuts the start, right of it the end.
        """
        centre = (t0 + t1) / 2 if keep is None else keep
        for row in self.overlaps(name, t0, t1, exclude):
            c = row.cells[name]
            middle = c.apex_rt if math.isfinite(c.apex_rt) else (c.t0 + c.t1) / 2
            if middle <= centre:
                t0 = max(t0, c.t1)
            else:
                t1 = min(t1, c.t0)
        return t0, t1

    def reintegrate(self) -> None:
        """Recompute all areas run by run: touching windows share one baseline line.

        Called after the computation and after every edit, so the area of a peak
        always follows the integrator rule for its current neighbours.
        """
        # Deleted rows stay part of the cluster geometry, so marking a row as noise
        # never changes the areas of its neighbours (its own area is just not shown).
        for name in self.names:
            trace = self.data[name].trace
            live = [(r, r.cells[name]) for r in self.rows
                    if r.cells[name].has_window and r.cells[name].area is not None]
            lines: list = []
            areas = cluster_areas(trace, [(c.t0, c.t1) for _, c in live], self.rule, lines)
            for (row, cell), area, (b0, b1) in zip(live, areas, lines):
                cell.area, cell.base0, cell.base1 = area, b0, b1
        for row in self.rows:
            self.refresh(row)

    def consensus_window(self, row: Row) -> tuple[float, float]:
        """Median window of the row's cells that have a window [min]."""
        cells = [c for c in row.cells.values() if c.has_window]
        if not cells:
            return row.rt - 0.02, row.rt + 0.02
        return float(np.median([c.t0 for c in cells])), float(np.median([c.t1 for c in cells]))

    def refresh(self, row: Row) -> None:
        """Recompute the derived values of a row from its cells."""
        with_area = [(n, c) for n, c in row.cells.items() if c.area is not None]
        # RT = mean apex time of the cells with an area [min].
        row.rt = float(np.mean([c.apex_rt for _, c in with_area])) if with_area else \
            float(np.mean(self.consensus_window(row)))
        row.ri = retention_index(row.rt, self.alkanes)
        row.n_found = len(with_area)
        row.max_area = max((c.area for _, c in with_area), default=0.0)
        sims = [c.similarity for n, c in with_area if n != row.ref_run and math.isfinite(c.similarity)]
        row.min_similarity = min(sims) if sims else math.nan
        row.base_ion = base_ion(row.ref_spectrum, self.axis)
        row.ions = top_ions(row.ref_spectrum, self.axis, 5)

    def _sort_rows(self) -> None:
        """Order rows by elution: middle of the integration window, then RT.

        (The window middle keeps the left part of a split before the right part even
        when both apexes sit at the split point.)
        """
        def key(r: Row) -> tuple[float, float]:
            t0, t1 = self.consensus_window(r)
            return ((t0 + t1) / 2, r.rt)
        self.rows.sort(key=key)

    def _new_uid(self) -> int:
        uid = self._next_uid
        self._next_uid += 1
        return uid

    # ------------------------------------------------------------ pipeline
    def _compute(self) -> None:
        P = self.params
        # ---- This finds the peaks and their spectra in every run ----
        peak_refs: list[PeakRef] = []
        detected: dict[tuple[int, int], object] = {}
        for i, name in enumerate(self.names):
            d = self.data[name]
            peaks = pick_peaks(d.trace, P.min_height_pct, P.min_snr, P.rt_min, P.rt_max, self.rule)
            for k, p in enumerate(peaks):
                spec = peak_spectrum(d.run, p.apex, p.start, p.end, self.axis, P.spectrum_background_scans)
                peak_refs.append(PeakRef(i, k, p.rt, p.height, spec))
                detected[(i, k)] = p
        self.stats["peaks"] = len(peak_refs)

        # ---- This aligns the peaks across runs ----
        clusters = align_peaks(peak_refs, len(self.names), P.rt_tolerance_min, P.min_similarity, self.sim)
        self.stats["clusters"] = len(clusters)
        self.stats["co2"] = 0

        # ---- This turns clusters into rows (CO2 noise is dropped here) ----
        for cluster in clusters:
            ref = max(cluster.members.values(), key=lambda m: m.height)
            if P.co2_filter and is_co2_noise(ref.spectrum, self.axis, P.co2_ion_pct, P.co2_min_other_ions):
                self.stats["co2"] += 1
                continue
            cells = {}
            for i, name in enumerate(self.names):
                member = cluster.members.get(i)
                if member is None:
                    cells[name] = Cell(reason="pík nenalezen nad prahem detekce")
                    continue
                p = detected[(i, member.index)]
                cells[name] = Cell(status="det", t0=p.t0, t1=p.t1, area=p.area, apex_rt=p.rt, snr=p.snr,
                                   similarity=1.0 if member is ref else self.sim(member.spectrum, ref.spectrum),
                                   inside=True, source="pík nalezen v záznamu")
            row = Row(uid=0, label="", cells=cells, ref_run=self.names[ref.run], ref_spectrum=ref.spectrum)
            self.refresh(row)
            self.rows.append(row)
        self._sort_rows()

        # ---- This fills in a missing replicate in the window of the found one ----
        self.stats["filled"] = self.stats["fill_failed"] = 0
        if P.fill_replicates:
            groups: dict[str, list[str]] = {}
            for name in self.names:
                groups.setdefault(replicate_group(name), []).append(name)
            for row in self.rows:
                for members in groups.values():
                    found = [n for n in members if row.cells[n].status == "det"]
                    if len(members) < 2 or not found:
                        continue
                    source = max(found, key=lambda n: row.cells[n].area)
                    src = row.cells[source]
                    src_spec, _, _ = self.window_spectrum(source, src.t0, src.t1)
                    for name in members:
                        if row.cells[name].status != "ND":
                            continue
                        cell = self._fill(row, name, (src.t0, src.t1), src_spec, f"dointegrace (paralelka), okno z {source}")
                        row.cells[name] = cell
                        self.stats["filled" if cell.status == "fill" else "fill_failed"] += 1
                self.refresh(row)

        self.reintegrate()
        self._hide_small_rows()
        # ---- This numbers the rows by retention time ----
        for row in self.rows:
            row.uid = self._new_uid()
            row.label = str(row.uid)

    def _hide_small_rows(self) -> None:
        """Hide rows whose largest area (over all runs) is below the minimum area.

        Applied AFTER integration and done like a manual delete: the row stays in the
        cluster geometry, so hiding a small peak never changes its neighbours' areas,
        and the analyst can show and restore it. min_area in counts * s; 0 = off.
        """
        self.stats["small"] = 0
        if self.params.min_area <= 0:
            return
        for row in self.rows:
            if row.max_area < self.params.min_area:
                row.deleted = True
                row.edits.append(f"skryto: největší plocha < min. plocha {self.params.min_area:g}")
                self.stats["small"] += 1

    def _fill(self, row: Row, name: str, window: tuple[float, float], ref: np.ndarray | None, source: str) -> Cell:
        """Try to integrate a run where the row has no peak (ND unless a real peak is there)."""
        t0, t1 = self.clip_to_free(name, window[0], window[1], exclude=[row])
        if not t1 > t0:
            return Cell(source=source, reason="okno je celé obsazené sousedním píkem")
        cell = self.evaluate(name, t0, t1, ref if ref is not None else row.ref_spectrum, "fill", source,
                             self.params.fill_min_snr, self.params.fill_min_similarity)
        if cell.status == "ND" and (t0 > window[0] + EPS or t1 < window[1] - EPS):
            cell.reason += " (okno zúženo kvůli sousednímu píku)"
        if cell.status == "fill" and ref is not None:
            # The similarity column always refers to the row's reference spectrum.
            spectrum, _, _ = self.window_spectrum(name, t0, t1)
            cell.similarity = self.sim(spectrum, row.ref_spectrum) if spectrum is not None else math.nan
        return cell

    # ------------------------------------------------------------ undo
    def _checkpoint(self, description: str) -> None:
        """Remember the current rows so the next edit can be undone."""
        self._undo.append((copy.deepcopy(self.rows), self._next_uid, description))
        del self._undo[:-50]  # keep the last 50 steps

    def undo(self) -> str:
        """Undo the last edit; returns its description."""
        if not self._undo:
            raise EditError("Není co vrátit.")
        self.rows, self._next_uid, description = self._undo.pop()
        # Derived values (e.g. RI) follow the CURRENT alkanes, not those of the snapshot.
        for row in self.rows:
            self.refresh(row)
        return description

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    def row(self, uid: int) -> Row:
        for r in self.rows:
            if r.uid == uid:
                return r
        raise EditError("Řádek už neexistuje (byl sloučen nebo rozdělen).")

    def live_row(self, uid: int) -> Row:
        """A row that may be edited (deleted rows must be restored first)."""
        row = self.row(uid)
        if row.deleted:
            raise EditError(f"Řádek {row.label} je smazaný. Nejdřív ho obnov.")
        return row

    # ------------------------------------------------------------ manual edits
    def set_window(self, uid: int, t0: float, t1: float, samples: list[str] | None = None) -> tuple[Row, list[str]]:
        """Use the window [t0, t1] for the row; returns (row, runs where it was clipped).

        samples=None: every run where the row has an area; each run's window edges move
        by the same amounts as the edges of the shown median window.
        samples=[...]: only those runs, exactly [t0, t1] (window of one sample).
        In every run the window is clipped at neighbouring rows' windows (it may
        touch them, never overlap); refused if nothing is left in some run.
        """
        row = self.live_row(uid)
        if not t1 > t0:
            raise EditError("Konec okna musí být větší než začátek.")
        if samples:
            unknown = [n for n in samples if n not in self.names]
            if unknown:
                raise EditError("Neznámý vzorek: " + ", ".join(unknown))
            targets = list(samples)
        else:
            targets = [n for n in self.names if row.cells[n].has_window]
        if not targets:
            raise EditError("Řádek nemá žádnou plochu. Použij „Integrovat i v ND“.")
        # This computes each run's window: the start and end move by the same amount
        # as the start and end of the window the user sees (the median window), so
        # moving only one edge moves only that edge; then clipped at the neighbours,
        # always keeping the row's own apex in that run.
        shown = self.consensus_window(row)
        windows, clipped = {}, []
        for n in targets:
            c = row.cells[n]
            if samples or not c.has_window:
                a, b = t0, t1
            else:
                a, b = c.t0 + (t0 - shown[0]), c.t1 + (t1 - shown[1])
            if not b > a:
                raise EditError(f"Okno nepoužito: ve vzorku {n} by bylo prázdné.")
            keep = c.apex_rt if (math.isfinite(c.apex_rt) and a < c.apex_rt < b) else None
            ca, cb = self.clip_to_free(n, a, b, exclude=[row], keep=keep)
            if not cb > ca + EPS:
                raise EditError(f"Okno nepoužito: ve vzorku {n} je celé obsazené sousedním řádkem.")
            if ca > a + EPS or cb < b - EPS:
                clipped.append(n)
            windows[n] = (ca, cb)
        self._checkpoint(f"okno řádku {row.label}")
        for n, (a, b) in windows.items():
            row.cells[n] = self.evaluate(n, a, b, row.ref_spectrum, "man", "ruční okno")
        row.edits.append(f"okno {t0:.3f}–{t1:.3f} min" + (f" ({', '.join(samples)})" if samples else ""))
        self.reintegrate()
        self._sort_rows()
        return row, clipped

    def fill_missing(self, uid: int) -> Row:
        """Try to integrate the runs where the row is ND, in the row's median window."""
        row = self.live_row(uid)
        missing = [n for n in self.names if row.cells[n].status == "ND"]
        if not missing:
            raise EditError("Řádek nemá žádné ND.")
        if not any(c.has_window for c in row.cells.values()):
            raise EditError("Řádek nemá v žádném vzorku okno, není podle čeho dointegrovat. Nastav okno ručně.")
        self._checkpoint(f"dointegrace řádku {row.label}")
        window = self.consensus_window(row)
        for n in missing:
            row.cells[n] = self._fill(row, n, window, None, "ruční dointegrace v okně řádku")
        found = [n for n in missing if row.cells[n].status == "fill"]
        row.edits.append(f"dointegrace ND: {len(found)} z {len(missing)}")
        self.refresh(row)
        self.reintegrate()
        return row

    def merge(self, uids: list[int]) -> Row:
        """Merge rows into one: per run, the window spans all merged windows."""
        rows = sorted({self.row(u).uid: self.row(u) for u in uids}.values(), key=lambda r: r.rt)
        if len(rows) < 2:
            raise EditError("Pro sloučení vyber aspoň dva řádky.")
        if any(r.deleted for r in rows):
            raise EditError("Smazané řádky nejde slučovat.")
        windows = {}
        for n in self.names:
            cells = [r.cells[n] for r in rows if r.cells[n].has_window]
            if cells:
                windows[n] = (min(c.t0 for c in cells), max(c.t1 for c in cells))
        conflicts = [f"{n} s řádkem {o.label}" for n, w in windows.items() for o in self.overlaps(n, *w, rows)]
        if conflicts:
            raise EditError("Sloučení nepoužito, okno by se překrývalo: " + "; ".join(conflicts) + ".")
        self._checkpoint("sloučení " + ", ".join(r.label for r in rows))
        # The reference spectrum comes from the row with the largest total area.
        biggest = max(rows, key=lambda r: sum(c.area or 0 for c in r.cells.values()))
        merged = Row(uid=self._new_uid(), label="+".join(r.label for r in rows), cells={},
                     ref_run=biggest.ref_run, ref_spectrum=biggest.ref_spectrum,
                     edits=["sloučeno z " + ", ".join(r.label for r in rows)])
        for n in self.names:
            merged.cells[n] = self.evaluate(n, *windows[n], merged.ref_spectrum, "man", "sloučení řádků") \
                if n in windows else Cell(reason="žádný ze sloučených řádků tu neměl plochu")
        self.refresh(merged)
        self.rows = [r for r in self.rows if r not in rows] + [merged]
        self.reintegrate()
        self._sort_rows()
        return merged

    def split(self, uid: int, at: float) -> list[Row]:
        """Split a row at time `at` [min] into <label>_1 and <label>_2."""
        row = self.live_row(uid)
        t0, t1 = self.consensus_window(row)
        cells = [c for c in row.cells.values() if c.has_window]
        if not cells or not (min(c.t0 for c in cells) + 0.002 < at < max(c.t1 for c in cells) - 0.002):
            raise EditError("Místo rozdělení musí ležet uvnitř okna řádku.")
        self._checkpoint(f"rozdělení řádku {row.label}")
        parts = []
        for j, side in enumerate(("left", "right"), start=1):
            part = Row(uid=self._new_uid(), label=f"{row.label}_{j}", cells={}, ref_run=row.ref_run,
                       ref_spectrum=row.ref_spectrum, edits=[f"rozděleno z {row.label} v {at:.3f} min"])
            for n in self.names:
                c = row.cells[n]
                if not c.has_window:
                    part.cells[n] = copy.copy(c)
                    continue
                window = (c.t0, min(c.t1, at)) if side == "left" else (max(c.t0, at), c.t1)
                part.cells[n] = self.evaluate(n, *window, None, "man", "rozdělení píku") \
                    if window[1] > window[0] + EPS else Cell(source="rozdělení píku", reason="okno leží celé v druhé části")
            # This takes the part's reference spectrum from its largest cell.
            with_area = [n for n in self.names if part.cells[n].area is not None]
            if with_area:
                best = max(with_area, key=lambda n: part.cells[n].area)
                spectrum, _, _ = self.window_spectrum(best, part.cells[best].t0, part.cells[best].t1)
                if spectrum is not None:
                    part.ref_run, part.ref_spectrum = best, spectrum
                for n in with_area:
                    s, _, _ = self.window_spectrum(n, part.cells[n].t0, part.cells[n].t1)
                    part.cells[n].similarity = self.sim(s, part.ref_spectrum) if s is not None else math.nan
            self.refresh(part)
            parts.append(part)
        index = self.rows.index(row)
        self.rows[index:index + 1] = parts
        self.reintegrate()
        self._sort_rows()
        return parts

    def set_deleted(self, uid: int, deleted: bool) -> Row:
        """Mark a row as deleted (noise) or restore it."""
        row = self.row(uid)
        if not deleted:
            # Restoring must not break the no-overlap rule.
            conflicts = [f"{n} s řádkem {o.label}" for n, c in row.cells.items() if c.has_window
                         for o in self.overlaps(n, c.t0, c.t1, [row])]
            if conflicts:
                raise EditError("Řádek nejde obnovit, jeho okno se překrývá: " + "; ".join(conflicts) + ".")
        self._checkpoint(("obnovení" if not deleted else "smazání") + f" řádku {row.label}")
        row.deleted = deleted
        row.edits.append("smazáno ručně" if deleted else "obnoveno")
        self.reintegrate()
        return row

    def set_note(self, uid: int, text: str) -> Row:
        """The analyst's own note for a row (max. 500 characters)."""
        row = self.row(uid)
        self._checkpoint(f"poznámka řádku {row.label}")
        row.note = text.strip()[:500]
        return row

    # ------------------------------------------------------------ checks
    def overlap_problems(self) -> list[str]:
        """List of overlapping windows (must always be empty; used by tests)."""
        problems = []
        for n in self.names:
            cells = sorted(((r.cells[n], r) for r in self.live_rows() if r.cells[n].has_window), key=lambda x: x[0].t0)
            for (a, ra), (b, rb) in zip(cells, cells[1:]):
                if b.t0 < a.t1 - EPS:
                    problems.append(f"{n}: {ra.label} a {rb.label}")
        return problems


def view_filter(rows: list[Row], params: AnalysisParams) -> dict[int, str]:
    """Why each row is hidden in the table ('' = visible). Never changes the numbers."""
    reasons: dict[int, str] = {}
    hide_ions = set(params.hide_base_ions)
    for r in rows:
        reason = ""
        if r.deleted:
            auto = bool(r.edits) and r.edits[-1].startswith("skryto:")   # hidden by the minimum area
            reason = "pod min. plochou" if auto else "smazáno"
        elif r.base_ion is not None and r.base_ion in hide_ions:
            reason = f"základní iont {r.base_ion}"
        elif (params.small_max_detections > 0 and params.small_max_area > 0
              and r.n_found < params.small_max_detections and r.max_area < params.small_max_area):
            reason = f"malý pík (n {r.n_found}, max. plocha {r.max_area:.0f})"
        reasons[r.uid] = reason
    # This keeps only the N largest of the remaining rows.
    if params.top_n > 0:
        visible = sorted((r for r in rows if not reasons[r.uid]), key=lambda r: -r.max_area)
        for r in visible[params.top_n:]:
            reasons[r.uid] = f"mimo {params.top_n} největších"
    return reasons

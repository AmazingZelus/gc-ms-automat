"""Excel export: provenance header, missing-value sheets, replicate means (known values)."""

import io
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from openpyxl import load_workbook

from gcms_automat import APP_NAME, __version__
from gcms_automat.analysis.params import AnalysisParams
from gcms_automat.analysis.table import Analysis
from gcms_automat.xlsx_export import (ExportOptions, build_workbook, format_mean_sd, replicate_stats,
                                      save_workbook, sheet_title)

from synthetic import A, B, make_run

NOW = datetime(2026, 11, 20, 9, 30, 0, tzinfo=timezone(timedelta(hours=1)))
FILES = [{"name": n, "role": "sample"} for n in ("v1_a", "v1_b", "v2_a", "v2_b")]


@pytest.fixture(scope="module")
def analysis():
    # Compound A in all 4 runs; compound B only in v1_a and v1_b (ND in group v2).
    runs = [make_run("v1_a", [(A, 3.0, 1e5, 0.02), (B, 5.0, 5e4, 0.02)], seed=1),
            make_run("v1_b", [(A, 3.0, 1.2e5, 0.02), (B, 5.0, 6e4, 0.02)], seed=2),
            make_run("v2_a", [(A, 3.0, 2e5, 0.02)], seed=3),
            make_run("v2_b", [(A, 3.0, 2.2e5, 0.02)], seed=4)]
    a = Analysis(runs, [], AnalysisParams())
    note_row = next(r for r in a.rows if abs(r.rt - 3.0) < 0.02)
    a.set_note(note_row.uid, "=SUM(A1:A9)")   # must stay plain text in Excel
    return a


def export(analysis, **kw):
    options = ExportOptions(**kw)
    buffer = io.BytesIO()
    build_workbook(analysis, AnalysisParams(), [], FILES, options, now=NOW).save(buffer)
    buffer.seek(0)
    return load_workbook(buffer)


def rows_by_id(ws):
    header = [c.value for c in ws[1]]
    return header, {row[0]: dict(zip(header, row)) for row in ws.iter_rows(min_row=2, values_only=True)}


def test_info_sheet_has_name_version_time_parameters_and_methods(analysis):
    wb = export(analysis)
    assert wb.sheetnames[0] == "Info"
    values = [c for row in wb["Info"].iter_rows(values_only=True) for c in row if c is not None]
    assert APP_NAME in values and __version__ in values
    assert "2026-11-20T09:30:00+01:00" in values
    assert "min_snr" in values                       # every parameter is listed (rule 7)
    assert any("trapezoidal rule" in str(v) for v in values)
    assert any("arPLS" in str(v) for v in values)
    assert any("Savitzky" in str(v) for v in values)
    assert "pybaselines" in values and "openpyxl" in values


def test_missing_value_sheets(analysis):
    wb = export(analysis, markers=["nd", "zero", "blank", "custom"], custom_text="<LOQ")
    assert wb.sheetnames[1:5] == ["Plochy (ND)", "Plochy (0)", "Plochy (prázdné)", "Plochy (<LOQ)"]
    b_id = next(int(r.label) for r in analysis.rows if abs(r.rt - 5.0) < 0.02)
    expected = {"Plochy (ND)": "ND", "Plochy (0)": 0, "Plochy (prázdné)": None, "Plochy (<LOQ)": "<LOQ"}
    for sheet, marker in expected.items():
        header, rows = rows_by_id(wb[sheet])
        assert header[5] == "n (z 4)"
        assert rows[b_id]["v2_a"] == marker and rows[b_id]["v1_a"] > 0


def test_note_starting_with_equals_is_text_not_formula(analysis):
    wb = export(analysis)
    _, rows = rows_by_id(wb["Plochy (ND)"])
    a_id = next(int(r.label) for r in analysis.rows if abs(r.rt - 3.0) < 0.02)
    assert rows[a_id]["Poznámka"].startswith("=SUM")
    cell = next(c for c in wb["Plochy (ND)"]["G"] if c.value and str(c.value).startswith("=SUM"))
    assert cell.data_type == "s"


def test_replicate_means_known_values(analysis):
    wb = export(analysis, markers=[], mean_formats=["mean", "mean_pm_sd", "mean_sd_columns"])
    a_row = next(r for r in analysis.rows if abs(r.rt - 3.0) < 0.02)
    b_row = next(r for r in analysis.rows if abs(r.rt - 5.0) < 0.02)
    v1 = [a_row.cells["v1_a"].area, a_row.cells["v1_b"].area]
    # Known result computed by hand: mean = (x1 + x2) / 2, SD = |x1 - x2| / sqrt(2).
    mean, sd = (v1[0] + v1[1]) / 2, abs(v1[0] - v1[1]) / np.sqrt(2)
    a_id, b_id = int(a_row.label), int(b_row.label)
    _, rows = rows_by_id(wb["Průměry"])
    assert rows[a_id]["v1 (n=2)"] == round(mean)
    assert rows[b_id]["v2 (n=2)"] == "ND"          # B missing in group v2 -> ND
    _, rows = rows_by_id(wb["Průměr a SD"])
    assert rows[a_id]["v1 průměr (n=2)"] == round(mean)
    assert rows[a_id]["v1 SD"] == round(sd)
    _, rows = rows_by_id(wb["Průměr ± SD"])
    assert rows[a_id]["v1 (n=2)"] == format_mean_sd(mean, sd)


def test_replicate_stats_rules():
    assert replicate_stats([10.0, 12.0]) == pytest.approx((11.0, np.sqrt(2.0)))   # SD with n - 1
    assert replicate_stats([10.0, None]) == (None, None)                         # one ND -> ND
    assert replicate_stats([7.0]) == (7.0, None)                                  # single run: no SD


def test_format_mean_sd_rounding():
    assert format_mean_sd(1234567.0, 45678.0) == "1 235 000 ± 46 000"
    assert format_mean_sd(1.23456, 0.0123) == "1,235 ± 0,012"
    assert format_mean_sd(100.0, None) == "100"


def test_sheet_title_is_valid_and_unique():
    used = set()
    assert sheet_title("Plochy (a/b:c)", used) == "Plochy (a_b_c)"
    assert sheet_title("Plochy (a/b:c)", used) == "Plochy (a_b_c) (2)"
    assert len(sheet_title("x" * 60, used)) == 31


def test_control_characters_are_removed(analysis):
    row = next(r for r in analysis.rows if abs(r.rt - 5.0) < 0.02)
    analysis.set_note(row.uid, "vlozeno\x0bz Wordu")
    wb = export(analysis)
    _, rows = rows_by_id(wb["Plochy (ND)"])
    assert rows[int(row.label)]["Poznámka"] == "vlozenoz Wordu"
    analysis.set_note(row.uid, "")


def test_custom_text_equal_to_builtin_marker_is_refused(analysis):
    for text in ("ND", "nd", "0"):
        with pytest.raises(ValueError):
            export(analysis, markers=["custom"], custom_text=text)


def test_info_records_computation_time_and_warns_after_changes(analysis):
    computed = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone(timedelta(hours=1)))
    buffer = io.BytesIO()
    build_workbook(analysis, AnalysisParams(), [], FILES, ExportOptions(), now=NOW,
                   computed_at=computed, changed_since=True).save(buffer)
    buffer.seek(0)
    values = [c for row in load_workbook(buffer)["Info"].iter_rows(values_only=True) for c in row if c is not None]
    assert "2026-11-20T08:00:00+01:00" in values and "2026-11-20T09:30:00+01:00" in values
    assert "Pozor" in values


def test_invalid_options_are_refused(analysis):
    with pytest.raises(ValueError):
        export(analysis, markers=["custom"], custom_text="")
    with pytest.raises(ValueError):
        export(analysis, markers=[], mean_formats=[])


def test_only_visible_rows_and_provenance(analysis):
    wb = export(analysis, provenance=True)
    _, prov = rows_by_id(wb["Původ hodnot"])
    assert "Původ hodnot" in wb.sheetnames and prov
    params_hide = AnalysisParams(hide_base_ions=[91])     # hides compound B
    buffer = io.BytesIO()
    build_workbook(analysis, params_hide, [], FILES, ExportOptions(), now=NOW).save(buffer)
    buffer.seek(0)
    _, rows = rows_by_id(load_workbook(buffer)["Plochy (ND)"])
    assert len(rows) == len(analysis.rows) - 1


def test_save_is_atomic_and_unique(analysis, tmp_path):
    wb = build_workbook(analysis, AnalysisParams(), [], FILES, ExportOptions(), now=NOW)
    first = save_workbook(wb, tmp_path, now=NOW)
    second = save_workbook(wb, tmp_path, now=NOW)
    assert first != second and first.exists() and second.exists()
    assert not list(tmp_path.glob("*.part"))


def test_poor_match_ignores_nd_cells(analysis):
    # Compound B is ND in v2_a/v2_b: its worst similarity comes only from v1_a/v1_b.
    b = next(r for r in analysis.rows if abs(r.rt - 5.0) < 0.02)
    assert b.min_similarity > 0.99

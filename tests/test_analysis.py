"""Tests of the GC-MS computation on synthetic data with known results."""

import math

import numpy as np
import pytest

from gcms_automat.analysis.cdf import read_cdf, write_cdf
from gcms_automat.analysis.params import AnalysisParams, parse_ions
from gcms_automat.analysis.retention import Alkane, find_alkanes, parse_alkane_table, retention_index
from gcms_automat.analysis.signal import estimate_noise
from gcms_automat.analysis.spectra import MzAxis, similarity
from gcms_automat.analysis.table import Analysis, EditError, replicate_group, view_filter

from synthetic import A, B, C, CO2, alkane_compound, gaussian_area, make_run

SIGMA = 0.02  # peak sigma [min] = 1.2 s (typical capillary GC peak)


def params(**kw):
    return AnalysisParams(**kw)


def row_near(analysis, rt, tol=0.02):
    rows = [r for r in analysis.rows if abs(r.rt - rt) < tol and not r.deleted]
    assert len(rows) == 1, f"expected one row at {rt}, got {[r.rt for r in rows]}"
    return rows[0]


# ---------------------------------------------------------------- reading files
def test_cdf_round_trip(tmp_path):
    # Known content: 3 scans; m/z 43.1 and 42.9 both round to 43 and are summed.
    rt = np.array([1.0, 1.01, 1.02])
    scans = [(np.array([43.1, 42.9, 57.0]), np.array([10.0, 5.0, 7.0])),
             (np.array([91.0]), np.array([3.0])), (np.array([43.0]), np.array([1.0]))]
    path = tmp_path / "x.CDF"
    write_cdf(path, rt, scans, title="test")
    run = read_cdf(path.read_bytes(), "x")
    assert np.allclose(run.rt_min, rt)
    assert run.title == "test"
    assert run.tic().tolist() == [22.0, 3.0, 1.0]
    assert run.spectra[0, 43 - run.mz_min] == 15.0


def test_non_cdf_is_rejected():
    with pytest.raises(ValueError):
        read_cdf(b"this is not a netCDF file", "bad")


# ---------------------------------------------------------------- signal
def test_noise_estimate_of_white_noise():
    # Known sd 50; MAD estimate from 20 000 points: tolerance 5 % (sampling error ~1 %).
    y = np.random.default_rng(1).normal(0, 50, 20000)
    assert estimate_noise(y) == pytest.approx(50, rel=0.05)


def test_gaussian_peak_area_matches_formula():
    # One peak with known area. The window ends where the signal falls to 5 % of
    # the height (+-2.45 sigma), which cuts off 1.4 % of a Gaussian's area;
    # tolerance 2 %.
    run = make_run("s1", [(A, 3.0, 1e5, SIGMA)])
    analysis = Analysis([run], [], params())
    row = row_near(analysis, 3.0)
    expected = gaussian_area(1e5, SIGMA, A)
    assert row.cells["s1"].area == pytest.approx(expected, rel=0.02)
    assert row.rt == pytest.approx(3.0, abs=0.003)  # within half a scan


@pytest.mark.parametrize("height", [200.0, 1000.0, 1e5])
def test_small_peaks_are_not_inflated_by_noise(height):
    # TIC S/N of the 200-count peak is ~40; even with a low detection limit (S/N 3)
    # the baseline must run through the middle of the noise. Known area; tolerance
    # 5 % (integrated noise scatter of the smallest peak ~2 %, Gaussian tail cut 1.4 %).
    for seed in range(3):
        analysis = Analysis([make_run("s", [(A, 3.0, height, SIGMA)], seed=seed)], [], params(min_snr=3))
        row = row_near(analysis, 3.0, tol=0.03)
        assert row.cells["s"].area == pytest.approx(gaussian_area(height, SIGMA, A), rel=0.05)


def test_small_peak_next_to_a_big_one():
    # A big peak must not lift the baseline under its small neighbour (0.3 min away).
    for seed in range(3):
        run = make_run("s", [(A, 3.0, 1000.0, SIGMA), (B, 3.3, 1e5, SIGMA)], seed=seed)
        row = row_near(Analysis([run], [], params(min_snr=3)), 3.0, tol=0.03)
        assert row.cells["s"].area == pytest.approx(gaussian_area(1000.0, SIGMA, A), rel=0.03)


def test_similarity_properties():
    axis = MzAxis(35, 300)
    a = np.zeros(axis.size); a[43 - 35] = 100; a[57 - 35] = 50
    b = np.zeros(axis.size); b[91 - 35] = 100
    assert similarity(a, a, axis) == pytest.approx(1.0)
    assert similarity(a, a * 0.3, axis) == pytest.approx(1.0)   # scale-invariant
    assert similarity(a, b, axis) == 0.0                         # no common ion


# ---------------------------------------------------------------- alignment
def three_runs(shifts=(0.0, 0.01, -0.01)):
    return [make_run(f"r{i}", [(A, 3.0 + s, 1e5, SIGMA), (B, 5.0 + s, 8e4, SIGMA), (C, 5.15 + s, 6e4, SIGMA)],
                     seed=i) for i, s in enumerate(shifts)]


def test_alignment_groups_shifted_peaks():
    analysis = Analysis(three_runs(), [], params())
    # Exactly 3 compounds and nothing else (no baseline artefacts next to big peaks).
    assert len(analysis.rows) == 3
    for rt in (3.0, 5.0, 5.15):
        row = row_near(analysis, rt)
        assert row.n_found == 3
        assert row.min_similarity > 0.99
    assert analysis.overlap_problems() == []


def test_same_rt_different_spectrum_is_not_merged():
    runs = [make_run("r0", [(A, 3.0, 1e5, SIGMA)]), make_run("r1", [(B, 3.0, 1e5, SIGMA)], seed=1)]
    analysis = Analysis(runs, [], params())
    assert len([r for r in analysis.rows if abs(r.rt - 3.0) < 0.02]) == 2


def test_co2_noise_is_dropped():
    analysis = Analysis([make_run("r0", [(CO2, 2.0, 1e5, SIGMA), (A, 3.0, 1e5, SIGMA)])], [], params())
    assert analysis.stats["co2"] == 1
    assert all(abs(r.rt - 2.0) > 0.05 for r in analysis.rows)


def test_co2_filter_can_be_switched_off():
    analysis = Analysis([make_run("r0", [(CO2, 2.0, 1e5, SIGMA)])], [], params(co2_filter=False))
    row_near(analysis, 2.0)


# ---------------------------------------------------------------- replicates
def test_replicate_group_names():
    assert replicate_group("vzorek_1_a") == "vzorek_1"
    assert replicate_group("ryby313_RK6_0M_A") == "ryby313_RK6_0M"
    assert replicate_group("blank") == "blank"   # no separator -> not a replicate letter


def test_missing_replicate_is_filled_when_a_real_peak_is_there():
    # Detection needs S/N 50 here; the small peak in s_b (S/N ~20) is not detected,
    # but it is above the fill limit (S/N 3), so it must be filled in.
    big = make_run("s_a", [(A, 3.0, 1e5, SIGMA)])
    small = make_run("s_b", [(A, 3.0, 100.0, SIGMA)], seed=3)
    analysis = Analysis([big, small], [], params(min_snr=50))
    cell = row_near(analysis, 3.0).cells["s_b"]
    assert cell.status == "fill"
    # Small peak (S/N ~20): integrated noise gives a few % scatter -> tolerance 10 %.
    assert cell.area == pytest.approx(gaussian_area(100.0, SIGMA, A), rel=0.10)


def test_missing_replicate_stays_nd_without_peak():
    analysis = Analysis([make_run("s_a", [(A, 3.0, 1e5, SIGMA)]), make_run("s_b", [], seed=3)], [], params())
    cell = row_near(analysis, 3.0).cells["s_b"]
    assert cell.status == "ND" and cell.reason


# ---------------------------------------------------------------- retention index
def test_retention_index_formula():
    alk = [Alkane(10, 4.0), Alkane(11, 6.0), Alkane(13, 10.0)]
    assert retention_index(5.0, alk) == pytest.approx(1050.0)     # halfway C10-C11
    assert retention_index(8.0, alk) == pytest.approx(1200.0)     # halfway C11-C13 (2 carbons)
    assert math.isnan(retention_index(3.0, alk))                  # before the first alkane


def test_parse_alkane_table_formats():
    text = "C;RT\nC10;4,000\nC11\t6.5\n12 8,25\n"
    alk = parse_alkane_table(text)
    assert [(a.carbons, a.rt) for a in alk] == [(10, 4.0), (11, 6.5), (12, 8.25)]


def test_find_alkanes_in_standard_run():
    run = make_run("alkany", [(alkane_compound(n), 2.0 + (n - 10), 1e5, SIGMA) for n in (10, 11, 12)])
    axis = MzAxis.covering([run])
    found = find_alkanes([run], axis, 1.75, 5)
    assert [(a.carbons, round(a.rt, 2)) for a in found] == [(10, 2.0), (11, 3.0), (12, 4.0)]


# ---------------------------------------------------------------- manual edits
def test_window_overlapping_neighbour_is_refused():
    analysis = Analysis(three_runs(), [], params())
    b, c = row_near(analysis, 5.0), row_near(analysis, 5.15)
    with pytest.raises(EditError):
        analysis.set_window(b.uid, b.cells["r0"].t0, c.cells["r0"].t1)
    assert analysis.overlap_problems() == []


def test_split_labels_use_underscore_and_areas_add_up():
    analysis = Analysis(three_runs(), [], params())
    row = row_near(analysis, 3.0)
    total = row.cells["r0"].area
    parts = analysis.split(row.uid, 3.0)
    assert [p.label for p in parts] == [f"{row.label}_1", f"{row.label}_2"]
    # The trapezoidal rule with interpolated edges is additive: parts sum to the whole.
    assert sum(p.cells["r0"].area for p in parts) == pytest.approx(total, rel=1e-9)
    assert analysis.overlap_problems() == []


def test_merge_integrates_the_union_window_and_undo_restores():
    from gcms_automat.analysis.signal import integrate_window
    analysis = Analysis(three_runs(), [], params())
    b, c = row_near(analysis, 5.0), row_near(analysis, 5.15)
    union = (b.cells["r0"].t0, c.cells["r0"].t1)
    parts_sum = b.cells["r0"].area + c.cells["r0"].area
    n_rows = len(analysis.rows)
    merged = analysis.merge([b.uid, c.uid])
    # Exactly the area of the union window; the gap between the two peaks holds only
    # baseline noise, so it is also the sum of both peaks within 1 %.
    assert merged.cells["r0"].area == pytest.approx(integrate_window(analysis.data["r0"].trace, *union), rel=1e-12)
    assert merged.cells["r0"].area == pytest.approx(parts_sum, rel=0.01)
    assert len(analysis.rows) == n_rows - 1
    analysis.undo()
    assert len(analysis.rows) == n_rows


def test_restoring_a_deleted_row_cannot_create_overlap():
    analysis = Analysis(three_runs(), [], params())
    b, c = row_near(analysis, 5.0), row_near(analysis, 5.15)
    analysis.set_deleted(c.uid, True)
    analysis.set_window(b.uid, b.cells["r0"].t0, c.cells["r0"].t1)   # allowed: c is deleted
    with pytest.raises(EditError):
        analysis.set_deleted(c.uid, False)


# ---------------------------------------------------------------- view filters
def test_view_filters():
    runs = three_runs() + [make_run("r3", [(A, 3.0, 1e5, SIGMA), (C, 8.0, 5e3, SIGMA)], seed=9)]
    analysis = Analysis(runs, [], params(fill_replicates=False))
    small = row_near(analysis, 8.0)
    # Hide by base ion 91 (compound B).
    reasons = view_filter(analysis.rows, params(hide_base_ions=[91]))
    assert reasons[row_near(analysis, 5.0).uid].startswith("základní iont")
    # Small-peak filter needs BOTH conditions.
    assert view_filter(analysis.rows, params(small_max_detections=2, small_max_area=1e9))[small.uid]
    assert not view_filter(analysis.rows, params(small_max_detections=2, small_max_area=1.0))[small.uid]
    # Top N by largest area.
    top = view_filter(analysis.rows, params(top_n=1))
    assert sum(1 for v in top.values() if not v) == 1


def test_parse_ions_input():
    assert parse_ions("207, 281;355 207") == [207, 281, 355]
    with pytest.raises(ValueError):
        parse_ions("-5")


def test_params_from_user_input_ignore_invalid_values():
    p = AnalysisParams.from_dict({"min_snr": "abc", "rt_tolerance_min": "0.05", "co2_filter": "false",
                                  "min_similarity": 5})
    assert p.min_snr == 10.0 and p.rt_tolerance_min == 0.05 and p.co2_filter is False
    assert p.min_similarity == 0.70  # out of range 0-1 -> default kept

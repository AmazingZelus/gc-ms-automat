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

from synthetic import A, B, C, CO2, Compound, alkane_compound, gaussian_area, make_run

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
    # One peak with known area. The window ends where the signal falls to 1 % of
    # the height (+-2.9 sigma), which cuts off 0.4 % of a Gaussian's area;
    # tolerance 1 %.
    run = make_run("s1", [(A, 3.0, 1e5, SIGMA)])
    analysis = Analysis([run], [], params())
    row = row_near(analysis, 3.0)
    expected = gaussian_area(1e5, SIGMA, A)
    assert row.cells["s1"].area == pytest.approx(expected, rel=0.01)
    assert row.rt == pytest.approx(3.0, abs=0.003)  # within half a scan


@pytest.mark.parametrize("height,single_tol,mean_tol", [(200.0, 0.15, 0.03), (1000.0, 0.05, 0.01), (1e5, 0.01, 0.005)])
def test_peak_areas_have_no_bias(height, single_tol, mean_tol):
    # Known area, 20 noise realisations, low detection limit (S/N 3). The 200-count
    # peak has TIC S/N ~10 (scatter ~4 %): each run within 15 %, but the MEAN (= bias)
    # within 3 %. Larger peaks: tighter. Window cut at 1 % height leaves out 0.4 %.
    ratios = []
    for seed in range(20):
        analysis = Analysis([make_run("s", [(A, 3.0, height, SIGMA)], seed=seed)], [], params(min_snr=3))
        ratios.append(row_near(analysis, 3.0, tol=0.03).cells["s"].area / gaussian_area(height, SIGMA, A))
    assert all(abs(r - 1) < single_tol for r in ratios)
    assert abs(np.mean(ratios) - 1) < mean_tol


def test_peaks_on_a_broad_hump_get_their_own_area():
    # Reviewer case: a broad hump (sigma 0.4 min, 5000 counts) with two small peaks
    # on it. With the hump counted they came out 10-15x too large. Known areas;
    # tolerance 15 % (the hump's slope under the peak foot is not exactly linear).
    hump = Compound({300: 100})
    for seed in range(3):
        run = make_run("h", [(hump, 10.0, 5000, 0.4), (B, 9.8, 3000, SIGMA), (C, 10.3, 3000, SIGMA)], minutes=20, seed=seed)
        analysis = Analysis([run], [], params())
        assert row_near(analysis, 9.8).cells["h"].area == pytest.approx(gaussian_area(3000, SIGMA, B), rel=0.15)
        assert row_near(analysis, 10.3).cells["h"].area == pytest.approx(gaussian_area(3000, SIGMA, C), rel=0.15)


def test_tailing_peak_area_tradeoff_is_as_documented():
    # Documented trade-off of the 5 % slope end (params.py): a tailing EMG peak with
    # tau/sigma = 1.5 loses about 4 % of its tail, with the slope end off (0) ~0 %.
    run = make_run("e", [(B, 5.0, 1e6, SIGMA, 0.03)], baseline=5000, noise=50)
    default = row_near(Analysis([run], [], params()), 5.0, tol=0.05).cells["e"].area
    no_slope = row_near(Analysis([run], [], params(window_end_slope_pct=0)), 5.0, tol=0.05).cells["e"].area
    expected = gaussian_area(1e6, SIGMA, B)
    assert default / expected == pytest.approx(0.956, abs=0.02)
    assert no_slope / expected == pytest.approx(1.0, abs=0.01)


def test_small_peak_next_to_a_big_one():
    # A big peak must not lift the baseline under its small neighbour (0.3 min away).
    for seed in range(3):
        run = make_run("s", [(A, 3.0, 1000.0, SIGMA), (B, 3.3, 1e5, SIGMA)], seed=seed)
        row = row_near(Analysis([run], [], params(min_snr=3)), 3.0, tol=0.03)
        assert row.cells["s"].area == pytest.approx(gaussian_area(1000.0, SIGMA, A), rel=0.03)


def test_tailing_peak_and_small_neighbour():
    # Reviewer case: tailing big peak (EMG, tau 0.1 min) on a 5000-count baseline and
    # a small Gaussian 0.25 min before it. Known areas; tolerance 3 % (window end at
    # 1 % of the height leaves out ~0.4 % of a Gaussian, more of a tail).
    from synthetic import peak_shape
    for seed in range(3):
        run = make_run("s", [(A, 4.75, 3e4, SIGMA), (B, 5.0, 1e6, SIGMA, 0.1)], baseline=5000, noise=50, seed=seed)
        analysis = Analysis([run], [], params())
        small = row_near(analysis, 4.75, tol=0.03)
        assert small.cells["s"].area == pytest.approx(gaussian_area(3e4, SIGMA, A), rel=0.03)


def test_no_negative_areas_in_crowded_region_with_drift():
    # Cluster of 5 overlapping peaks on a drifting baseline: every area must be
    # positive and the sum within 3 % of the known total.
    cluster = [(A, 6.0, 5e4, 0.025), (B, 6.08, 3e4, 0.025), (C, 6.17, 8e4, 0.025), (A, 6.25, 2e4, 0.025), (B, 6.4, 6e4, 0.025)]
    run = make_run("s", cluster, baseline=2000, drift=300, noise=30)
    analysis = Analysis([run], [], params())
    areas = [r.cells["s"].area for r in analysis.rows if 5.9 < r.rt < 6.5]
    assert all(a > 0 for a in areas)
    expected = sum(gaussian_area(h, s, c) for c, _, h, s in cluster)
    assert sum(areas) == pytest.approx(expected, rel=0.03)


def test_filled_replicate_is_not_biased():
    # Reviewer case: the small peak in s_b is below 0.2 % of its run maximum, so it is
    # not detected there, only filled in. It must not come out systematically low
    # (previous baseline: -6 to -7 %). Tolerance 3 % per seed, mean within 1.5 %.
    ratios = []
    for seed in range(6):
        s_a = make_run("s_a", [(A, 3.0, 1e4, SIGMA), (B, 6.0, 2e6, SIGMA)], seed=seed)
        s_b = make_run("s_b", [(A, 3.0, 3e3, SIGMA), (B, 6.0, 2e6, SIGMA)], seed=seed + 10)
        cell = row_near(Analysis([s_a, s_b], [], params()), 3.0).cells["s_b"]
        assert cell.status == "fill"
        ratios.append(cell.area / gaussian_area(3e3, SIGMA, A))
    assert all(abs(r - 1) < 0.03 for r in ratios)
    assert abs(np.mean(ratios) - 1) < 0.015


def test_height_threshold_ignores_peaks_outside_rt_range():
    # A huge solvent peak at 1 min, outside rt_min = 2, must not raise the 0.2 % threshold.
    run = make_run("s", [(C, 1.0, 5e7, SIGMA), (A, 4.0, 5e4, SIGMA)])
    analysis = Analysis([run], [], params(rt_min=2.0))
    row_near(analysis, 4.0)


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
    found = find_alkanes([run], axis, 7.0, 5)
    assert [(a.carbons, round(a.rt, 2)) for a in found] == [(10, 2.0), (11, 3.0), (12, 4.0)]


def test_alkane_fragment_isotopes_are_not_read_as_molecular_ions():
    # C10-C20; long alkanes have a weak M+ (0.2 % < 0.3 % limit). Their C(n)H(2n+1)+
    # fragments carry 13C isotope peaks exactly at the M+ of shorter alkanes. Known
    # result: C10-C16 found with the right carbon numbers, nothing mislabelled.
    peaks = [(alkane_compound(n, 2.0 if n <= 16 else 0.2), 2.0 + (n - 10) * 0.8, 1e5, SIGMA) for n in range(10, 21)]
    run = make_run("alkany", peaks, minutes=12)
    found = find_alkanes([run], MzAxis.covering([run]), 7.0, 5)
    assert [(a.carbons, round(a.rt, 1)) for a in found] == [(n, round(2.0 + (n - 10) * 0.8, 1)) for n in range(10, 17)]


def test_check_alkanes():
    from gcms_automat.analysis.retention import check_alkanes
    assert check_alkanes([Alkane(10, 5.0), Alkane(11, 7.0)]) == ""
    assert "opakuje" in check_alkanes([Alkane(10, 5.0), Alkane(10, 9.0)])
    assert "stoupat" in check_alkanes([Alkane(10, 5.0), Alkane(12, 7.0), Alkane(11, 9.0)])


# ---------------------------------------------------------------- manual edits
def test_window_over_a_neighbour_is_clipped_and_inside_it_refused():
    analysis = Analysis(three_runs(), [], params())
    b, c = row_near(analysis, 5.0), row_near(analysis, 5.15)
    _, clipped = analysis.set_window(b.uid, b.cells["r0"].t0 - 0.02, c.cells["r0"].t1)
    assert set(clipped) == {"r0", "r1", "r2"}
    assert analysis.overlap_problems() == []
    with pytest.raises(EditError):      # completely inside the neighbour's window
        analysis.set_window(b.uid, 5.14, 5.16)


def test_window_follows_each_runs_retention_shift():
    # Runs shifted by 0, +0.01, -0.01 min: a window drawn around the mean RT is moved
    # by each run's own shift, so every run keeps the whole peak (same area as before).
    analysis = Analysis(three_runs(), [], params())
    a = row_near(analysis, 3.0)
    before = {n: c.area for n, c in a.cells.items()}
    analysis.set_window(a.uid, a.rt - 0.1, a.rt + 0.1)
    for n, c in row_near(analysis, 3.0).cells.items():
        assert c.area == pytest.approx(before[n], rel=0.01)


def test_window_for_one_sample_only():
    analysis = Analysis(three_runs(), [], params())
    a = row_near(analysis, 3.0)
    other = a.cells["r1"].t0
    analysis.set_window(a.uid, 2.95, 3.05, samples=["r0"])
    row = row_near(analysis, 3.0)
    assert row.cells["r0"].t0 == pytest.approx(2.95) and row.cells["r1"].t0 == other


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


def test_deleted_rows_cannot_be_edited():
    analysis = Analysis(three_runs(), [], params())
    b, c = row_near(analysis, 5.0), row_near(analysis, 5.15)
    analysis.set_deleted(c.uid, True)
    analysis.set_window(b.uid, b.cells["r0"].t0, c.cells["r0"].t1)
    for edit in (lambda: analysis.split(c.uid, 5.15), lambda: analysis.set_window(c.uid, 5.1, 5.2),
                 lambda: analysis.fill_missing(c.uid)):
        with pytest.raises(EditError):
            edit()
    assert analysis.overlap_problems() == []


def test_random_edit_sequences_never_create_overlaps():
    # Fuzz test: 300 random edits (window, split, merge, fill, delete, restore, undo);
    # refused edits are fine, but the no-overlap rule must hold after every step.
    rng = np.random.default_rng(42)
    analysis = Analysis(three_runs(), [], params())
    for _ in range(300):
        rows = analysis.rows
        r = rows[int(rng.integers(len(rows)))]
        t = float(rng.uniform(2.8, 5.4))
        action = int(rng.integers(7))
        try:
            if action == 0:
                analysis.set_window(r.uid, t, t + float(rng.uniform(0.01, 0.3)))
            elif action == 1:
                analysis.split(r.uid, r.rt + float(rng.normal(0, 0.02)))
            elif action == 2:
                other = rows[int(rng.integers(len(rows)))]
                analysis.merge([r.uid, other.uid])
            elif action == 3:
                analysis.fill_missing(r.uid)
            elif action == 4:
                analysis.set_deleted(r.uid, True)
            elif action == 5:
                analysis.set_deleted(r.uid, False)
            else:
                analysis.undo()
        except EditError:
            pass
        assert analysis.overlap_problems() == []


def test_undo_uses_current_alkanes_for_ri():
    analysis = Analysis(three_runs(), [Alkane(10, 2.0), Alkane(11, 4.0)], params())
    row = row_near(analysis, 3.0)
    analysis.set_note(row.uid, "x")
    analysis.alkanes = [Alkane(10, 2.0), Alkane(12, 4.0)]
    analysis.undo()
    assert row_near(analysis, 3.0).ri == pytest.approx(1100, abs=1)   # halfway C10-C12


def test_invalid_parameter_keeps_previous_value():
    base = AnalysisParams(min_similarity=0.8)
    rejected = []
    p = AnalysisParams.from_dict({"min_similarity": 1.5}, base=base, rejected=rejected)
    assert p.min_similarity == 0.8 and rejected


def test_damaged_cdf_files_are_rejected(tmp_path):
    rt = np.array([1.0, 1.01])
    cases = {"nan": [(np.array([np.nan]), np.array([1.0])), (np.array([43.0]), np.array([1.0]))],
             "huge": [(np.array([1e9]), np.array([1.0])), (np.array([43.0]), np.array([1.0]))]}
    for name, scans in cases.items():
        write_cdf(tmp_path / f"{name}.CDF", rt, scans)
        with pytest.raises(ValueError):
            read_cdf((tmp_path / f"{name}.CDF").read_bytes(), name)
    write_cdf(tmp_path / "time.CDF", np.array([1.0, 0.9]), cases["nan"][1:] * 2)
    with pytest.raises(ValueError):
        read_cdf((tmp_path / "time.CDF").read_bytes(), "time")


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

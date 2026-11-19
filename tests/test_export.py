"""Export tests on synthetic data with known results."""

from datetime import datetime, timedelta, timezone
from io import StringIO

import pandas as pd
import pytest

from gcms_automat import APP_NAME, __version__
from gcms_automat.export import make_test_table, write_csv_export

FIXED_TIME = datetime(2026, 11, 19, 10, 15, 3, tzinfo=timezone(timedelta(hours=1)))


def read_back(path, sep, decimal):
    # This reads the CSV the same way a user's script would (skipping '#' lines).
    text = path.read_text(encoding="utf-8-sig")
    return text, pd.read_csv(StringIO(text), comment="#", sep=sep, decimal=decimal)


def test_header_contains_name_version_and_time(tmp_path):
    path = write_csv_export(make_test_table(), tmp_path, "t", "cz", now=FIXED_TIME)
    text, _ = read_back(path, ";", ",")
    lines = text.splitlines()
    assert lines[0] == f"# app: {APP_NAME}"
    assert lines[1] == f"# version: {__version__}"
    assert lines[2] == "# processed_at: 2026-11-19T10:15:03+01:00"
    assert any(line.startswith("# lib.numpy: ") for line in lines)


@pytest.mark.parametrize("fmt,sep,decimal", [("cz", ";", ","), ("intl", ",", ".")])
def test_known_values_round_trip(tmp_path, fmt, sep, decimal):
    # Known result: x = 0..4, x^2 = 0,1,4,9,16, x/2 = 0,0.5,1,1.5,2
    path = write_csv_export(make_test_table(), tmp_path, "t", fmt, now=FIXED_TIME)
    _, table = read_back(path, sep, decimal)
    assert table["x"].tolist() == [0, 1, 2, 3, 4]
    assert table["x_squared"].tolist() == [0, 1, 4, 9, 16]
    assert table["x_half"].tolist() == [0.0, 0.5, 1.0, 1.5, 2.0]


def test_czech_format_uses_decimal_comma(tmp_path):
    path = write_csv_export(make_test_table(), tmp_path, "t", "cz", now=FIXED_TIME)
    assert "1;1;0,5" in path.read_text(encoding="utf-8-sig")


def test_file_has_bom_for_excel(tmp_path):
    path = write_csv_export(make_test_table(), tmp_path, "t", "cz", now=FIXED_TIME)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_no_overwrite_when_same_timestamp(tmp_path):
    first = write_csv_export(make_test_table(), tmp_path, "t", "cz", now=FIXED_TIME)
    second = write_csv_export(make_test_table(), tmp_path, "t", "cz", now=FIXED_TIME)
    assert first != second and first.exists() and second.exists()


def test_unknown_format_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        write_csv_export(make_test_table(), tmp_path, "t", "xx")

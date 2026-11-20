"""The analysis API end to end, with synthetic .CDF files (known peaks)."""

import io

import numpy as np
import pytest

from gcms_automat.analysis.cdf import write_cdf
from gcms_automat.lifecycle import ClientTracker
from gcms_automat.server import create_app
from gcms_automat.session import Session

from synthetic import A, B, C, make_run

TOKEN, PORT = "t", 8765
BASE = f"http://127.0.0.1:{PORT}"
H = {"X-App-Token": TOKEN}


def cdf_bytes(run, tmp_path):
    # This writes a synthetic run as a real .CDF file and returns its bytes.
    scans = []
    dense = run.spectra.toarray()
    for row in dense:
        nz = np.flatnonzero(row)
        scans.append((run.mz_min + nz, row[nz]))
    path = tmp_path / f"{run.name}.CDF"
    write_cdf(path, run.rt_min, scans)
    return path.read_bytes()


@pytest.fixture
def client(tmp_path):
    app = create_app(token=TOKEN, tracker=ClientTracker(), port=PORT, exports_dir=tmp_path, session=Session())
    c = app.test_client()
    runs = [make_run(n, [(A, 3.0, 1e5, 0.02), (B, 5.0, 8e4, 0.02), (C, 5.15, 6e4, 0.02)], minutes=7, seed=i)
            for i, n in enumerate(["s1_a", "s1_b", "s2_a"])]
    data = {"files": [(io.BytesIO(cdf_bytes(r, tmp_path)), r.name + ".CDF") for r in runs]}
    r = c.post("/api/files", base_url=BASE, headers=H, data=data, content_type="multipart/form-data")
    assert r.json["ok"] and len(r.json["added"]) == 3
    return c


def post(c, path, body):
    return c.post(path, base_url=BASE, headers=H, json=body)


def test_run_and_table(client):
    r = post(client, "/api/run", {"params": {}})
    assert r.json["ok"]
    table = r.json["table"]
    assert table["names"] == ["s1_a", "s1_b", "s2_a"]
    rows = [x for x in table["rows"] if not x["hidden"]]
    assert len(rows) == 3 and all(x["n"] == 3 for x in rows)


def test_detail_and_spectrum(client):
    rows = post(client, "/api/run", {"params": {}}).json["table"]["rows"]
    uid = rows[0]["uid"]
    d = client.get(f"/api/detail?uid={uid}&t0=2.5&t1=3.5", base_url=BASE, headers=H).json
    assert d["ok"] and len(d["traces"]) == 3 and d["spectrum"]["mz"]
    s = client.get(f"/api/spectrum?uid={uid}&sample=s1_b", base_url=BASE, headers=H).json
    assert s["ok"] and s["similarity"] > 0.99


def test_edits_and_undo(client):
    rows = post(client, "/api/run", {"params": {}}).json["table"]["rows"]
    b = next(x for x in rows if abs(x["rt"] - 5.0) < 0.02)
    c = next(x for x in rows if abs(x["rt"] - 5.15) < 0.02)
    r = post(client, "/api/edit", {"action": "merge", "uids": [b["uid"], c["uid"]]})
    assert r.json["ok"] and len(r.json["table"]["rows"]) == 2
    r = post(client, "/api/undo", {})
    assert r.json["ok"] and len(r.json["table"]["rows"]) == 3
    r = post(client, "/api/edit", {"action": "split", "uid": b["uid"], "at": 5.0})
    assert [x["label"] for x in r.json["table"]["rows"] if x["label"].startswith(b["label"] + "_")] == \
        [b["label"] + "_1", b["label"] + "_2"]


def test_refused_edit_gives_czech_message(client):
    rows = post(client, "/api/run", {"params": {}}).json["table"]["rows"]
    b = next(x for x in rows if abs(x["rt"] - 5.0) < 0.02)
    # A window over the neighbour is clipped (message says where) ...
    r = post(client, "/api/edit", {"action": "window", "uid": b["uid"], "t0": 4.9, "t1": 5.3})
    assert r.json["ok"] and "Oříznuto" in r.json["message"]
    # ... one completely inside the neighbour is refused with a Czech explanation.
    r = post(client, "/api/edit", {"action": "window", "uid": b["uid"], "t0": 5.14, "t1": 5.16})
    assert r.status_code == 400 and "obsazené" in r.json["error"]


def test_view_filter_does_not_recompute(client):
    post(client, "/api/run", {"params": {}})
    r = post(client, "/api/view", {"params": {"hide_base_ions": "91", "min_snr": 99}})
    rows = r.json["table"]["rows"]
    assert sum(1 for x in rows if x["hidden"]) == 1
    assert r.json["table"]["dirty"] is False  # pipeline parameter in a view call is ignored


def test_alkane_import_sets_ri(client):
    post(client, "/api/run", {"params": {}})
    r = post(client, "/api/alkanes/import", {"text": "C10;2,0\nC11;4,0\nC12;6,0"})
    assert r.json["ok"]
    rows = client.get("/api/table", base_url=BASE, headers=H).json["table"]["rows"]
    a = next(x for x in rows if abs(x["rt"] - 3.0) < 0.02)
    assert a["ri"] == pytest.approx(1050, abs=1)   # halfway between C10 (2 min) and C11 (4 min)


def test_upload_of_non_cdf_reports_error(client):
    data = {"files": [(io.BytesIO(b"nonsense"), "bad.CDF")]}
    r = client.post("/api/files", base_url=BASE, headers=H, data=data, content_type="multipart/form-data")
    assert r.json["errors"] and "bad.CDF" in r.json["errors"][0]


def test_export_and_download(client):
    post(client, "/api/run", {"params": {}})
    r = post(client, "/api/export", {"options": {"markers": ["nd", "custom"], "custom_text": "<LOQ",
                                                 "mean_formats": ["mean"]}})
    assert r.json["ok"] and r.json["filename"].endswith(".xlsx")
    d = client.get(f"/api/download?name={r.json['filename']}", base_url=BASE, headers=H)
    assert d.status_code == 200 and d.data[:2] == b"PK"          # an .xlsx is a ZIP file
    # Only plain file names from the exports folder can be downloaded.
    bad = client.get("/api/download?name=../app/main.py", base_url=BASE, headers=H)
    assert bad.status_code == 404


def test_export_with_invalid_options_explains(client):
    post(client, "/api/run", {"params": {}})
    r = post(client, "/api/export", {"options": {"markers": ["custom"], "custom_text": ""}})
    assert r.status_code == 400 and "Vlastní text" in r.json["error"]


def test_export_info_describes_the_computed_result(client, tmp_path):
    # Reviewer case: a failed re-run with other parameters and a newly uploaded file
    # must not change what the Info sheet says about the exported (old) result.
    from openpyxl import load_workbook
    post(client, "/api/run", {"params": {}})
    r = post(client, "/api/run", {"params": {"rt_min": 5, "rt_max": 4, "min_snr": 50}})
    assert r.status_code == 400
    extra = make_run("s9_a", [(A, 3.0, 1e5, 0.02)], minutes=7, seed=9)
    client.post("/api/files", base_url=BASE, headers=H, content_type="multipart/form-data",
                data={"files": [(io.BytesIO(cdf_bytes(extra, tmp_path)), "s9_a.CDF")]})
    name = post(client, "/api/export", {"options": {}}).json["filename"]
    info = load_workbook(tmp_path / name)["Info"]
    rows = {row[0]: row[1] for row in info.iter_rows(values_only=True) if row and row[0]}
    assert rows["Min. poměr signál/šum"] == 10 and rows["RT od"] == 0
    assert "s9_a" not in rows and "s1_a" in rows
    assert "Pozor" in rows

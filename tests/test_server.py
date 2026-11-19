"""API tests with Flask's test client (no real network)."""

import pytest

from gcms_automat import __version__
from gcms_automat.lifecycle import ClientTracker
from gcms_automat.server import create_app

TOKEN = "secret-token"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def client(tmp_path):
    tracker = ClientTracker()
    app = create_app(token=TOKEN, tracker=tracker, port=PORT, exports_dir=tmp_path)
    c = app.test_client()
    c.tracker = tracker
    c.exports = tmp_path
    return c


def auth():
    return {"X-App-Token": TOKEN}


def test_api_requires_token(client):
    assert client.get("/api/info", base_url=BASE).status_code == 403
    assert client.get("/api/info", base_url=BASE, headers={"X-App-Token": "wrong"}).status_code == 403


def test_wrong_host_rejected(client):
    r = client.get("/api/info", base_url="http://evil.example:8765", headers=auth())
    assert r.status_code == 403


def test_info_reports_version(client):
    r = client.get("/api/info", base_url=BASE, headers=auth())
    assert r.json["version"] == __version__


def test_export_writes_file_with_version(client):
    r = client.post("/api/export-test", base_url=BASE, headers=auth(), json={"csv_format": "intl"})
    assert r.json["ok"]
    files = list(client.exports.glob("*.csv"))
    assert len(files) == 1
    assert f"# version: {__version__}" in files[0].read_text(encoding="utf-8-sig")


def test_index_has_csp_and_no_external_urls(client):
    r = client.get("/", base_url=BASE)
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    for name in ("/", "/static/app.js", "/static/style.css"):
        body = client.get(name, base_url=BASE).get_data(as_text=True)
        assert "http://" not in body and "https://" not in body and "//cdn" not in body


def test_beacon_with_token_in_url(client):
    client.post("/api/heartbeat", base_url=BASE, headers=auth(), json={"cid": "tab1"})
    r = client.post(f"/api/closing?token={TOKEN}&cid=tab1", base_url=BASE, data="")
    assert r.status_code == 200


def test_shutdown_sets_flag(client):
    client.post("/api/shutdown", base_url=BASE, headers=auth())
    assert client.tracker.exit_reason() is not None

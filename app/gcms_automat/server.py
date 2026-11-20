"""The local web server (Flask). Serves the UI and a small JSON API.

Security for a localhost app:
  * listens only on 127.0.0.1 (not reachable from other computers),
  * every API call must carry a random token created at start, so other web
    pages open in the browser cannot control the app,
  * the Host header is checked (protects against "DNS rebinding"),
  * the Content-Security-Policy forbids loading anything from the internet.
"""

from __future__ import annotations

import os
import platform
import secrets
import subprocess
import sys

from flask import Flask, abort, jsonify, request, send_from_directory

from . import APP_NAME, __version__
from .export import CSV_FORMATS, DEFAULT_CSV_FORMAT, library_versions, make_test_table, write_csv_export
from .lifecycle import ClientTracker
from .paths import EXPORTS_DIR, STATIC_DIR
from .session import Session

# Grace period after a tab closed while a result exists [s]: long enough for the
# browser to restore an unloaded tab or for a reload; the console window stays open.
WORK_GRACE_S = 120.0

# This policy tells the browser: load scripts, styles, images and data ONLY from
# this local server. Any accidental link to a CDN or the internet is blocked.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


def create_app(token: str, tracker: ClientTracker, port: int, exports_dir=EXPORTS_DIR,
               session: Session | None = None) -> Flask:
    """Build the Flask application."""
    app = Flask(__name__, static_folder=None)
    # Uploads of many .CDF files at once (a 46-min run is ~2 MB): limit 2 GB.
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 ** 3
    from .api_analysis import create_blueprint
    session = session or Session()
    app.register_blueprint(create_blueprint(session, exports_dir))
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    # ---- This checks every request: correct Host, and the token for the API ----
    @app.before_request
    def check_request():
        if request.host not in allowed_hosts:
            abort(403)
        if request.path.startswith("/api/"):
            # sendBeacon (used when a tab closes) cannot send headers -> query param allowed.
            given = request.headers.get("X-App-Token") or request.args.get("token", "")
            # Compared as bytes, so unusual characters give 403 instead of a crash.
            if not secrets.compare_digest(given.encode("utf-8", "replace"), token.encode("utf-8")):
                abort(403)

    # ---- This adds security and no-cache headers to every response ----
    @app.after_request
    def add_headers(response):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # No caching, so a newer version never shows stale JavaScript from an older one.
        response.headers["Cache-Control"] = "no-store"
        return response

    # ---- This serves the user interface (HTML, JS, CSS - all bundled locally) ----
    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(STATIC_DIR, filename)

    # ---- This tells the UI the app name, version and library versions ----
    @app.get("/api/info")
    def info():
        return jsonify(
            app=APP_NAME,
            version=__version__,
            python=platform.python_version(),
            libraries=library_versions(),
            exports_dir=str(exports_dir),
            csv_formats=[{"key": f.key, "label": f.label} for f in CSV_FORMATS.values()],
            default_csv_format=DEFAULT_CSV_FORMAT,
        )

    # ---- This receives "I am still open" signals from browser tabs ----
    @app.post("/api/heartbeat")
    def heartbeat():
        tracker.heartbeat(_client_id())
        return jsonify(ok=True)

    @app.post("/api/closing")
    def closing():
        # With a computed result the grace period is long: a browser that only
        # unloads a background tab, or a page reload, must not cost the user's work
        # (the server keeps the result; a reopened tab shows it again).
        tracker.closing(_client_id(), WORK_GRACE_S if session.has_work else None)
        return jsonify(ok=True)

    # ---- This is the "Ukončit" button ----
    @app.post("/api/shutdown")
    def shutdown():
        tracker.request_shutdown()
        return jsonify(ok=True)

    # ---- This is the "Export test" button: writes a small CSV with the header ----
    @app.post("/api/export-test")
    def export_test():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}
        csv_format = payload.get("csv_format", DEFAULT_CSV_FORMAT)
        if not isinstance(csv_format, str) or csv_format not in CSV_FORMATS:
            return jsonify(ok=False, error=f"Neznámý formát CSV: {csv_format}"), 400
        try:
            path = write_csv_export(make_test_table(), exports_dir, "export_test", csv_format)
        except OSError as exc:
            # Typical cause: the folder is read-only (e.g. unzipped into Program Files).
            return jsonify(ok=False, error=f"Soubor nelze uložit: {exc}"), 500
        return jsonify(ok=True, path=str(path), filename=path.name)

    # ---- This opens the exports folder in Windows Explorer ----
    @app.post("/api/open-exports")
    def open_exports():
        try:
            exports_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(exports_dir)  # noqa: S606 (opens a local folder only)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(exports_dir)])
            else:
                subprocess.Popen(["xdg-open", str(exports_dir)])
        except OSError as exc:
            return jsonify(ok=False, error=str(exc)), 500
        return jsonify(ok=True)

    return app


def _client_id() -> str:
    """Read the tab's random id (limited length, so it cannot fill memory)."""
    # This accepts the id from JSON, from a plain-text beacon body, or from the URL.
    cid = request.args.get("cid") or ""
    if not cid:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            cid = str(data.get("cid", ""))
    if not cid or len(cid) > 64:
        abort(400)
    return cid

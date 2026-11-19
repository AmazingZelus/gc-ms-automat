"""Entry point: started by spustit.bat (or `python app/main.py` during development).

Starts the local server on a free port, opens the browser and stops by itself
when the browser is closed or the user clicks "Ukončit".
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import secrets
import socket
import sys
import threading
import webbrowser
from pathlib import Path

# This makes "import gcms_automat" work when started as `python app/main.py`.
# (The portable Python finds it through its ._pth file instead.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gcms_automat import APP_NAME, __version__  # noqa: E402
from gcms_automat.lifecycle import ClientTracker, LifecycleSettings, start_watchdog  # noqa: E402
from gcms_automat.paths import LOGS_DIR, RUNTIME_DIR  # noqa: E402

PREFERRED_PORT = 8765
SERVER_INFO_FILE = RUNTIME_DIR / "server.json"
log = logging.getLogger("gcms_automat")


def setup_logging() -> None:
    """Log to the console window and to logs/gcms-automat.log (inside the app folder)."""
    # This makes console output safe even if the console cannot show Czech characters.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    # This adds a size-limited log file; if the folder is read-only, console only.
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            LOGS_DIR / "gcms-automat.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s")
    # This hides the per-request lines of the web server (too noisy for users).
    logging.getLogger("waitress").setLevel(logging.WARNING)


def bind_socket(preferred_port: int) -> socket.socket:
    """Open a listening socket on 127.0.0.1: the preferred port, or any free one."""
    # This tries the preferred port first, then lets the operating system pick one.
    for port in (preferred_port, 0):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            # On Windows this stops other programs from "sharing" our port.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            sock.close()
            log.info("Port %s je obsazený, zkouším jiný.", port)
            continue
        sock.listen(64)
        return sock
    raise RuntimeError("No free port found on 127.0.0.1")


def write_server_info(port: int, token: str, url: str) -> None:
    """Save port/token of the running instance (used by the automatic tests)."""
    # This file lives in <app>/runtime and is deleted when the server stops.
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        SERVER_INFO_FILE.write_text(json.dumps(
            {"pid": os.getpid(), "port": port, "token": token, "url": url, "version": __version__}),
            encoding="utf-8")
    except OSError as exc:
        log.warning("Nelze zapsat %s: %s", SERVER_INFO_FILE, exc)


def stop_process(reason: str) -> None:
    """Stop the whole program immediately (the console window then closes)."""
    # This cleans up, flushes the log and exits with code 0 (= normal end).
    log.info("Ukončuji aplikaci (%s).", reason)
    try:
        SERVER_INFO_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    logging.shutdown()
    os._exit(0)


def main() -> int:
    setup_logging()
    log.info("%s v%s se spouští...", APP_NAME, __version__)

    # This reads optional settings used only by the automatic tests.
    settings = LifecycleSettings()
    if os.environ.get("GCMS_STARTUP_TIMEOUT"):
        settings.startup_timeout_s = float(os.environ["GCMS_STARTUP_TIMEOUT"])
    preferred_port = int(os.environ.get("GCMS_PORT", PREFERRED_PORT))
    open_browser = os.environ.get("GCMS_NO_BROWSER") != "1"

    # This prepares the socket, the secret token and the Flask app.
    sock = bind_socket(preferred_port)
    port = sock.getsockname()[1]
    token = secrets.token_urlsafe(24)
    url = f"http://127.0.0.1:{port}/?token={token}"

    from waitress import create_server  # imported here so --help-like errors stay fast
    from gcms_automat.server import create_app

    tracker = ClientTracker(settings=settings)
    app = create_app(token=token, tracker=tracker, port=port)
    server = create_server(app, sockets=[sock], threads=4)

    # This starts the watchdog that stops the app when the browser is gone.
    start_watchdog(tracker, stop_process)
    write_server_info(port, token, url)

    # The full address (with the one-time key) is printed so the user can copy it
    # if the browser does not open by itself. The key is only valid for this run.
    log.info("Aplikace běží. Pokud se prohlížeč neotevře sám, zkopírujte do něj adresu:")
    log.info("  %s", url)
    log.info("Toto okno nezavírejte. Aplikace se ukončí sama po zavření prohlížeče "
             "nebo tlačítkem Ukončit.")
    # This opens the default web browser shortly after the server is ready.
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()

    # This runs the web server until stop_process() ends the program.
    try:
        server.run()
    except KeyboardInterrupt:
        stop_process("Ctrl+C")
    return 0


if __name__ == "__main__":
    # This catches unexpected errors so the console shows them (spustit.bat pauses).
    try:
        sys.exit(main())
    except Exception:
        log.exception("Aplikace selhala při startu.")
        sys.exit(1)

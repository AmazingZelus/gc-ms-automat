"""Folder layout of the portable application.

Everything the application writes stays inside the application folder
(the folder that contains spustit.bat). Nothing is written elsewhere.
"""

from pathlib import Path

# This finds the application root folder.
# Layout: <root>/app/gcms_automat/paths.py  ->  root is three levels up.
# The same layout is used in the git repository and in the portable ZIP.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
APP_DIR = ROOT_DIR / "app"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# These are the folders the application writes into (all inside ROOT_DIR).
EXPORTS_DIR = ROOT_DIR / "exporty"   # user-visible results (Czech name on purpose)
LOGS_DIR = ROOT_DIR / "logs"         # log files for troubleshooting
RUNTIME_DIR = ROOT_DIR / "runtime"   # temporary files of a running instance

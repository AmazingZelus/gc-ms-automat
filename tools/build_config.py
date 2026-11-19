"""Build settings shared by make_lock.py and build_portable.py (one place to change)."""

# This is the portable ("embeddable") Python for Windows that goes into the ZIP.
# Must be a release that python.org still publishes as "embed-amd64.zip".
PYTHON_VERSION = "3.14.10"
PYTHON_TAG = "314"  # cp314 wheels, python314._pth
EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
WHEEL_PLATFORM = "win_amd64"

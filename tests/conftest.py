"""Make the app package importable in tests."""
import sys
from pathlib import Path

# This adds the app/ folder to the import path (same as the portable ._pth file).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

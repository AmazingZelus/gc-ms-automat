"""Build the portable Windows ZIP.

    python tools/build_portable.py            # downloads the embeddable Python
    python tools/build_portable.py --embed-zip path/to/python-embed.zip

Result: dist/GC-MS-Automat-v<version>-windows-x64.zip containing
    GC-MS-Automat-v<version>/
        spustit.bat        <- the user double-clicks this
        README.md
        app/               <- our code
        python/            <- portable Python + all libraries
"""

from __future__ import annotations

import argparse
import compileall
import hashlib
import py_compile
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_config import EMBED_SHA256, EMBED_URL, PYTHON_TAG, PYTHON_VERSION, WHEEL_PLATFORM  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"


def read_version() -> str:
    """Read __version__ from the single source of truth (without importing the app)."""
    # This finds the line  __version__ = "x.y.z"  in app/gcms_automat/__init__.py.
    text = (ROOT / "app" / "gcms_automat" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("__version__ not found")
    return match.group(1)


def get_embed_zip(local: str | None) -> Path:
    """Return a path to the embeddable Python ZIP (download it once into build/)."""
    # This uses a local copy if given, otherwise downloads from python.org (HTTPS).
    if local:
        return Path(local)
    target = BUILD_DIR / Path(EMBED_URL).name
    if not target.exists():
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {EMBED_URL}")
        urllib.request.urlretrieve(EMBED_URL, target)
    # This checks the download against the checksum published by python.org.
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"Embed ZIP SHA-256: {digest}")
    if digest != EMBED_SHA256:
        target.unlink()
        raise SystemExit(f"Checksum mismatch for {EMBED_URL}: expected {EMBED_SHA256}")
    return target


def write_pth(python_dir: Path) -> None:
    """Tell the portable Python where our packages and our app code are."""
    # This replaces pythonXYZ._pth. Paths are relative to the python folder.
    # In ._pth mode Python ignores PYTHONPATH and user folders (good: isolated).
    pth = python_dir / f"python{PYTHON_TAG}._pth"
    pth.write_text("\n".join([
        f"python{PYTHON_TAG}.zip",
        ".",
        r"Lib\site-packages",
        r"..\app",
        "import site",
        "",
    ]), encoding="utf-8")


def install_packages(site_packages: Path) -> None:
    """Install the exact, hash-checked Windows wheels into the portable Python."""
    # This uses pip from the build machine, but downloads Windows wheels for the
    # target Python version, so it also works when building on Linux.
    site_packages.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "pip", "install", "--no-deps", "--require-hashes",
        "--only-binary=:all:", "--platform", WHEEL_PLATFORM, "--implementation", "cp",
        "--python-version", PYTHON_TAG[0] + "." + PYTHON_TAG[1:],
        "--target", str(site_packages), "--no-compile", "--disable-pip-version-check",
        "-r", str(ROOT / "requirements" / "runtime.lock.txt"),
    ], check=True)


# File types needed only to BUILD the libraries, never to run them.
BUILD_ONLY_SUFFIXES = {".lib", ".pyx", ".pxd", ".pxi", ".pyi", ".c", ".cpp", ".h"}


def remove_unneeded_files(site_packages: Path) -> None:
    """Delete files that are not needed to run the app.

    Test suites, build-only files and command-line launchers make the ZIP bigger,
    contain the longest file paths (Windows has a 260-character path limit), and
    unsigned launcher .exe files can upset antivirus programs.
    """
    # This deletes the launcher folders created by pip (bin on Linux, Scripts on Windows).
    for name in ("bin", "Scripts"):
        shutil.rmtree(site_packages / name, ignore_errors=True)
    # This deletes every folder named "tests" inside the installed libraries.
    for folder in sorted(site_packages.rglob("tests"), key=lambda p: len(p.parts), reverse=True):
        if folder.is_dir():
            shutil.rmtree(folder)
    # This deletes build-only files (C sources, Cython files, import libraries, stubs).
    for path in list(site_packages.rglob("*")):
        if path.is_file() and path.suffix.lower() in BUILD_ONLY_SUFFIXES:
            path.unlink()


def copy_app(dest: Path) -> None:
    """Copy our code, the start script and the user README."""
    # This copies app/ without caches, then the files for the user.
    shutil.copytree(ROOT / "app", dest / "app",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "spustit.bat", dest / "spustit.bat")
    shutil.copy2(ROOT / "README.md", dest / "README.md")
    if (ROOT / "LICENSE").exists():
        shutil.copy2(ROOT / "LICENSE", dest / "LICENSE")
    # The start script must keep Windows line endings (CRLF).
    if b"\r\n" not in (dest / "spustit.bat").read_bytes():
        raise SystemExit("spustit.bat lost its CRLF line endings")


def precompile(dest: Path) -> None:
    """Pre-compile .py files for faster first start (only with a matching Python)."""
    # .pyc files are tied to the Python minor version, so skip if versions differ.
    if f"{sys.version_info.major}{sys.version_info.minor}" != PYTHON_TAG:
        print(f"Skipping pre-compilation (build Python is not {PYTHON_TAG}).")
        return
    # UNCHECKED_HASH: the .pyc is used as is, regardless of file dates. Normal .pyc
    # files compare the source file date, which ZIP extraction changes (time zone,
    # 2-second rounding), so they would be recompiled on every PC anyway.
    for folder in (dest / "python" / "Lib" / "site-packages", dest / "app"):
        compileall.compile_dir(folder, quiet=1, workers=0,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)


def make_zip(source_dir: Path, zip_path: Path) -> None:
    """Pack the CONTENTS of the folder into a ZIP (no extra top-level folder)."""
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(source_dir.rglob("*")):
            zf.write(path, path.relative_to(source_dir).as_posix())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--embed-zip", help="local embeddable Python ZIP (skip download)")
    parser.add_argument("--print-version", action="store_true", help="print the app version and exit")
    args = parser.parse_args()

    # This lets the CI workflow read the version from the single source of truth.
    if args.print_version:
        print(read_version())
        return

    # This prepares a clean output folder named after the version.
    version = read_version()
    name = f"GC-MS-Automat-v{version}"
    stage = DIST_DIR / name
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)

    # This assembles: portable Python -> libraries -> our app -> ZIP.
    print(f"Building {name} with Python {PYTHON_VERSION}")
    with zipfile.ZipFile(get_embed_zip(args.embed_zip)) as zf:
        zf.extractall(stage / "python")
    write_pth(stage / "python")
    install_packages(stage / "python" / "Lib" / "site-packages")
    remove_unneeded_files(stage / "python" / "Lib" / "site-packages")
    copy_app(stage)
    precompile(stage)

    # This checks the longest path inside the ZIP. Windows allows 260 characters
    # in total; Explorer extracts into "<folder>\<zip name>\", so the user's folder
    # gets 260 - 1 - len(zip name without .zip) - 1 - longest characters.
    zip_name = f"{name}-windows-x64"
    longest = max(len(p.relative_to(stage).as_posix()) for p in stage.rglob("*"))
    budget = 260 - 1 - len(zip_name) - 1 - longest
    print(f"Longest path inside ZIP: {longest} characters; "
          f"room left for the user's folder: {budget} characters")
    if budget < 100:
        raise SystemExit("Paths inside the ZIP are too long for Windows; shorten them.")

    zip_path = DIST_DIR / f"{zip_name}.zip"
    make_zip(stage, zip_path)
    print(f"Done: {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()

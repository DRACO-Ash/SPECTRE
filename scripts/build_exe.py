"""PyInstaller build helper for SIPC.

Run this script from the repo root after installing the build extras::

    pip install -e ".[build]"
    python scripts/build_exe.py

The resulting executable will be placed in ``dist/sipc.exe``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ENTRY_POINT = REPO_ROOT / "sipc" / "ui" / "app.py"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"


def main() -> None:
    """Invoke PyInstaller with SIPC-specific options."""
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=sipc",
        "--onefile",
        "--windowed",
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        f"--specpath={BUILD_DIR}",
        # PySide6 hidden imports
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        # Structlog
        "--hidden-import=structlog",
        str(ENTRY_POINT),
    ]

    print(f"Building SIPC executable...\nCommand: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=REPO_ROOT, check=False)

    if result.returncode == 0:
        exe_path = DIST_DIR / "sipc.exe"
        print(f"\nBuild successful: {exe_path}")
    else:
        print(f"\nBuild FAILED with exit code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()

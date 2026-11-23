"""Run actual tests, then print the project's runner notes verbatim."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
result = subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root
)
print("\n--- Runner notes (project-supplied text) ---", flush=True)
print((root / "docs" / "runner-notes.txt").read_text(encoding="utf-8"), flush=True)
sys.exit(result.returncode)


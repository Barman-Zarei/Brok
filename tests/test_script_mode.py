"""PyInstaller (and `python brok/main.py`) run main.py as a plain script, with no parent package.

Regression: top-level relative imports in main.py broke the packaged binaries ("attempted relative import with no
known parent package"). This runs main.py as a script and checks it gets past the imports.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_main_runs_as_a_script():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH="")
    r = subprocess.run(
        [sys.executable, str(ROOT / "brok" / "main.py"), "--help"],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(ROOT),
    )  # fmt: skip
    assert r.returncode == 0, r.stderr[-500:]
    assert "relative import" not in r.stderr
    assert "usage" in r.stdout.lower()


def test_main_starts_as_a_script_not_just_parses_args():
    """`--help` exits before main() runs; this runs main() itself (headless) so imports inside it are exercised."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH="")
    r = subprocess.run(
        [sys.executable, str(ROOT / "brok" / "main.py")],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(ROOT),
    )  # fmt: skip
    assert "Traceback" not in r.stderr and "relative import" not in r.stderr, r.stderr[-600:]

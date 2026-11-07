"""Which copy of the code is running: short git commit, printed by clients and servers at
startup so a 4-laptop test can check everyone uses the same version (no networking here)."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def commit():
    """'a9845f2', 'a9845f2+changes' (local edits), or 'unknown (no git)' for a zip download."""
    def git(*args):
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                              timeout=3, check=True).stdout.strip()
    try:
        head = git("rev-parse", "--short", "HEAD")
    except (OSError, subprocess.SubprocessError):
        return "unknown (no git)"
    try:
        dirty = git("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError):
        dirty = ""
    return head + ("+changes" if dirty else "")

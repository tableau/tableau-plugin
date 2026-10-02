#!/usr/bin/env python3
"""Run a skill script with an interpreter that has the plugin's requirements.

Every skill shares one dependency list (requirements.txt at the plugin root) and
one venv. The session-start hook prepares the venv ahead of time so skills
never pay the install cost mid-task:

    python3 run_python.py --bootstrap                  # prepare only (hook)
    python3 run_python.py SCRIPT.py [script args...]   # run a script

Interpreter choice, cheapest first:
  1. the running interpreter, if it already satisfies requirements.txt
     (the script runs in-process, no extra Python start-up);
  2. the shared venv, if its stamp matches the current requirements.txt;
  3. otherwise (re)build the venv, then use it.

The venv lives in a fixed per-user cache dir rather than a host-provided plugin
data dir: hook processes and the model's shell don't always see the same host
env vars, and a fixed path also survives plugin reinstalls. Stdlib-only and
cross-platform (macOS, Linux, Windows).
"""

from __future__ import annotations

import hashlib
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = PLUGIN_ROOT / "requirements.txt"
STAMP_NAME = ".requirements-sha256"
REQUIREMENT_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:>=\s*([0-9][0-9.]*))?$")


def cache_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "tableau-plugin"


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def requirements() -> list[str]:
    lines = REQUIREMENTS.read_text().splitlines() if REQUIREMENTS.exists() else []
    return [ln.split("#", 1)[0].strip() for ln in lines if ln.split("#", 1)[0].strip()]


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def current_satisfies(reqs: list[str]) -> bool:
    """True if this interpreter already has every requirement installed."""
    from importlib import metadata

    for req in reqs:
        match = REQUIREMENT_LINE.match(req)
        if not match:
            return False  # unsupported specifier: let the venv's pip handle it
        name, minimum = match.groups()
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            return False
        if minimum and version_tuple(installed) < version_tuple(minimum):
            return False
    return True


def ensure_venv(reqs: list[str]) -> Path:
    """Return the shared venv's interpreter, building it if stale or missing."""
    tag = f"{sys.version_info.major}.{sys.version_info.minor}"
    venv = cache_dir() / f"venv-{tag}"
    python = venv_python(venv)
    stamp = venv / STAMP_NAME
    digest = hashlib.sha256("\n".join(reqs).encode()).hexdigest()
    if python.exists() and stamp.exists() and stamp.read_text().strip() == digest:
        return python

    # Keep install chatter on stderr so the script's stdout stays clean.
    venv.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", "--clear", str(venv)],
                   check=True, stdout=sys.stderr)
    if reqs:
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check",
             "--no-input", "-r", str(REQUIREMENTS)],
            check=True, stdout=sys.stderr,
        )
    stamp.write_text(digest + "\n")  # last, so a failed install is retried
    return python


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2

    reqs = requirements()
    if current_satisfies(reqs):
        if args == ["--bootstrap"]:
            return 0
        script = str(Path(args[0]).resolve())
        sys.argv = [script, *args[1:]]
        sys.path.insert(0, str(Path(script).parent))
        runpy.run_path(script, run_name="__main__")
        return 0

    try:
        python = ensure_venv(reqs)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"error: could not prepare the plugin's Python environment: {exc}",
              file=sys.stderr)
        return 1
    if args == ["--bootstrap"]:
        return 0
    if os.name != "nt":
        os.execv(str(python), [str(python), *args])
    return subprocess.run([str(python), *args]).returncode


if __name__ == "__main__":
    sys.exit(main())

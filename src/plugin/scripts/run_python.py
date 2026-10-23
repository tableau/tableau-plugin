#!/usr/bin/env python3
"""Run a skill script with an interpreter that has the plugin's requirements.

Core packages live in requirements.txt. Optional profiles live in
requirements-PROFILE.txt and are installed only when explicitly selected. Each
profile has its own cached venv so incompatible warehouse connectors cannot
destabilize core Hyper operations or each other. Venvs are built lazily, so
sessions that never use a profile never install it:

    python3 run_python.py SCRIPT.py [script args...]   # run with core packages
    python3 run_python.py --with PROFILE SCRIPT.py ... # add an optional profile
    python3 run_python.py --bootstrap                  # prepare core only

Interpreter choice, cheapest first:
  1. the running interpreter, if it already satisfies the selected requirements
     (the script runs in-process, no extra Python start-up);
  2. the profile's shared venv, if its stamp matches the requirements;
  3. otherwise (re)build the venv, then use it.

The venv lives in a fixed per-user cache dir rather than a host-provided plugin
data dir: the model's shell doesn't always see the host's plugin env vars, and a
fixed path also survives plugin reinstalls. Stdlib-only and
cross-platform (macOS, Linux, Windows).
"""

from __future__ import annotations

import hashlib
import os
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CORE_REQUIREMENTS = PLUGIN_ROOT / "requirements.txt"
STAMP_NAME = ".requirements-sha256"
REQUIREMENT_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*)$")
SPECIFIER = re.compile(r"^(>=|==|<)\s*([0-9][0-9.]*)$")
MIN_PYTHON = (3, 9)
PYTHON_CANDIDATES = tuple(
    f"python3.{minor}" for minor in range(14, MIN_PYTHON[1] - 1, -1)
)


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


def requirement_files(profile: str | None) -> list[Path]:
    files = [CORE_REQUIREMENTS]
    if profile:
        extra = PLUGIN_ROOT / f"requirements-{profile}.txt"
        if not extra.is_file():
            prefix = "requirements-"
            available = sorted(
                p.stem[len(prefix):]
                for p in PLUGIN_ROOT.glob("requirements-*.txt")
            )
            choices = ", ".join(available) or "none"
            raise ValueError(f"unknown dependency profile {profile!r}; available: {choices}")
        files.append(extra)
    return files


def requirements(files: list[Path]) -> list[str]:
    lines = [line for path in files for line in path.read_text().splitlines()]
    return [ln.split("#", 1)[0].strip() for ln in lines if ln.split("#", 1)[0].strip()]


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def python_version(python: str) -> tuple[int, ...] | None:
    """Return an interpreter's major/minor version, or None if it cannot run."""
    try:
        result = subprocess.run(
            [python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    version = version_tuple(result.stdout.strip())
    return version[:2] if len(version) >= 2 else None


def compatible_python() -> tuple[str, tuple[int, ...]]:
    """Find a Python new enough for plugin scripts and their type syntax."""
    current = sys.version_info[:2]
    if current >= MIN_PYTHON:
        return sys.executable, current

    seen = {str(Path(sys.executable).resolve())}
    for name in PYTHON_CANDIDATES:
        candidate = shutil.which(name)
        if not candidate:
            continue
        resolved = str(Path(candidate).resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        version = python_version(candidate)
        if version and version >= MIN_PYTHON:
            return candidate, version

    wanted = ".".join(map(str, MIN_PYTHON))
    raise RuntimeError(
        f"Tableau plugin scripts require Python {wanted} or newer; "
        f"this launcher is running on {sys.version_info.major}.{sys.version_info.minor} "
        "and no compatible python3 interpreter was found on PATH"
    )


def current_satisfies(reqs: list[str]) -> bool:
    """True if this interpreter already has every requirement installed."""
    if sys.version_info[:2] < MIN_PYTHON:
        return False
    from importlib import metadata

    for req in reqs:
        match = REQUIREMENT_LINE.match(req)
        if not match:
            return False  # unsupported specifier: let the venv's pip handle it
        name, rest = match.groups()
        specs = [SPECIFIER.match(s.strip()) for s in rest.split(",")] if rest else []
        if not all(specs):
            return False  # unsupported specifier: let the venv's pip handle it
        try:
            installed = version_tuple(metadata.version(name))
        except metadata.PackageNotFoundError:
            return False
        for op, wanted in (s.groups() for s in specs):
            wanted_tuple = version_tuple(wanted)
            if op == ">=" and installed < wanted_tuple:
                return False
            if op == "==" and installed != wanted_tuple:
                return False
            if op == "<" and installed >= wanted_tuple:
                return False
    return True


def ensure_venv(reqs: list[str], files: list[Path], profile: str | None,
                base_python: str, base_version: tuple[int, ...]) -> Path:
    """Return the shared venv's interpreter, building it if stale or missing."""
    tag = f"{base_version[0]}.{base_version[1]}"
    suffix = f"-{profile}" if profile else ""
    venv = cache_dir() / f"venv-{tag}{suffix}"
    python = venv_python(venv)
    stamp = venv / STAMP_NAME
    digest = hashlib.sha256("\n".join(reqs).encode()).hexdigest()
    if python.exists() and stamp.exists() and stamp.read_text().strip() == digest:
        return python

    # Keep install chatter on stderr so the script's stdout stays clean. Wheels
    # only (no source builds needing a compiler), and a short timeout with one
    # retry so an offline machine fails in seconds rather than minutes.
    print("Installing the Tableau plugin's Python requirements (one-time)...",
          file=sys.stderr)
    venv.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([base_python, "-m", "venv", "--clear", str(venv)],
                   check=True, stdout=sys.stderr)
    if reqs:
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check",
             "--no-input", "--only-binary=:all:", "--timeout", "15", "--retries", "1",
             *[arg for path in files for arg in ("-r", str(path))]],
            check=True, stdout=sys.stderr,
        )
    stamp.write_text(digest + "\n")  # last, so a failed install is retried
    return python


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2

    profile = None
    if args[:1] == ["--with"]:
        if len(args) < 3:
            print("error: --with requires PROFILE and SCRIPT.py", file=sys.stderr)
            return 2
        profile, args = args[1], args[2:]

    try:
        files = requirement_files(profile)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    reqs = requirements(files)
    if current_satisfies(reqs):
        if args == ["--bootstrap"]:
            return 0
        script = str(Path(args[0]).resolve())
        sys.argv = [script, *args[1:]]
        sys.path.insert(0, str(Path(script).parent))
        runpy.run_path(script, run_name="__main__")
        return 0

    try:
        base_python, base_version = compatible_python()
        python = ensure_venv(reqs, files, profile, base_python, base_version)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: could not prepare the plugin's Python environment: {exc}\n"
              f"Installing {', '.join(reqs)} from PyPI needs network access; "
              f"it is retried on the next run.", file=sys.stderr)
        return 1
    if args == ["--bootstrap"]:
        return 0
    if os.name != "nt":
        os.execv(str(python), [str(python), *args])
    return subprocess.run([str(python), *args]).returncode


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Multi-platform plugin builder.

Assembles a platform-specific plugin distribution from:

  1. the shared source payload  (src/plugin/)          -> dist/<platform>/plugins/tableau/
  2. a per-platform overlay     (platforms/<platform>/overlay/) -> dist/<platform>/

Overlay files are written after the payload and therefore win on any collision
(that's how a platform swaps in its own manifest, README, hooks, etc.).

Templating is opt-in and lazy: a file whose name ends in ".j2" is rendered with
Jinja2 using the platform's vars.yaml (the ".j2" suffix is stripped in output).
Every other file is copied verbatim, so binary assets and JSON/XML resources are
never passed through the template engine. If no ".j2" files exist for a target,
the build runs with the Python standard library alone.

A platform's vars.yaml may list `exclude:` globs (relative to src/plugin/) for
payload files that platform doesn't ship.

Usage:
    python3 build/build.py                 # build every platform under platforms/
    python3 build/build.py openai          # build only the named platform(s)
    python3 build/build.py --zip claude    # also write dist/claude-tableau.zip
    python3 build/build.py --check openai  # fail if dist/ is stale vs a fresh build
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
SRC_PAYLOAD = ROOT / "src" / "plugin"
PAYLOAD_DEST_SUBPATH = Path("plugins/tableau")  # where the shared payload lands in a dist
PLATFORMS_DIR = ROOT / "platforms"
DIST_DIR = ROOT / "dist"

# Never copied into a distribution.
EXCLUDE_NAMES = {".DS_Store"}
# Any path containing one of these components (or matching a suffix) is skipped.
EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_SUFFIXES = (".pyc",)

TEMPLATE_SUFFIX = ".j2"


def log(msg: str) -> None:
    print(msg)


def load_vars(platform_dir: Path) -> dict:
    """Load platform variables from vars.yaml (only imported if it exists)."""
    vars_file = platform_dir / "vars.yaml"
    if not vars_file.exists():
        return {}
    try:
        import yaml  # lazy: only needed when a platform actually defines vars
    except ImportError:
        sys.exit(
            f"error: {vars_file} exists but PyYAML is not installed.\n"
            f"       pip install -r build/requirements.txt"
        )
    data = yaml.safe_load(vars_file.read_text()) or {}
    if not isinstance(data, dict):
        sys.exit(f"error: {vars_file} must contain a top-level mapping")
    return data


def render_template(text: str, variables: dict, src: Path) -> str:
    """Render a Jinja2 template string (lazy import; StrictUndefined catches typos)."""
    try:
        from jinja2 import Environment, StrictUndefined
    except ImportError:
        sys.exit(
            f"error: {src} is a .j2 template but Jinja2 is not installed.\n"
            f"       pip install -r build/requirements.txt"
        )
    env = Environment(
        undefined=StrictUndefined,
        autoescape=False,           # this is markdown/JSON, not HTML
        keep_trailing_newline=True,
        trim_blocks=True,           # a standalone {% %} line leaves no blank line
        lstrip_blocks=True,         # ...and no leading indentation either
    )
    return env.from_string(text).render(**variables)


def emit_file(src: Path, dest: Path, variables: dict) -> str:
    """Copy or render one file into place. Returns 'render' or 'copy'."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.name.endswith(TEMPLATE_SUFFIX):
        rendered = render_template(src.read_text(), variables, src)
        out = dest.with_name(dest.name[: -len(TEMPLATE_SUFFIX)])
        out.write_text(rendered)
        shutil.copymode(src, out)
        return "render"
    shutil.copy2(src, dest)
    return "copy"


def copy_tree(src_root: Path, dest_root: Path, variables: dict,
              exclude: tuple[str, ...] = ()) -> tuple[int, int]:
    """Emit every file under src_root into dest_root (recursively).

    `exclude` holds globs matched against each file's path relative to src_root.
    """
    copied = rendered = 0
    for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
        if src.name in EXCLUDE_NAMES or src.name.endswith(EXCLUDE_SUFFIXES):
            continue
        if EXCLUDE_DIRS.intersection(src.relative_to(src_root).parts):
            continue
        rel = src.relative_to(src_root)
        if any(PurePosixPath(rel.as_posix()).match(g) for g in exclude):
            continue
        result = emit_file(src, dest_root / rel, variables)
        if result == "render":
            rendered += 1
        else:
            copied += 1
    return copied, rendered


def build_platform(platform: str, out_root: Path = DIST_DIR) -> Path:
    platform_dir = PLATFORMS_DIR / platform
    if not platform_dir.is_dir():
        sys.exit(f"error: unknown platform '{platform}' (no {platform_dir})")

    variables = load_vars(platform_dir)
    variables.setdefault("platform", platform)

    dist = out_root / platform
    if dist.exists():
        shutil.rmtree(dist)

    # 1. shared payload -> dist/<platform>/plugins/tableau/
    exclude = tuple(variables.get("exclude", ()))
    c1, r1 = copy_tree(SRC_PAYLOAD, dist / PAYLOAD_DEST_SUBPATH, variables, exclude)

    # 2. platform overlay -> dist/<platform>/ (root); overrides payload on collision
    overlay = platform_dir / "overlay"
    c2 = r2 = 0
    if overlay.is_dir():
        c2, r2 = copy_tree(overlay, dist, variables)

    shown = dist.relative_to(ROOT) if dist.is_relative_to(ROOT) else dist
    log(f"[{platform}] payload: {c1} copied, {r1} rendered | "
        f"overlay: {c2} copied, {r2} rendered -> {shown}")
    return dist


def zip_plugin(platform: str, dist: Path) -> Path:
    """Zip the built plugin dir (manifest at the zip root) for upload/submission.

    Entries are sorted with a fixed timestamp so the zip is reproducible.
    """
    plugin_dir = dist / PAYLOAD_DEST_SUBPATH
    out = dist.parent / f"{platform}-{PAYLOAD_DEST_SUBPATH.name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in plugin_dir.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(plugin_dir).as_posix(),
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = (path.stat().st_mode & 0o777) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    shown = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    log(f"[{platform}] zip -> {shown}")
    return out


def discover_platforms() -> list[str]:
    return sorted(
        p.name for p in PLATFORMS_DIR.iterdir()
        if p.is_dir() and (p / "overlay").exists()
    )


def dirs_equal(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b)
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(dirs_equal(a / sub, b / sub) for sub in cmp.common_dirs)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build platform plugin distributions.")
    ap.add_argument("platforms", nargs="*", help="platform(s) to build (default: all)")
    ap.add_argument("--check", action="store_true",
                    help="build to a temp dir and fail if dist/ differs from it")
    ap.add_argument("--zip", action="store_true",
                    help="also zip each built plugin to dist/<platform>-tableau.zip")
    args = ap.parse_args()

    targets = args.platforms or discover_platforms()
    if not targets:
        sys.exit("error: no platforms found under platforms/")

    if args.check:
        ok = True
        for platform in targets:
            with tempfile.TemporaryDirectory() as tmp:
                # Build into a scratch dir, leaving dist/ untouched, and compare.
                fresh = build_platform(platform, out_root=Path(tmp))
                staged = DIST_DIR / platform
                if not (staged.exists() and dirs_equal(staged, fresh)):
                    log(f"[{platform}] CHECK FAILED: dist is stale")
                    ok = False
        sys.exit(0 if ok else 1)

    for platform in targets:
        dist = build_platform(platform)
        if args.zip:
            zip_plugin(platform, dist)


if __name__ == "__main__":
    main()

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

`--variant` builds a renamed copy for local development that can be installed
next to the published plugin without colliding with it (see VARIANTS):

  prod  what ships: hosted mcp.tableau.com            -> dist/<platform>/
  test  hosted test.mcp.tableau.com                   -> dist/<platform>-test/
  stage hosted stage.mcp.tableau.com                  -> dist/<platform>-stage/
  dev   a local tableau-mcp checkout over stdio       -> dist/<platform>-dev/
        (TABLEAU_MCP_DIR from this repo's .env, overridable in the host env)

Usage:
    python3 build/build.py                 # build every platform under platforms/
    python3 build/build.py openai          # build only the named platform(s)
    python3 build/build.py --zip claude    # also write dist/claude-tableau.zip
    python3 build/build.py --check openai  # fail if dist/ is stale vs a fresh build
    python3 build/build.py --variant dev openai
"""

from __future__ import annotations

import argparse
import filecmp
import json
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
EXCLUDE_DIRS = {"__pycache__", "tests"}
EXCLUDE_SUFFIXES = (".pyc",)

TEMPLATE_SUFFIX = ".j2"

# Local-development variants. Each gets its own plugin name and MCP server key:
# hosts key MCP servers by name (Codex skips a second plugin server with the
# same name), so a variant sharing the published names would shadow, or be
# shadowed by, the marketplace install.
VARIANTS = {
    "prod": None,
    "test": {"label": "Test", "url": "https://test.mcp.tableau.com"},
    "stage": {"label": "Stage", "url": "https://stage.mcp.tableau.com"},
    "dev": {"label": "Dev", "stdio": True},
}
MCP_CONFIG_NAMES = (".mcp.json", "mcp.json")
# Per-developer settings (git-ignored). TABLEAU_MCP_DIR there becomes the dev
# variant's default checkout.
DOTENV = ROOT / ".env"


def load_dotenv(path: Path) -> dict:
    """Parse KEY=VALUE lines; blank lines and # comments are skipped."""
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.removeprefix("export ").partition("=")
                values[key.strip()] = value.strip().strip("'\"")
    return values


def dev_server_command() -> str:
    """Shell command for the dev variant's stdio server.

    The host plugin cache, not this repo, is where the server runs, so the
    checkout comes from TABLEAU_MCP_DIR in the host's environment, falling back
    to the one in .env baked in at build time. dotenv only looks in the cwd,
    which the host picks, so node loads the checkout's .env; variables already
    set (TRANSPORT) win over it.
    """
    default = load_dotenv(DOTENV).get("TABLEAU_MCP_DIR")
    if default:
        default = str(Path(default).expanduser())
        if any(c in default for c in '"$`\\}'):
            sys.exit(f"error: TABLEAU_MCP_DIR in {DOTENV} has characters the shell would expand")
        if not (Path(default) / "build" / "index.js").exists():
            log(f"warning: {default}/build/index.js not found; run `npm run build` there")
        checkout = f'${{TABLEAU_MCP_DIR:-{default}}}'
    else:
        checkout = '${TABLEAU_MCP_DIR:?set TABLEAU_MCP_DIR (in .env or the environment)}'
    return f'dir="{checkout}"; exec node --env-file="$dir/.env" "$dir/build/index.js"'


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


def mcp_server_config(variant: dict, original: dict, env_passthrough: bool) -> dict:
    """The MCP server definition a variant uses in place of the published one."""
    if not variant.get("stdio"):
        return {**original, "url": variant["url"]}
    config = {
        "command": "sh",
        "args": ["-c", dev_server_command()],
        "env": {"TRANSPORT": "stdio"},
    }
    if env_passthrough:
        config["env_vars"] = ["TABLEAU_MCP_DIR"]
    return {"type": "stdio", **config} if original.get("type") == "streamable-http" else config


def rewrite_json(path: Path, edit) -> None:
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def apply_variant(dist: Path, name: str, variant: dict, server_key: str,
                  env_passthrough: bool) -> None:
    """Rename the built plugin, its marketplace and MCP server, and repoint the server."""
    suffix, label = f"-{name}", f" ({variant['label']})"

    def relabel(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "displayName" and isinstance(value, str):
                    node[key] = value + label
                else:
                    relabel(value)
        elif isinstance(node, list):
            for item in node:
                relabel(item)

    def edit_marketplace(data: dict) -> None:
        data["name"] += suffix
        for plugin in data["plugins"]:
            plugin["name"] += suffix
        relabel(data)

    def edit_manifest(data: dict) -> None:
        data["name"] += suffix
        relabel(data)

    def edit_mcp(data: dict) -> None:
        (original,) = data["mcpServers"].values()
        data["mcpServers"] = {server_key: mcp_server_config(variant, original, env_passthrough)}

    plugin_dir = dist / PAYLOAD_DEST_SUBPATH
    for path in (dist / ".agents/plugins/marketplace.json",
                 dist / ".claude-plugin/marketplace.json"):
        if path.exists():
            rewrite_json(path, edit_marketplace)
    for path in (plugin_dir / "plugin.json",
                 plugin_dir / ".codex-plugin/plugin.json",
                 plugin_dir / ".claude-plugin/plugin.json"):
        if path.exists():
            rewrite_json(path, edit_manifest)
    for config_name in MCP_CONFIG_NAMES:
        if (plugin_dir / config_name).exists():
            rewrite_json(plugin_dir / config_name, edit_mcp)


def build_platform(platform: str, out_root: Path = DIST_DIR, variant: str = "prod") -> Path:
    platform_dir = PLATFORMS_DIR / platform
    if not platform_dir.is_dir():
        sys.exit(f"error: unknown platform '{platform}' (no {platform_dir})")

    variables = load_vars(platform_dir)
    variables.setdefault("platform", platform)

    spec = VARIANTS[variant]
    server_key = "Tableau" + (spec["label"] if spec else "")
    if spec and variables.get("mcp_prefix"):
        # Skills address tools by server key on hosts with a fixed prefix.
        variables["mcp_prefix"] = f"mcp__{server_key}__"

    dist = out_root / (platform if not spec else f"{platform}-{variant}")
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

    if spec:
        apply_variant(dist, variant, spec, server_key,
                      bool(variables.get("mcp_env_passthrough")))

    shown = dist.relative_to(ROOT) if dist.is_relative_to(ROOT) else dist
    log(f"[{dist.name}] payload: {c1} copied, {r1} rendered | "
        f"overlay: {c2} copied, {r2} rendered -> {shown}")
    return dist


def zip_plugin(dist: Path) -> Path:
    """Zip the built plugin dir (manifest at the zip root) for upload/submission.

    Entries are sorted with a fixed timestamp so the zip is reproducible.
    """
    plugin_dir = dist / PAYLOAD_DEST_SUBPATH
    out = dist.parent / f"{dist.name}-{PAYLOAD_DEST_SUBPATH.name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in plugin_dir.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(plugin_dir).as_posix(),
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = (path.stat().st_mode & 0o777) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    shown = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    log(f"[{dist.name}] zip -> {shown}")
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
    ap.add_argument("--variant", choices=VARIANTS, default="prod",
                    help="local-development variant to build (default: prod)")
    args = ap.parse_args()

    targets = args.platforms or discover_platforms()
    if not targets:
        sys.exit("error: no platforms found under platforms/")

    if args.check:
        ok = True
        for platform in targets:
            with tempfile.TemporaryDirectory() as tmp:
                # Build into a scratch dir, leaving dist/ untouched, and compare.
                fresh = build_platform(platform, out_root=Path(tmp), variant=args.variant)
                staged = DIST_DIR / fresh.name
                if not (staged.exists() and dirs_equal(staged, fresh)):
                    log(f"[{platform}] CHECK FAILED: dist is stale")
                    ok = False
        sys.exit(0 if ok else 1)

    for platform in targets:
        dist = build_platform(platform, variant=args.variant)
        if args.zip:
            zip_plugin(dist)


if __name__ == "__main__":
    main()

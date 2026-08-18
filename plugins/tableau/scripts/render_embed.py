#!/usr/bin/env python3
"""
Build a viewable embed for a published Tableau workbook/view URL and try to
open it.

Why this exists: Tableau's hosted MCP server has its own "render-interactive-viz"
/ "get-embed-token" tools (the "mcp-apps" tool group) that are designed to let a
host render a live Tableau embed inline via the MCP Apps standard. But per
OpenAI's own docs, that iframe rendering is implemented in ChatGPT; Codex is
only guaranteed to be able to use the tool's data, not necessarily render its
UI. So this script is the fallback path that works from any Codex surface with
a browser available: it appends Tableau's documented embed query parameters to
a view URL, writes a minimal local HTML file with an <iframe>, and tries to
open it with the OS's default handler.

Usage:
    python3 render_embed.py <workbook_or_view_url> [--out path/to/embed.html]

If opening the file automatically fails (e.g. headless environment), the
script still prints the file path and the embed URL so the caller can present
a link to the user.
"""

import argparse
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

EMBED_PARAMS = ":embed=yes&:toolbar=no&:tabs=no&:showVizHome=no"

HTML_TEMPLATE = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Tableau embed</title>
    <style>
      html, body {{ margin: 0; height: 100%; }}
      iframe {{ border: 0; width: 100%; height: 100%; }}
    </style>
  </head>
  <body>
    <iframe src="{embed_url}" allowfullscreen></iframe>
  </body>
</html>
"""


def build_embed_url(url: str) -> str:
    parts = urlsplit(url)

    # Tableau Cloud URLs are often hash-routed (e.g. "#/views/Workbook/View"),
    # where the embed params need to go inside the fragment for the client-side
    # router to see them. Classic Tableau Server URLs have no fragment, so the
    # params go in the real query string instead.
    if parts.fragment:
        sep = "&" if "?" in parts.fragment else "?"
        fragment = f"{parts.fragment}{sep}{EMBED_PARAMS}"
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, fragment))

    query = f"{parts.query}&{EMBED_PARAMS}" if parts.query else EMBED_PARAMS
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def try_open(path: Path) -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=True)
        elif system == "Windows":
            subprocess.run(["cmd", "/c", "start", "", str(path)], check=True)
        else:
            subprocess.run(["xdg-open", str(path)], check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Published Tableau workbook or view URL")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write the embed HTML file (default: a temp file)",
    )
    args = parser.parse_args(argv[1:])

    embed_url = build_embed_url(args.url)

    out_path = args.out
    if out_path is None:
        fd, name = tempfile.mkstemp(prefix="tableau-embed-", suffix=".html")
        out_path = Path(name)
        import os

        os.close(fd)

    out_path.write_text(HTML_TEMPLATE.format(embed_url=embed_url), encoding="utf-8")

    opened = try_open(out_path)

    print(f"embed_url: {embed_url}")
    print(f"html_file: {out_path}")
    print(f"opened_automatically: {opened}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""Fail if a skill names a TableauDesktop tool the Desktop MCP server doesn't list.

Starts the server over stdio with no Tableau Desktop running, lists its tools,
and checks every `TableauDesktop__<tool>` name under src/plugin/skills/.

Usage:
    python3 build/check_desktop_tools.py                  # npx -y @tableau/mcp-server-desktop@latest
    python3 build/check_desktop_tools.py node <checkout>/build/index.desktop.js
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "src" / "plugin" / "skills"
TOOL_NAME_RE = re.compile(r"TableauDesktop__([a-z][a-z0-9-]*)")
DEFAULT_COMMAND = ["npx", "-y", "@tableau/mcp-server-desktop@latest"]


def skill_tool_names() -> dict[str, set[str]]:
    """Each tool name the skills use, mapped to the files that use it."""
    names: dict[str, set[str]] = {}
    for path in sorted(p for p in SKILLS.rglob("*") if p.is_file()):
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for name in TOOL_NAME_RE.findall(text):
            names.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return names


def listed_tools(command: list[str]) -> set[str]:
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "TRANSPORT": "stdio",
            "PRODUCT_TELEMETRY_ENABLED": "false",
            "TABLEAU_EXTERNAL_API_DISCOVERY_DIR": tmp,
            "TABLEAU_MCP_CACHE_DIR": str(Path(tmp) / "cache"),
        }
        if "HOME" in os.environ:
            env["HOME"] = os.environ["HOME"]
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "check-desktop-tools", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        executable = shutil.which(command[0]) or command[0]
        proc = subprocess.Popen([executable, *command[1:]], cwd=tmp, env=env, text=True,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for request in requests:
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
                if "id" not in request:
                    continue
                for line in proc.stdout:
                    message = json.loads(line)
                    if message.get("id") == request["id"]:
                        break
                else:
                    sys.exit(f"error: the server exited before answering {request['method']}")
                if "error" in message:
                    sys.exit(f"error: {request['method']} failed: {message['error']}")
            return {tool["name"] for tool in message["result"]["tools"]}
        finally:
            proc.kill()
            proc.wait()


def main() -> None:
    command = sys.argv[1:] or DEFAULT_COMMAND
    used = skill_tool_names()
    if not used:
        sys.exit(f"error: no TableauDesktop__<tool> names under {SKILLS}")
    listed = listed_tools(command)
    missing = sorted(set(used) - listed)
    if missing:
        lines = "\n".join(f"  {name}: {', '.join(sorted(used[name]))}" for name in missing)
        sys.exit(f"error: skills name tools the Desktop server doesn't list:\n{lines}")
    print(f"Desktop tool names OK: {len(used)} used by skills, {len(listed)} listed by the server")


if __name__ == "__main__":
    main()

"""
Shared stdio JSON-RPC client for talking to the Tableau MCP server directly (no LLM
involved -- deterministic tool calls with fixed arguments), used by bench scripts that
need to read or clean up live Tableau content rather than going through codex.

Launch config is read from plugins/tableau/.mcp.json -- the same file codex/the plugin
uses -- rather than relying on the tableau-mcp checkout's own .env, which may be set up
for a different transport (e.g. http) than the stdio transport this client speaks.
"""
import json
import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MCP_JSON = REPO_ROOT / "plugins" / "tableau" / ".mcp.json"


def load_tableau_server_config(mcp_json_path=None):
    path = Path(mcp_json_path) if mcp_json_path else DEFAULT_MCP_JSON
    cfg = json.loads(path.read_text())["mcpServers"]["tableau"]
    cmd = [cfg["command"], *cfg.get("args", [])]
    cwd = cfg["cwd"]
    env = {**os.environ, **cfg.get("env", {})}
    return cmd, cwd, env


class McpStdioClient:
    def __init__(self, cmd, cwd, env=None):
        self.proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0

    def _next_id(self):
        self._id += 1
        return self._id

    def _write(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)

    def call(self, method, params=None, timeout=60):
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                stderr_tail = self.proc.stderr.read(4000) if self.proc.stderr else ""
                raise RuntimeError(f"MCP server closed stdout unexpectedly. stderr:\n{stderr_tail}")
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # server log noise on stdout, not a JSON-RPC frame
            if obj.get("id") == req_id:
                if "error" in obj:
                    raise RuntimeError(f"{method} failed: {obj['error']}")
                return obj.get("result")
            # else: notification or response to a different call; ignore and keep reading
        raise TimeoutError(f"Timed out waiting for response to {method}")

    def initialize(self):
        self.call("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "tableau-bench", "version": "0.1.0"},
        })
        self.notify("notifications/initialized")

    def list_tools(self):
        result = self.call("tools/list")
        return result.get("tools", [])

    def call_tool(self, name, arguments):
        return self.call("tools/call", {"name": name, "arguments": arguments}, timeout=120)

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def result_text(result):
    if not result:
        return ""
    content = result.get("content") or []
    if content and content[0].get("type") == "text":
        return content[0]["text"]
    return str(result)

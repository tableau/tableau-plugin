#!/usr/bin/env python3
"""
Clean up workbooks published to the live Tableau site by bench runs.

Reads bench/results/created_assets.jsonl (written by run_bench.py whenever a
run's publish-workbook call succeeds) and, for each not-yet-deleted asset,
drives the Tableau MCP server's own `delete-content` tool directly over its
stdio JSON-RPC transport -- the same preview/confirm flow the plugin itself
uses, with the same Cloud recycle-bin safety net. No LLM is involved: this
calls the tool with fixed arguments, deterministically.

If the site has the mcp-apps feature gate on, delete-content refuses a
model/script-driven confirm and requires a human to click Confirm in Tableau's
UI -- this script detects that and reports the asset as needing manual
cleanup (with a link) instead of trying to work around it.

Usage:
  python3 bench/cleanup_assets.py                 # dry run: just list what's tracked
  python3 bench/cleanup_assets.py --yes            # actually preview+confirm-delete each one
  python3 bench/cleanup_assets.py --yes --limit 3  # cap how many get deleted in one run
"""
import argparse
import json
import time
from pathlib import Path

from mcp_client import McpStdioClient, load_tableau_server_config, result_text

ROOT = Path(__file__).resolve().parent
DEFAULT_LEDGER = ROOT / "results" / "created_assets.jsonl"
DEFAULT_STATE = ROOT / "results" / "cleanup_state.json"
DEFAULT_REPORT = ROOT / "results" / "cleanup_report.md"


def load_ledger(path):
    assets = {}
    if not path.exists():
        return assets
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        wb_id = entry.get("workbook_id")
        if wb_id:
            assets[wb_id] = entry  # last write wins for display metadata
    return assets


def load_state(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--server-cmd", nargs="+", default=None,
                     help="Override the MCP server launch command (default: read from plugins/tableau/.mcp.json)")
    ap.add_argument("--server-cwd", default=None,
                     help="Override the MCP server cwd (default: read from plugins/tableau/.mcp.json)")
    ap.add_argument("--yes", action="store_true", help="Actually delete. Without this, only lists tracked assets.")
    ap.add_argument("--limit", type=int, default=None, help="Max number of assets to delete this run.")
    args = ap.parse_args()

    assets = load_ledger(args.ledger)
    state = load_state(args.state)

    pending = [
        (wb_id, entry) for wb_id, entry in assets.items()
        if state.get(wb_id, {}).get("status") != "deleted"
    ]

    if not pending:
        print("No pending tracked assets to clean up.")
        return

    print(f"{len(pending)} tracked asset(s) not yet marked deleted:")
    for wb_id, entry in pending:
        status = state.get(wb_id, {}).get("status", "untracked")
        print(f"  - {entry.get('name')!r} (id {wb_id}, project {entry.get('project')}) [{status}]")
        if entry.get("webpage_url"):
            print(f"      {entry['webpage_url']}")

    if not args.yes:
        print("\nDry run (default). Re-run with --yes to preview+confirm-delete these via the")
        print("Tableau MCP server's delete-content tool (Cloud recycle-bin recoverable).")
        return

    if args.limit is not None:
        pending = pending[: args.limit]

    client = McpStdioClient(args.server_cmd, args.server_cwd)
    report_lines = ["# Cleanup report", ""]
    try:
        client.initialize()
        tool_names = {t["name"] for t in client.list_tools()}
        if "delete-content" not in tool_names:
            msg = (
                "delete-content tool is not available on this MCP server (ADMIN_TOOLS_ENABLED "
                "may be off for this connection). Cannot auto-delete -- delete manually via the "
                "Tableau UI using the links above."
            )
            print(f"\n{msg}")
            report_lines.append(msg)
            for wb_id, entry in pending:
                state[wb_id] = {"status": "blocked", "detail": msg, "checked_at": time.time()}
            save_state(args.state, state)
            args.report.write_text("\n".join(report_lines))
            return

        for wb_id, entry in pending:
            name = entry.get("name")
            print(f"\n[{name}] previewing delete (id {wb_id}) ...")
            try:
                preview = client.call_tool("delete-content", {"resourceType": "workbook", "resourceId": wb_id})
            except RuntimeError as e:
                print(f"  preview failed: {e}")
                state[wb_id] = {"status": "error", "detail": str(e), "checked_at": time.time()}
                report_lines.append(f"- **{name}** (`{wb_id}`): preview error — {e}")
                continue

            if preview.get("isError"):
                detail = result_text(preview)
                print(f"  preview blocked: {detail}")
                state[wb_id] = {"status": "blocked", "detail": detail, "checked_at": time.time()}
                report_lines.append(
                    f"- **{name}** (`{wb_id}`): blocked at preview — {detail}. "
                    f"Manual link: {entry.get('webpage_url', 'n/a')}"
                )
                continue

            print(f"  preview ok, confirming delete ...")
            try:
                confirm = client.call_tool(
                    "delete-content",
                    {"resourceType": "workbook", "resourceId": wb_id, "confirm": True},
                )
            except RuntimeError as e:
                print(f"  confirm failed: {e}")
                state[wb_id] = {"status": "error", "detail": str(e), "checked_at": time.time()}
                report_lines.append(f"- **{name}** (`{wb_id}`): confirm error — {e}")
                continue

            if confirm.get("isError"):
                detail = result_text(confirm)
                print(f"  confirm blocked (likely needs human UI confirmation): {detail}")
                state[wb_id] = {"status": "blocked", "detail": detail, "checked_at": time.time()}
                report_lines.append(
                    f"- **{name}** (`{wb_id}`): blocked at confirm (human confirmation required in "
                    f"Tableau's UI) — {detail}. Manual link: {entry.get('webpage_url', 'n/a')}"
                )
                continue

            detail = result_text(confirm)
            print(f"  deleted: {detail}")
            state[wb_id] = {"status": "deleted", "detail": detail, "checked_at": time.time()}
            report_lines.append(f"- **{name}** (`{wb_id}`): deleted — {detail}")
    finally:
        client.close()
        save_state(args.state, state)

    args.report.write_text("\n".join(report_lines))
    print(f"\nReport written to {args.report}")


if __name__ == "__main__":
    main()

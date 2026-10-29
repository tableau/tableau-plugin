#!/usr/bin/env python3
"""
Repeatedly run an agent CLI -- `codex exec` (default) or Claude Code's `claude -p`
(--harness claude) -- against a set of test cases (from prompts.json),
recording every tool call (shell + MCP) with its duration, and every
non-tool-call ("thinking") interval between decision points. Produces a
per-run JSON record, a per-test aggregate, and a Markdown report.

Usage:
  python3 bench/run_bench.py                     # run everything in prompts.json
  python3 bench/run_bench.py --only cold_bar_chart
  python3 bench/run_bench.py --models gpt-5.6-sol,o3   # sweep the same tests across models
  python3 bench/run_bench.py --harness claude     # same tests through Claude Code
  python3 bench/run_bench.py --harness codex,claude   # both, in one sweep and one report
  python3 bench/run_bench.py --reps 2 --dry-run   # sanity-check commands first
  python3 bench/run_bench.py --report-only        # rebuild report.md from saved results/
"""
import argparse
import concurrent.futures
import json
import os
import re
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPTS_FILE = ROOT / "prompts.json"
DEFAULT_RESULTS_DIR = ROOT / "results"
# Flat, accumulating archive that the Tableau .hyper extract is built from. Each
# rep writes one uniquely-named file here (in addition to its nested
# results/.../summary.json), so repeated runs combine without duplication.
DEFAULT_STAGING_DIR = ROOT / "tableau"
DEFAULT_HYPER_OUTPUT = ROOT / "bench_results.hyper"
CODEX_CONFIG_TOML = Path.home() / ".codex" / "config.toml"
HARNESSES = ("codex", "claude")
# Claude dev build, from `python3 build/build.py --variant dev claude`. Loaded per run via
# --plugin-dir, so there's no install step (and nothing to reinstall after a rebuild).
DEFAULT_CLAUDE_PLUGIN_DIR = ROOT.parent / "dist" / "claude-dev" / "plugins" / "tableau"
CLAUDE_USER_SETTINGS = Path.home() / ".claude" / "settings.json"
# The only user settings a Claude run keeps: whatever authenticates the CLI (e.g. a
# gateway's apiKeyHelper, env and model overrides). Everything else in user settings --
# other plugins, hooks, CLAUDE.md -- is skipped so runs see only the Tableau plugin.
CLAUDE_AUTH_KEYS = ("apiKeyHelper", "env", "modelOverrides")

# Guards created_assets.jsonl appends when reps run concurrently (--parallel).
_LEDGER_LOCK = threading.Lock()

# Tool names (or substrings) whose successful mcp_tool_call result represents new content
# published to the live Tableau site, and therefore needs to be tracked for cleanup.
PUBLISHING_TOOLS = {"publish-workbook"}

# codex exec supports these; codex exec resume only supports a subset (no -s/--approve-for-me).
RESUME_SAFE_FLAGS = {"-m", "--model", "--enable", "--disable", "--skip-git-repo-check"}


def read_config_default_model():
    """Best-effort read of the top-level `model = "..."` line in ~/.codex/config.toml,
    used only as a label when a test doesn't pin an explicit model via -m."""
    if not CODEX_CONFIG_TOML.exists():
        return None
    match = re.search(r'(?m)^model\s*=\s*["\'](.+?)["\']', CODEX_CONFIG_TOML.read_text())
    return match.group(1) if match else None


def parse_harnesses(value):
    """argparse type for --harness: one harness or a comma-separated list of them."""
    harnesses = list(dict.fromkeys(h.strip() for h in value.split(",") if h.strip()))
    unknown = [h for h in harnesses if h not in HARNESSES]
    if unknown or not harnesses:
        raise argparse.ArgumentTypeError(
            f"unknown harness {', '.join(unknown) or value!r} (choose from {', '.join(HARNESSES)})")
    return harnesses


def sanitize_label(label):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label)


def resolve_model_list(value, harness):
    """`model` (in defaults or a test override) may be a single model string, a list of
    models to sweep across, a {harness: string-or-list} mapping, or None/empty to leave
    it up to the CLI's own default."""
    if isinstance(value, dict):
        value = value.get(harness)
    if not value:
        return None
    if isinstance(value, str):
        return [value]
    return [v for v in value if v] or None


def resolve_step_files(step):
    """Resolve a step's "files" list (paths relative to the repo root, or absolute)
    to existing absolute paths. Fails fast if a referenced file doesn't exist, rather
    than letting the model discover that mid-run."""
    resolved = []
    for f in step.get("files", []):
        p = Path(f)
        if not p.is_absolute():
            p = (ROOT.parent / f).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"Step file not found: {f!r} (resolved to {p})")
        resolved.append(p)
    return resolved


def build_prompt_with_files(prompt, resolved_files):
    if not resolved_files:
        return prompt
    listing = "\n".join(f"- {p}" for p in resolved_files)
    return (
        f"{prompt}\n\n"
        f"Local file(s) provided for this task (read them directly from disk at these exact paths):\n{listing}"
    )


def build_first_step_args(cfg):
    args = ["--skip-git-repo-check"]
    # --approve-for-me implies workspace-write and conflicts with an explicit --sandbox.
    if cfg.get("approve_for_me"):
        args += ["--approve-for-me"]
    elif cfg.get("sandbox"):
        args += ["-s", cfg["sandbox"]]
    if cfg.get("model"):
        args += ["-m", cfg["model"]]
    if cfg.get("cd"):
        args += ["-C", cfg["cd"]]
    return args


def build_resume_step_args(cfg):
    # Resume steps run with the same pinned `cwd` as step 1 (see run_codex_step), which is
    # a throwaway temp dir rather than a git repo, so they need this too -- not just step 1.
    args = ["--skip-git-repo-check"]
    if cfg.get("model"):
        args += ["-m", cfg["model"]]
    return args


def write_claude_auth_settings(out_dir):
    """Copy just the auth-related user settings into a private file for --settings.

    Claude runs pass `--setting-sources project` so the user's other plugins, hooks and
    CLAUDE.md don't leak into the benchmark, which also drops whatever authenticates the
    CLI -- this hands those keys back. `out_dir` comes from mkdtemp (0700); the caller
    deletes it at the end of the sweep."""
    user = json.loads(CLAUDE_USER_SETTINGS.read_text()) if CLAUDE_USER_SETTINGS.exists() else {}
    path = Path(out_dir) / "auth-settings.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({k: user[k] for k in CLAUDE_AUTH_KEYS if k in user}, fh)
    return path


def build_claude_cmd(cfg, resume_id, add_dirs):
    # Unlike `codex exec resume`, `claude -p --resume` takes every flag, so each step gets
    # the same args. The prompt goes over stdin: --add-dir is variadic and would swallow a
    # trailing positional prompt.
    cmd = [
        "claude", "-p", "--output-format", "stream-json", "--verbose",
        "--setting-sources", "project",
        "--settings", str(cfg["claude_settings"]),
        "--plugin-dir", str(cfg["claude_plugin_dir"]),
        "--permission-mode", cfg.get("permission_mode") or "auto",
    ]
    if add_dirs:
        cmd += ["--add-dir", *add_dirs]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    if resume_id:
        cmd += ["--resume", resume_id]
    return cmd


def run_codex_step(prompt, resume_id, step_args, raw_log_fh, cwd=None):
    if resume_id is None:
        cmd = ["codex", "exec", "--json", *step_args, prompt]
    else:
        cmd = ["codex", "exec", "resume", "--json", *step_args, resume_id, prompt]
    return run_agent_step(cmd, raw_log_fh, cwd=cwd)


def run_agent_step(cmd, raw_log_fh, cwd=None, stdin_text=None):
    events = []  # (monotonic_ts, parsed_json_or_None, raw_line)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL if stdin_text is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=cwd,
    )
    if stdin_text is not None:
        proc.stdin.write(stdin_text)
        proc.stdin.close()
    t_launch = time.monotonic()
    for line in proc.stdout:
        ts = time.monotonic()
        raw_log_fh.write(f"{ts - t_launch:.4f}\t{line}")
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            events.append((ts, None, line))
            continue
        events.append((ts, obj, line))
    proc.wait()
    return t_launch, events, proc.returncode


def _extract_published_asset(item):
    """If this completed mcp_tool_call published a workbook, pull out its identity."""
    if item.get("tool") not in PUBLISHING_TOOLS:
        return None
    try:
        text = (item.get("result") or {})["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None
    return _published_asset(item.get("tool"), item.get("server"), text)


def _published_asset(tool, server, text):
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("status") != "published":
        return None
    data = payload.get("data") or {}
    return {
        "tool": tool,
        "server": server,
        "workbook_id": data.get("id"),
        "name": data.get("name"),
        "content_url": data.get("contentUrl"),
        "project": (data.get("project") or {}).get("name"),
        "webpage_url": data.get("webpageUrl") or payload.get("url"),
    }


def analyze_step_events(t_launch, events, step_index, prompt, wall_start):
    """Turn a raw event stream into a single ordered timeline of tool calls and
    non-tool ("thinking") segments.

    Events already arrive in chronological order, so each is appended to one
    ``timeline`` list (rather than split into separate arrays) tagged with a
    ``segment_type`` discriminator, an ``operation`` category, and absolute
    ``start_offset_s`` / ``end_offset_s`` measured from the rep's ``wall_start``.
    That preserves the interleaving -- e.g. which reasoning segment follows a
    given tool call. Rep-global ``seq`` and ``preceding_tool`` are stamped later
    (in run_test_once) once every step's timeline is concatenated.
    """
    timeline = []
    warnings = []
    errors = []
    created_assets = []
    thread_id = None
    final_message = None
    usage = None

    prev_ts = t_launch
    open_items = {}  # item_id -> (start_ts, item)
    started_processing = False

    for ts, obj, raw in events:
        if obj is None:
            continue
        etype = obj.get("type")

        if etype == "thread.started":
            thread_id = obj.get("thread_id")
            continue

        if etype == "turn.started":
            prev_ts = ts
            started_processing = True
            continue

        if etype == "turn.completed":
            usage = obj.get("usage")
            continue

        if etype == "item.started":
            item = obj["item"]
            if item.get("type") in ("command_execution", "mcp_tool_call"):
                gap = ts - prev_ts
                if started_processing and gap > 0:
                    name = _tool_name(item)
                    timeline.append({
                        "step": step_index, "segment_type": "non_tool_segment",
                        "kind": "pre_tool_call", "operation": "pre_tool_call",
                        "name": None, "label": f"deciding to call {name}",
                        "duration": gap,
                        "start_offset_s": prev_ts - wall_start,
                        "end_offset_s": ts - wall_start,
                        "status": None, "error": None,
                    })
                open_items[item["id"]] = (ts, item)
                prev_ts = ts
            continue

        if etype == "item.completed":
            item = obj["item"]
            itype = item.get("type")

            if itype in ("command_execution", "mcp_tool_call"):
                start_ts, _ = open_items.pop(item["id"], (prev_ts, item))
                timeline.append({
                    "step": step_index, "segment_type": "tool_call",
                    "kind": itype, "operation": classify_operation(itype, item),
                    "name": _tool_name(item), "label": None,
                    "duration": ts - start_ts,
                    "start_offset_s": start_ts - wall_start,
                    "end_offset_s": ts - wall_start,
                    "status": item.get("status"), "error": item.get("error"),
                })
                if itype == "mcp_tool_call":
                    asset = _extract_published_asset(item)
                    if asset:
                        created_assets.append(asset)
                prev_ts = ts

            elif itype == "reasoning":
                timeline.append({
                    "step": step_index, "segment_type": "non_tool_segment",
                    "kind": "reasoning", "operation": "reasoning",
                    "name": None, "label": item.get("text", "")[:80],
                    "duration": ts - prev_ts,
                    "start_offset_s": prev_ts - wall_start,
                    "end_offset_s": ts - wall_start,
                    "status": None, "error": None,
                })
                prev_ts = ts

            elif itype == "agent_message":
                timeline.append({
                    "step": step_index, "segment_type": "non_tool_segment",
                    "kind": "agent_message", "operation": "message",
                    "name": None, "label": item.get("text", "")[:80],
                    "duration": ts - prev_ts,
                    "start_offset_s": prev_ts - wall_start,
                    "end_offset_s": ts - wall_start,
                    "status": None, "error": None,
                })
                final_message = item.get("text")
                prev_ts = ts

            elif itype == "error":
                msg = item.get("message", "")
                if "disallowed by requirements" in msg or "Under-development features" in msg:
                    warnings.append(msg)
                else:
                    errors.append(msg)
                prev_ts = ts
            continue

    # Mark the last agent_message of the step as the "final" one for reporting.
    for seg in reversed(timeline):
        if seg["kind"] == "agent_message":
            seg["kind"] = "final_message"
            break

    return {
        "step": step_index,
        "prompt": prompt,
        "thread_id": thread_id,
        "timeline": timeline,
        "final_message": final_message,
        "usage": usage,
        "warnings": warnings,
        "errors": errors,
        "created_assets": created_assets,
    }


def analyze_claude_step_events(t_launch, events, step_index, prompt, wall_start):
    """`claude -p --output-format stream-json` counterpart of analyze_step_events,
    producing the same step record so reporting, the .hyper build and grading don't
    care which harness ran.

    Claude emits no item.started/item.completed pair: a tool call starts when its
    assistant `tool_use` block arrives and ends at the matching user `tool_result`
    (same id). `thread_id` holds the session id, which `--resume` takes."""
    timeline = []
    warnings = []
    errors = []
    created_assets = []
    session_id = None
    final_message = None
    usage = None

    prev_ts = t_launch
    open_calls = {}  # tool_use_id -> (start_ts, tool_use block)

    def segment(kind, operation, label, ts):
        timeline.append({
            "step": step_index, "segment_type": "non_tool_segment",
            "kind": kind, "operation": operation,
            "name": None, "label": label,
            "duration": ts - prev_ts,
            "start_offset_s": prev_ts - wall_start,
            "end_offset_s": ts - wall_start,
            "status": None, "error": None,
        })

    for ts, obj, raw in events:
        if obj is None:
            continue
        etype = obj.get("type")

        if etype == "system":
            if obj.get("subtype") == "init":
                session_id = obj.get("session_id")
                prev_ts = ts
            continue

        if etype == "result":
            session_id = obj.get("session_id") or session_id
            usage = _claude_usage(obj)
            if obj.get("is_error"):
                errors.append(str(obj.get("result") or obj.get("subtype")))
            continue

        # A subagent's own turns; its Task call is timed as one tool call instead.
        if obj.get("parent_tool_use_id"):
            continue

        content = (obj.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            btype = block.get("type")
            if etype == "assistant" and btype == "tool_use":
                if ts - prev_ts > 0:
                    segment("pre_tool_call", "pre_tool_call", f"deciding to call {_claude_tool_name(block)}", ts)
                open_calls[block.get("id")] = (ts, block)
                prev_ts = ts
            elif etype == "user" and btype == "tool_result":
                start_ts, call = open_calls.pop(block.get("tool_use_id"), (prev_ts, {}))
                server, tool = _claude_tool_parts(call.get("name") or "")
                text = _claude_result_text(block)
                failed = bool(block.get("is_error"))
                timeline.append({
                    "step": step_index, "segment_type": "tool_call",
                    "kind": _claude_tool_kind(call.get("name") or ""),
                    "operation": classify_claude_operation(call),
                    "name": _claude_tool_name(call), "label": None,
                    "duration": ts - start_ts,
                    "start_offset_s": start_ts - wall_start,
                    "end_offset_s": ts - wall_start,
                    "status": "failed" if failed else "completed",
                    "error": text[:2000] if failed else None,
                })
                if server and not failed and tool in PUBLISHING_TOOLS:
                    asset = _published_asset(tool, server, text)
                    if asset:
                        created_assets.append(asset)
                prev_ts = ts
            elif etype == "assistant" and btype == "thinking":
                segment("reasoning", "reasoning", (block.get("thinking") or "")[:80], ts)
                prev_ts = ts
            elif etype == "assistant" and btype == "text":
                segment("agent_message", "message", (block.get("text") or "")[:80], ts)
                final_message = block.get("text")
                prev_ts = ts

    for seg in reversed(timeline):
        if seg["kind"] == "agent_message":
            seg["kind"] = "final_message"
            break

    return {
        "step": step_index,
        "prompt": prompt,
        "thread_id": session_id,
        "timeline": timeline,
        "final_message": final_message,
        "usage": usage,
        "warnings": warnings,
        "errors": errors,
        "created_assets": created_assets,
    }


def _claude_tool_parts(name):
    """mcp__plugin_tableau-dev_TableauDev__publish-workbook -> ("TableauDev", "publish-workbook").
    Built-in tools (Bash, Read, ...) have no server."""
    if not name.startswith("mcp__"):
        return None, name
    server, _, tool = name[len("mcp__"):].rpartition("__")
    return server.rsplit("_", 1)[-1], tool


def _claude_tool_kind(name):
    if name.startswith("mcp__"):
        return "mcp_tool_call"
    return "command_execution" if name == "Bash" else "builtin_tool"


def _claude_tool_name(block):
    """Same naming as _tool_name: server::tool for MCP calls, the command for shell."""
    server, tool = _claude_tool_parts(block.get("name") or "")
    if server:
        return f"{server}::{tool}"
    args = block.get("input") or {}
    if tool == "Bash":
        return (args.get("command") or "")[:80]
    detail = next((args[k] for k in ("file_path", "pattern", "skill", "query", "url", "description") if args.get(k)), "")
    return f"{tool} {detail}".strip()[:80]


def _claude_result_text(block):
    content = block.get("content")
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content if isinstance(content, str) else ""


def _claude_usage(result):
    """Map Claude's usage onto the codex-style keys build_hyper reads. Like codex's,
    input_tokens counts cached input too."""
    u = result.get("usage") or {}
    cached = u.get("cache_read_input_tokens") or 0
    written = u.get("cache_creation_input_tokens") or 0
    return {
        "input_tokens": (u.get("input_tokens") or 0) + cached + written,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": written,
        "output_tokens": u.get("output_tokens"),
        "cost_usd": result.get("total_cost_usd"),
    }


def classify_claude_operation(block):
    """classify_operation for Claude tool calls. Claude reads and writes files with its
    own tools where codex shells out, so those map onto the same categories."""
    server, tool = _claude_tool_parts(block.get("name") or "")
    args = block.get("input") or {}
    if server:
        return tool or "mcp"
    if tool == "Bash":
        return classify_operation("command_execution", args)
    if tool in ("Read", "Grep", "Glob"):
        return "inspect"
    if tool in ("Write", "Edit", "NotebookEdit"):
        path = (args.get("file_path") or "").lower()
        return "xml-write" if path.endswith((".twb", ".twbx", ".xml")) else "file-write"
    return {"ToolSearch": "tool-search", "Skill": "skill-load", "Task": "subagent",
            "Agent": "subagent", "WebFetch": "download"}.get(tool, tool.lower() or "tool")


def classify_operation(itype, item):
    """Normalize a tool call into a coarse operation category, so analysis can
    ask 'which operations are slow / fail most' with a single GROUP BY."""
    if itype == "mcp_tool_call":
        # e.g. Tableau::publish-workbook -> "publish-workbook"
        return item.get("tool") or "mcp"
    cmd = (item.get("command") or "").lower()
    if "curl" in cmd or "wget" in cmd:
        return "download"
    if "validate" in cmd:
        return "validate"
    if any(ext in cmd for ext in (".twb", ".twbx", ".xml")) and (
        ">" in cmd or " tee " in cmd or "python" in cmd or " sd " in cmd or "sed " in cmd
    ):
        return "xml-write"
    if any(tok in cmd for tok in ("sed -n", "cat ", "bat ", " rg ", "grep", " ls ", "find ", " fd ", "head", "tail")):
        return "inspect"
    return "shell"


def _tool_name(item):
    if item.get("type") == "command_execution":
        return item.get("command", "")[:80]
    return f"{item.get('server')}::{item.get('tool')}"


def mark_concurrent_tool_calls(step_results):
    """Flag every tool call whose time span overlaps another's. Agents can run several
    tools at once (Claude often does), and each call's duration is timed on its own, so
    summing durations double-counts the overlap -- see tool_time_once."""
    calls = sorted(
        (e for step in step_results for e in step.get("timeline", [])
         if e["segment_type"] == "tool_call" and e.get("start_offset_s") is not None),
        key=lambda e: e["start_offset_s"],
    )
    for e in calls:
        e["concurrent"] = False
    latest_end, latest = None, None
    for e in calls:
        if latest is not None and e["start_offset_s"] < latest_end:
            e["concurrent"] = latest["concurrent"] = True
        if latest_end is None or e["end_offset_s"] > latest_end:
            latest_end, latest = e["end_offset_s"], e


def tool_time_once(summary):
    """Wall-clock time a rep spent with at least one tool call running, so overlapping
    calls count once. Summaries without offsets fall back to summing durations."""
    calls = [e for step in summary["steps"] for e in step.get("timeline", [])
             if e["segment_type"] == "tool_call"]
    if any(e.get("start_offset_s") is None for e in calls):
        return sum(e["duration"] for e in calls)
    total, cur_start, cur_end = 0.0, None, None
    for start, end in sorted((e["start_offset_s"], e["end_offset_s"]) for e in calls):
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def record_created_assets(test_id, harness, model_label, rep, step_results, ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with _LEDGER_LOCK, ledger_path.open("a") as fh:
        for step in step_results:
            for asset in step.get("created_assets", []):
                entry = {
                    "test_id": test_id,
                    "harness": harness,
                    "model": model_label,
                    "rep": rep,
                    "step": step["step"],
                    "recorded_at": time.time(),
                    **asset,
                }
                fh.write(json.dumps(entry) + "\n")
                print(f"    published: {asset['name']!r} (id {asset['workbook_id']}) -> logged to {ledger_path}")


def run_test_once(test, cfg, model_label, rep_dir, rep, reps, ledger_path, preamble=None, staging_dir=None):
    # Logged here, inside the worker, rather than at submission time -- executor.submit()
    # returns immediately even when the pool is already saturated, so a print in the
    # submission loop would fire for every queued rep at once regardless of --parallel.
    print(f"[{test['id']}] model={model_label} run {rep}/{reps} starting ...", flush=True)
    rep_dir.mkdir(parents=True, exist_ok=True)

    # Whatever codex writes to disk during a run (venvs, extracted/rebuilt .twb/.twbx
    # packages, scratch scripts, ...) happens in its `-C` working directory. Unless a
    # test explicitly pins `cd`, give each run its own throwaway temp dir instead of the
    # invoking directory, so a sweep doesn't dump hundreds of MB of scratch files into
    # the repo root -- and remove it once the run is done.
    work_dir = None
    if cfg.get("cd"):
        run_cfg = cfg
    else:
        work_dir = tempfile.mkdtemp(prefix=f"{cfg['harness']}-bench-{sanitize_label(test['id'])}-")
        run_cfg = {**cfg, "cd": work_dir}

    def run_step(prompt, resume_id, all_dirs, raw_log_fh):
        if run_cfg["harness"] == "claude":
            # Every step re-grants the file dirs: unlike codex's, claude's resume takes --add-dir.
            cmd = build_claude_cmd(run_cfg, resume_id, all_dirs)
            return (*run_agent_step(cmd, raw_log_fh, cwd=run_cfg["cd"], stdin_text=prompt),
                    analyze_claude_step_events)
        if resume_id is None:
            step_args = build_first_step_args(run_cfg)
            for d in all_dirs:
                step_args += ["--add-dir", d]
        else:
            step_args = build_resume_step_args(run_cfg)
        return (*run_codex_step(prompt, resume_id, step_args, raw_log_fh, cwd=run_cfg["cd"]),
                analyze_step_events)

    try:
        step_results = []
        resume_id = None
        wall_start = time.monotonic()

        steps = test["steps"]
        # Resolve every step's files up front so directory access can be granted entirely on
        # the first exec call: `codex exec resume` has no --add-dir, so a later step can't
        # grant its own access. The preamble never carries files of its own.
        all_resolved_files = [resolve_step_files(step) for step in steps]
        all_dirs = sorted({str(p.parent) for files in all_resolved_files for p in files})

        # A suffix no other run shares (parallel reps, other models, earlier sweeps), which the
        # preamble's {run_tag} tells the model to end every workbook name with, so publishes
        # can't collide on a name that already exists in the results project.
        run_tag = f"{test['id'].split('_')[0]}-{sanitize_label(model_label)}-r{rep:02d}-{secrets.token_hex(2)}"

        preamble_wall_time = None
        if preamble:
            preamble = preamble.replace("{run_tag}", run_tag)
            # Test-harness-only instructions, shared by every test, sent as their own turn
            # before the test's actual steps (via the same resume mechanism as a multi-step
            # test) so the model has them in context -- but they're fixed overhead, not part
            # of what a test is measuring, so they're excluded from step_results/summary
            # entirely rather than showing up as a numbered step in tool/timing stats.
            preamble_start = time.monotonic()
            raw_log_path = rep_dir / "step_preamble.jsonl"
            with raw_log_path.open("w") as fh:
                t_launch, events, returncode, analyze = run_step(preamble, resume_id, all_dirs, fh)
            preamble_result = analyze(t_launch, events, -1, preamble, wall_start)
            if preamble_result["thread_id"]:
                resume_id = preamble_result["thread_id"]
            if returncode != 0:
                print(f"    warning: preamble step exited with returncode {returncode}")
            preamble_wall_time = time.monotonic() - preamble_start

        for i, step in enumerate(steps):
            resolved_files = all_resolved_files[i]
            prompt_text = build_prompt_with_files(step["prompt"], resolved_files)

            raw_log_path = rep_dir / f"step_{i}.jsonl"
            with raw_log_path.open("w") as fh:
                t_launch, events, returncode, analyze = run_step(prompt_text, resume_id, all_dirs, fh)
            result = analyze(t_launch, events, i, step["prompt"], wall_start)
            result["files"] = [str(p) for p in resolved_files]
            result["returncode"] = returncode
            step_results.append(result)
            if result["thread_id"]:
                resume_id = result["thread_id"]

        record_created_assets(test["id"], cfg["harness"], model_label, rep, step_results, ledger_path)
        mark_concurrent_tool_calls(step_results)

        # Stamp a rep-global sequence number and the name of the most recent tool
        # call onto every timeline entry, in chronological order across all steps.
        # This gives a single ordering key and lets analysis ask "what happened
        # right after this tool call" (e.g. reasoning that follows a publish).
        seq = 0
        last_tool = None
        for step in step_results:
            for entry in step.get("timeline", []):
                entry["seq"] = seq
                entry["preceding_tool"] = last_tool
                seq += 1
                if entry["segment_type"] == "tool_call":
                    last_tool = entry["name"]

        wall_time = time.monotonic() - wall_start
        summary = {
            "test_id": test["id"],
            "harness": cfg["harness"],
            "model": model_label,
            "run_tag": run_tag,
            "preamble_wall_time": preamble_wall_time,
            "wall_time": wall_time,
            "assetsCreated": any(step.get("created_assets") for step in step_results),
            "steps": step_results,
        }
        (rep_dir / "summary.json").write_text(json.dumps(summary, indent=2))

        # Also drop a uniquely-named copy into the flat staging archive that the
        # .hyper extract is built from. The name encodes test/model/run plus a
        # timestamp so repeated runs accumulate without overwriting; skip if a
        # file with the same name somehow already exists.
        if staging_dir is not None:
            staging_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            flat_name = f"{test['id']}__{sanitize_label(model_label)}__run_{rep:02d}__{stamp}.json"
            flat_path = staging_dir / flat_name
            if not flat_path.exists():
                flat_path.write_text(json.dumps(summary, indent=2))

        return summary
    finally:
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


def aggregate_test(test_id, harness, model_label, rep_summaries, out_path):
    all_tool_calls = []
    all_non_tool = []
    wall_times = []
    final_messages = []
    errors_seen = []

    for s in rep_summaries:
        wall_times.append(s["wall_time"])
        for step in s["steps"]:
            for entry in step.get("timeline", []):
                if entry["segment_type"] == "tool_call":
                    all_tool_calls.append(entry)
                else:
                    all_non_tool.append(entry)
            if step.get("final_message"):
                final_messages.append(step["final_message"])
            errors_seen.extend(step.get("errors", []))

    def stats(vals):
        if not vals:
            return None
        return {
            "n": len(vals),
            "mean": statistics.mean(vals),
            "min": min(vals),
            "max": max(vals),
            "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
        }

    by_tool = {}
    for tc in all_tool_calls:
        by_tool.setdefault(tc["name"], []).append(tc["duration"])
    tool_stats = {name: stats(durs) for name, durs in sorted(by_tool.items())}

    by_kind = {}
    for seg in all_non_tool:
        by_kind.setdefault(seg["kind"], []).append(seg["duration"])
    non_tool_stats = {kind: stats(durs) for kind, durs in sorted(by_kind.items())}

    total_tool_time = sum(tool_time_once(s) for s in rep_summaries)
    total_non_tool_time = sum(seg["duration"] for seg in all_non_tool)

    aggregate = {
        "test_id": test_id,
        "harness": harness,
        "model": model_label,
        "reps": len(rep_summaries),
        "wall_time": stats(wall_times),
        "total_tool_time_mean": total_tool_time / max(len(rep_summaries), 1),
        "total_non_tool_time_mean": total_non_tool_time / max(len(rep_summaries), 1),
        "tool_call_stats": tool_stats,
        "concurrent_tool_calls": {
            name: n for name in by_tool
            if (n := sum(1 for tc in all_tool_calls if tc["name"] == name and tc.get("concurrent")))
        },
        "non_tool_stats": non_tool_stats,
        "final_message_lengths": [len(m) for m in final_messages],
        "errors_seen": errors_seen,
    }
    out_path.write_text(json.dumps(aggregate, indent=2))
    return aggregate


def render_report(aggregates, out_path):
    lines = ["# Bench report", ""]

    by_test = {}
    for agg in aggregates:
        by_test.setdefault(agg["test_id"], []).append(agg)

    for test_id, aggs in by_test.items():
        lines.append(f"## {test_id}")
        if len(aggs) > 1:
            lines.append("")
            lines.append("**Model comparison:**")
            lines.append("")
            lines.append("| harness | model | n | wall time mean (s) | tool time mean (s) | non-tool time mean (s) |")
            lines.append("|---|---|---|---|---|---|")
            for agg in sorted(aggs, key=lambda a: a["wall_time"]["mean"]):
                lines.append(
                    f"| {agg.get('harness', 'codex')} | {agg['model']} | {agg['reps']} | {agg['wall_time']['mean']:.1f} | "
                    f"{agg['total_tool_time_mean']:.1f} | {agg['total_non_tool_time_mean']:.1f} |"
                )
            lines.append("")

        for agg in aggs:
            render_model_section(lines, agg)
        lines.append("")

    out_path.write_text("\n".join(lines))


def render_model_section(lines, agg):
        lines.append(f"### model: {agg['model']} ({agg.get('harness', 'codex')})  (n={agg['reps']})")
        wt = agg["wall_time"]
        lines.append(f"- Wall time: mean {wt['mean']:.1f}s (min {wt['min']:.1f}s, max {wt['max']:.1f}s, stdev {wt['stdev']:.1f}s)")
        lines.append(f"- Tool-call time (avg per run, overlapping calls counted once): {agg['total_tool_time_mean']:.1f}s")
        lines.append(f"- Non-tool-call time (avg per run): {agg['total_non_tool_time_mean']:.1f}s")

        lines.append("")
        lines.append("**Tool calls (avg duration, count across all runs):**")
        if agg["tool_call_stats"]:
            for name, st in sorted(agg["tool_call_stats"].items(), key=lambda kv: -kv[1]["mean"]):
                concurrent = agg.get("concurrent_tool_calls", {}).get(name)
                note = f", {concurrent} alongside another call" if concurrent else ""
                lines.append(f"- `{name}`: {st['mean']:.2f}s avg, {st['n']} calls{note}, range {st['min']:.2f}-{st['max']:.2f}s")
        else:
            lines.append("- (no tool calls)")

        lines.append("")
        lines.append("**Non-tool-call time by phase (largest first):**")
        if agg["non_tool_stats"]:
            for kind, st in sorted(agg["non_tool_stats"].items(), key=lambda kv: -kv[1]["mean"] * kv[1]["n"]):
                total = st["mean"] * st["n"] / agg["reps"]
                lines.append(f"- {kind}: {total:.2f}s/run avg total ({st['n']} occurrences, {st['mean']:.2f}s each avg)")
        else:
            lines.append("- (none)")

        if agg["final_message_lengths"]:
            fl = agg["final_message_lengths"]
            lines.append("")
            lines.append(f"- Final message length: mean {statistics.mean(fl):.0f} chars (min {min(fl)}, max {max(fl)}) — check results/ for actual text diffs")

        if agg["errors_seen"]:
            lines.append("")
            lines.append(f"**Errors seen across runs ({len(agg['errors_seen'])}):**")
            for e in agg["errors_seen"][:5]:
                lines.append(f"- {e[:200]}")

        lines.append("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", type=parse_harnesses, default=["codex"],
                    help=f"Agent CLI(s) to drive, comma-separated to sweep several in one run ({', '.join(HARNESSES)}; default codex)")
    ap.add_argument("--claude-plugin-dir", type=Path, default=DEFAULT_CLAUDE_PLUGIN_DIR,
                    help="Built Claude plugin loaded via --plugin-dir (default: dist/claude-dev/plugins/tableau)")
    ap.add_argument("--prompts-file", type=Path, default=DEFAULT_PROMPTS_FILE)
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    ap.add_argument("--only", help="Run only these tests (comma-separated ids)")
    ap.add_argument("--reps", type=int, help="Override repeats for all tests")
    ap.add_argument("--parallel", type=int, default=3, help="Max concurrent reps across the whole run, spanning tests/models (default 3)")
    ap.add_argument("--models", help="Comma-separated model ids to sweep the same tests across, e.g. gpt-5.6-sol,o3")
    ap.add_argument("--dry-run", action="store_true", help="Print planned commands, don't execute")
    ap.add_argument("--report-only", action="store_true", help="Rebuild report from existing results/")
    ap.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING_DIR,
                    help="Flat archive each rep's result is copied into and the .hyper is built from (default: bench/tableau)")
    ap.add_argument("--hyper-output", type=Path, default=DEFAULT_HYPER_OUTPUT,
                    help="Path of the Tableau .hyper extract built at the end of a run (default: bench/bench_results.hyper)")
    ap.add_argument("--no-hyper", action="store_true", help="Skip building the .hyper extract at the end of the run")
    args = ap.parse_args()
    if args.models and len(args.harness) > 1:
        # Model ids are harness-specific, so one --models list can't apply to several.
        ap.error("--models needs a single --harness; use a {harness: [...]} model mapping in prompts.json instead")

    spec = json.loads(args.prompts_file.read_text())
    defaults = spec.get("defaults", {})
    preamble = spec.get("preamble")
    tests = spec["tests"]
    if args.only:
        only = [i.strip() for i in args.only.split(",") if i.strip()]
        missing = [i for i in only if i not in {t["id"] for t in tests}]
        if missing:
            sys.exit(f"No test with id {', '.join(map(repr, missing))}")
        tests = [t for t in tests if t["id"] in only]

    # Codex's own default model is only a label; Claude's isn't read, so it's "default".
    default_model_label = {"codex": read_config_default_model(), "claude": "default"}
    ledger_path = args.results_dir / "created_assets.jsonl"

    aggregates = []
    # First pass: resolve every (test, harness, model) unit's config. Dry-run and report-only are
    # handled immediately here since neither needs the shared executor below; everything
    # else is queued into `units` so its reps can run alongside every other unit's reps.
    units = []  # (test, cfg, model_label, test_dir, reps)
    for test in tests:
        reps = args.reps or test.get("repeats", defaults.get("repeats", 10))
        test_overrides = {k: v for k, v in test.items() if k in ("sandbox", "approve_for_me", "permission_mode", "cd")}

        # Model resolution, highest precedence first: --models CLI flag (applies to every
        # test) > this test's own "model" > defaults.model. Any of these may be a single
        # model string or a list of models to sweep this test across, or a mapping from
        # harness to either.
        units_for_test = []
        for harness in args.harness:
            if args.models:
                model_overrides = [m.strip() for m in args.models.split(",") if m.strip()]
            else:
                model_overrides = resolve_model_list(test.get("model", defaults.get("model")), harness) or [None]
            units_for_test += [(harness, m) for m in model_overrides]

        for harness, model_override in units_for_test:
            cfg = {**defaults, **test_overrides, "harness": harness}
            if model_override:
                cfg["model"] = model_override
            model_label = cfg.get("model") or default_model_label[harness] or "unknown"

            test_dir = args.results_dir / test["id"] / sanitize_label(model_label)

            if args.dry_run:
                print(f"[{test['id']}] harness={harness} model={model_label} {reps} reps, {len(test['steps'])} step(s):")
                if preamble:
                    print(f"    -> [preamble] {preamble!r}")
                for step in test["steps"]:
                    print(f"    -> {step['prompt']!r}")
                    for f in resolve_step_files(step):
                        print(f"       + file: {f}")
                continue

            if args.report_only:
                rep_summaries = []
                for rep_dir in sorted(test_dir.glob("run_*")):
                    sf = rep_dir / "summary.json"
                    if sf.exists():
                        rep_summaries.append(json.loads(sf.read_text()))
                if rep_summaries:
                    aggregates.append(aggregate_test(test["id"], harness, model_label, rep_summaries, test_dir / "aggregate.json"))
                continue

            # Wipe any prior runs for this test+model before starting fresh ones, so a lower
            # rep count (e.g. 10 -> 1) doesn't leave stale run_NN/aggregate.json behind to
            # confuse report rendering or grading.
            if test_dir.exists():
                shutil.rmtree(test_dir)
            units.append((test, cfg, model_label, test_dir, reps))

    if args.dry_run or args.report_only:
        if not args.dry_run and aggregates:
            report_path = args.results_dir / "report.md"
            render_report(aggregates, report_path)
            print(f"\nReport written to {report_path}")
        return

    # Second pass: flatten every unit's reps into one shared pool bounded by --parallel, so
    # independent tests/models run concurrently too -- not just reps within a single one.
    work_items = [
        (unit_index, rep)
        for unit_index, (_, _, _, _, reps) in enumerate(units)
        for rep in range(1, reps + 1)
    ]
    results_by_unit = {i: {} for i in range(len(units))}
    claude_auth_dir = None
    if "claude" in args.harness:
        if not (args.claude_plugin_dir / ".claude-plugin" / "plugin.json").exists():
            sys.exit(f"{args.claude_plugin_dir} is not a built plugin -- run "
                     "`python3 build/build.py --variant dev claude` first")
        claude_auth_dir = tempfile.mkdtemp(prefix="claude-bench-auth-")
        claude_settings = write_claude_auth_settings(claude_auth_dir)
        for _, cfg, *_ in units:
            if cfg["harness"] != "claude":
                continue
            cfg["claude_settings"] = claude_settings
            cfg["claude_plugin_dir"] = args.claude_plugin_dir.resolve()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {}
            for unit_index, rep in work_items:
                test, cfg, model_label, test_dir, reps = units[unit_index]
                rep_dir = test_dir / f"run_{rep:02d}"
                fut = executor.submit(run_test_once, test, cfg, model_label, rep_dir, rep, reps, ledger_path, preamble=preamble, staging_dir=args.staging_dir)
                futures[fut] = (unit_index, rep)
            for fut in concurrent.futures.as_completed(futures):
                unit_index, rep = futures[fut]
                test, cfg, model_label, test_dir, reps = units[unit_index]
                summary = fut.result()
                results_by_unit[unit_index][rep] = summary
                print(f"[{test['id']}] model={model_label} run {rep}/{reps} done in {summary['wall_time']:.1f}s", flush=True)
    finally:
        if claude_auth_dir:
            shutil.rmtree(claude_auth_dir, ignore_errors=True)

    for unit_index, (test, cfg, model_label, test_dir, reps) in enumerate(units):
        rep_summaries = [results_by_unit[unit_index][r] for r in sorted(results_by_unit[unit_index])]
        if rep_summaries:
            aggregates.append(aggregate_test(test["id"], cfg["harness"], model_label, rep_summaries, test_dir / "aggregate.json"))

    if aggregates:
        report_path = args.results_dir / "report.md"
        render_report(aggregates, report_path)
        print(f"\nReport written to {report_path}")

    # Rebuild the Tableau .hyper extract from the whole staging archive, so the
    # run finishes with an up-to-date extract combining this run with any earlier
    # ones already staged. Kept optional (--no-hyper) since it needs tableauhyperapi.
    if not args.no_hyper:
        try:
            from build_hyper import write_hyper
        except ImportError as exc:
            print(f"\nSkipping .hyper build ({exc}); install tableauhyperapi to enable it.")
        else:
            write_hyper(args.staging_dir, args.hyper_output)


if __name__ == "__main__":
    main()

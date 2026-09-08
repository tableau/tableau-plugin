#!/usr/bin/env python3
"""
Repeatedly run codex exec against a set of test cases (from prompts.json),
recording every tool call (shell + MCP) with its duration, and every
non-tool-call ("thinking") interval between decision points. Produces a
per-run JSON record, a per-test aggregate, and a Markdown report.

Usage:
  python3 bench/run_bench.py                     # run everything in prompts.json
  python3 bench/run_bench.py --only cold_bar_chart
  python3 bench/run_bench.py --models gpt-5.6-sol,o3   # sweep the same tests across models
  python3 bench/run_bench.py --reps 2 --dry-run   # sanity-check commands first
  python3 bench/run_bench.py --report-only        # rebuild report.md from saved results/
"""
import argparse
import concurrent.futures
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPTS_FILE = ROOT / "prompts.json"
DEFAULT_RESULTS_DIR = ROOT / "results"
CODEX_CONFIG_TOML = Path.home() / ".codex" / "config.toml"

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


def sanitize_label(label):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label)


def resolve_model_list(value):
    """`model` (in defaults or a test override) may be a single model string, a list of
    models to sweep across, or None/empty to leave it up to codex's own default."""
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


def run_codex_step(prompt, resume_id, step_args, raw_log_fh, cwd=None):
    if resume_id is None:
        cmd = ["codex", "exec", "--json", *step_args, prompt]
    else:
        cmd = ["codex", "exec", "resume", "--json", *step_args, resume_id, prompt]

    events = []  # (monotonic_ts, parsed_json_or_None, raw_line)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=cwd,
    )
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
    result = item.get("result") or {}
    try:
        text = result["content"][0]["text"]
        payload = json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None
    if payload.get("status") != "published":
        return None
    data = payload.get("data") or {}
    return {
        "tool": item.get("tool"),
        "server": item.get("server"),
        "workbook_id": data.get("id"),
        "name": data.get("name"),
        "content_url": data.get("contentUrl"),
        "project": (data.get("project") or {}).get("name"),
        "webpage_url": data.get("webpageUrl") or payload.get("url"),
    }


def analyze_step_events(t_launch, events, step_index, prompt):
    """Turn a raw event stream into tool_calls + non_tool_segments with durations."""
    tool_calls = []
    non_tool_segments = []
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
                    non_tool_segments.append({
                        "step": step_index, "kind": "pre_tool_call",
                        "label": f"deciding to call {name}", "duration": gap,
                    })
                open_items[item["id"]] = (ts, item)
                prev_ts = ts
            continue

        if etype == "item.completed":
            item = obj["item"]
            itype = item.get("type")

            if itype in ("command_execution", "mcp_tool_call"):
                start_ts, _ = open_items.pop(item["id"], (prev_ts, item))
                duration = ts - start_ts
                tool_calls.append({
                    "step": step_index,
                    "kind": itype,
                    "name": _tool_name(item),
                    "duration": duration,
                    "status": item.get("status"),
                    "error": item.get("error"),
                })
                if itype == "mcp_tool_call":
                    asset = _extract_published_asset(item)
                    if asset:
                        created_assets.append(asset)
                prev_ts = ts

            elif itype == "reasoning":
                gap = ts - prev_ts
                non_tool_segments.append({
                    "step": step_index, "kind": "reasoning",
                    "label": item.get("text", "")[:80], "duration": gap,
                })
                prev_ts = ts

            elif itype == "agent_message":
                gap = ts - prev_ts
                non_tool_segments.append({
                    "step": step_index, "kind": "agent_message",
                    "label": item.get("text", "")[:80], "duration": gap,
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
    for seg in reversed(non_tool_segments):
        if seg["kind"] == "agent_message":
            seg["kind"] = "final_message"
            break

    return {
        "step": step_index,
        "prompt": prompt,
        "thread_id": thread_id,
        "tool_calls": tool_calls,
        "non_tool_segments": non_tool_segments,
        "final_message": final_message,
        "usage": usage,
        "warnings": warnings,
        "errors": errors,
        "created_assets": created_assets,
    }


def _tool_name(item):
    if item.get("type") == "command_execution":
        return item.get("command", "")[:80]
    return f"{item.get('server')}::{item.get('tool')}"


def record_created_assets(test_id, model_label, rep, step_results, ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with _LEDGER_LOCK, ledger_path.open("a") as fh:
        for step in step_results:
            for asset in step.get("created_assets", []):
                entry = {
                    "test_id": test_id,
                    "model": model_label,
                    "rep": rep,
                    "step": step["step"],
                    "recorded_at": time.time(),
                    **asset,
                }
                fh.write(json.dumps(entry) + "\n")
                print(f"    published: {asset['name']!r} (id {asset['workbook_id']}) -> logged to {ledger_path}")


def run_test_once(test, cfg, model_label, rep_dir, rep, reps, ledger_path, preamble=None):
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
        work_dir = tempfile.mkdtemp(prefix=f"codex-bench-{sanitize_label(test['id'])}-")
        run_cfg = {**cfg, "cd": work_dir}

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

        preamble_wall_time = None
        if preamble:
            # Test-harness-only instructions, shared by every test, sent as their own turn
            # before the test's actual steps (via the same resume mechanism as a multi-step
            # test) so the model has them in context -- but they're fixed overhead, not part
            # of what a test is measuring, so they're excluded from step_results/summary
            # entirely rather than showing up as a numbered step in tool/timing stats.
            preamble_start = time.monotonic()
            step_args = build_first_step_args(run_cfg)
            for d in all_dirs:
                step_args += ["--add-dir", d]
            raw_log_path = rep_dir / "step_preamble.jsonl"
            with raw_log_path.open("w") as fh:
                t_launch, events, returncode = run_codex_step(preamble, resume_id, step_args, fh, cwd=run_cfg["cd"])
            preamble_result = analyze_step_events(t_launch, events, -1, preamble)
            if preamble_result["thread_id"]:
                resume_id = preamble_result["thread_id"]
            if returncode != 0:
                print(f"    warning: preamble step exited with returncode {returncode}")
            preamble_wall_time = time.monotonic() - preamble_start

        for i, step in enumerate(steps):
            resolved_files = all_resolved_files[i]
            prompt_text = build_prompt_with_files(step["prompt"], resolved_files)

            if resume_id is None:
                step_args = build_first_step_args(run_cfg)
                for d in all_dirs:
                    step_args += ["--add-dir", d]
            else:
                step_args = build_resume_step_args(run_cfg)

            raw_log_path = rep_dir / f"step_{i}.jsonl"
            with raw_log_path.open("w") as fh:
                t_launch, events, returncode = run_codex_step(prompt_text, resume_id, step_args, fh, cwd=run_cfg["cd"])
            result = analyze_step_events(t_launch, events, i, step["prompt"])
            result["files"] = [str(p) for p in resolved_files]
            result["returncode"] = returncode
            step_results.append(result)
            if result["thread_id"]:
                resume_id = result["thread_id"]

        record_created_assets(test["id"], model_label, rep, step_results, ledger_path)

        wall_time = time.monotonic() - wall_start
        summary = {
            "test_id": test["id"],
            "model": model_label,
            "preamble_wall_time": preamble_wall_time,
            "wall_time": wall_time,
            "assetsCreated": any(step.get("created_assets") for step in step_results),
            "steps": step_results,
        }
        (rep_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary
    finally:
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


def aggregate_test(test_id, model_label, rep_summaries, out_path):
    all_tool_calls = []
    all_non_tool = []
    wall_times = []
    final_messages = []
    errors_seen = []

    for s in rep_summaries:
        wall_times.append(s["wall_time"])
        for step in s["steps"]:
            all_tool_calls.extend(step["tool_calls"])
            all_non_tool.extend(step["non_tool_segments"])
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

    total_tool_time = sum(tc["duration"] for tc in all_tool_calls)
    total_non_tool_time = sum(seg["duration"] for seg in all_non_tool)

    aggregate = {
        "test_id": test_id,
        "model": model_label,
        "reps": len(rep_summaries),
        "wall_time": stats(wall_times),
        "total_tool_time_mean": total_tool_time / max(len(rep_summaries), 1),
        "total_non_tool_time_mean": total_non_tool_time / max(len(rep_summaries), 1),
        "tool_call_stats": tool_stats,
        "non_tool_stats": non_tool_stats,
        "final_message_lengths": [len(m) for m in final_messages],
        "errors_seen": errors_seen,
    }
    out_path.write_text(json.dumps(aggregate, indent=2))
    return aggregate


def render_report(aggregates, out_path):
    lines = ["# Codex bench report", ""]

    by_test = {}
    for agg in aggregates:
        by_test.setdefault(agg["test_id"], []).append(agg)

    for test_id, aggs in by_test.items():
        lines.append(f"## {test_id}")
        if len(aggs) > 1:
            lines.append("")
            lines.append("**Model comparison:**")
            lines.append("")
            lines.append("| model | n | wall time mean (s) | tool time mean (s) | non-tool time mean (s) |")
            lines.append("|---|---|---|---|---|")
            for agg in sorted(aggs, key=lambda a: a["wall_time"]["mean"]):
                lines.append(
                    f"| {agg['model']} | {agg['reps']} | {agg['wall_time']['mean']:.1f} | "
                    f"{agg['total_tool_time_mean']:.1f} | {agg['total_non_tool_time_mean']:.1f} |"
                )
            lines.append("")

        for agg in aggs:
            render_model_section(lines, agg)
        lines.append("")

    out_path.write_text("\n".join(lines))


def render_model_section(lines, agg):
        lines.append(f"### model: {agg['model']}  (n={agg['reps']})")
        wt = agg["wall_time"]
        lines.append(f"- Wall time: mean {wt['mean']:.1f}s (min {wt['min']:.1f}s, max {wt['max']:.1f}s, stdev {wt['stdev']:.1f}s)")
        lines.append(f"- Tool-call time (avg per run): {agg['total_tool_time_mean']:.1f}s")
        lines.append(f"- Non-tool-call time (avg per run): {agg['total_non_tool_time_mean']:.1f}s")

        lines.append("")
        lines.append("**Tool calls (avg duration, count across all runs):**")
        if agg["tool_call_stats"]:
            for name, st in sorted(agg["tool_call_stats"].items(), key=lambda kv: -kv[1]["mean"]):
                lines.append(f"- `{name}`: {st['mean']:.2f}s avg, {st['n']} calls, range {st['min']:.2f}-{st['max']:.2f}s")
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
    ap.add_argument("--prompts-file", type=Path, default=DEFAULT_PROMPTS_FILE)
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    ap.add_argument("--only", help="Run only the test with this id")
    ap.add_argument("--reps", type=int, help="Override repeats for all tests")
    ap.add_argument("--parallel", type=int, default=3, help="Max concurrent reps across the whole run, spanning tests/models (default 3)")
    ap.add_argument("--models", help="Comma-separated model ids to sweep the same tests across, e.g. gpt-5.6-sol,o3")
    ap.add_argument("--dry-run", action="store_true", help="Print planned commands, don't execute")
    ap.add_argument("--report-only", action="store_true", help="Rebuild report from existing results/")
    args = ap.parse_args()

    spec = json.loads(args.prompts_file.read_text())
    defaults = spec.get("defaults", {})
    preamble = spec.get("preamble")
    tests = spec["tests"]
    if args.only:
        tests = [t for t in tests if t["id"] == args.only]
        if not tests:
            sys.exit(f"No test with id {args.only!r}")

    config_default_model = read_config_default_model()
    ledger_path = args.results_dir / "created_assets.jsonl"

    aggregates = []
    # First pass: resolve every (test, model) unit's config. Dry-run and report-only are
    # handled immediately here since neither needs the shared executor below; everything
    # else is queued into `units` so its reps can run alongside every other unit's reps.
    units = []  # (test, cfg, model_label, test_dir, reps)
    for test in tests:
        reps = args.reps or test.get("repeats", defaults.get("repeats", 10))
        test_overrides = {k: v for k, v in test.items() if k in ("sandbox", "approve_for_me", "cd")}

        # Model resolution, highest precedence first: --models CLI flag (applies to every
        # test) > this test's own "model" > defaults.model. Any of these may be a single
        # model string or a list of models to sweep this test across.
        if args.models:
            model_overrides = [m.strip() for m in args.models.split(",") if m.strip()]
        else:
            model_overrides = resolve_model_list(test.get("model", defaults.get("model"))) or [None]

        for model_override in model_overrides:
            cfg = {**defaults, **test_overrides}
            if model_override:
                cfg["model"] = model_override
            model_label = cfg.get("model") or config_default_model or "unknown"

            test_dir = args.results_dir / test["id"] / sanitize_label(model_label)

            if args.dry_run:
                print(f"[{test['id']}] model={model_label} {reps} reps, {len(test['steps'])} step(s):")
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
                    aggregates.append(aggregate_test(test["id"], model_label, rep_summaries, test_dir / "aggregate.json"))
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = {}
        for unit_index, rep in work_items:
            test, cfg, model_label, test_dir, reps = units[unit_index]
            rep_dir = test_dir / f"run_{rep:02d}"
            fut = executor.submit(run_test_once, test, cfg, model_label, rep_dir, rep, reps, ledger_path, preamble=preamble)
            futures[fut] = (unit_index, rep)
        for fut in concurrent.futures.as_completed(futures):
            unit_index, rep = futures[fut]
            test, cfg, model_label, test_dir, reps = units[unit_index]
            summary = fut.result()
            results_by_unit[unit_index][rep] = summary
            print(f"[{test['id']}] model={model_label} run {rep}/{reps} done in {summary['wall_time']:.1f}s", flush=True)

    for unit_index, (test, cfg, model_label, test_dir, reps) in enumerate(units):
        rep_summaries = [results_by_unit[unit_index][r] for r in sorted(results_by_unit[unit_index])]
        if rep_summaries:
            aggregates.append(aggregate_test(test["id"], model_label, rep_summaries, test_dir / "aggregate.json"))

    if aggregates:
        report_path = args.results_dir / "report.md"
        render_report(aggregates, report_path)
        print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    main()

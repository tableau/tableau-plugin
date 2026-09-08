# Codex bench

Runs a set of Tableau-plugin prompts against `codex exec` N times each, records
every tool call (shell + MCP) with its duration, records every non-tool-call
"thinking" interval, and rolls it all up into a report. Also tracks any
workbooks published to the live Tableau site during test runs and gives you a
way to clean them up.

## Setup

The benchmark scripts and assets live on the dedicated `benchmarking` branch,
not on `main` or a feature branch. To run them against plugin code you want to
measure:

1. Check out `benchmarking`.
2. Rebase it onto the branch under test, so the plugin in this checkout is
   the version you're measuring.
3. Reinstall the plugin (`./reload-plugin.sh` from the repo root, then start a
   new Codex task). Codex copies plugin files into its cache at install time,
   so a checkout/rebase has no effect until you reinstall.

```bash
git checkout benchmarking
git rebase <branch-under-test>
./reload-plugin.sh
```

No other dependencies beyond Python 3 stdlib and the `codex` CLI already being
authenticated with the Tableau plugin installed. From the repo root:

```bash
python3 bench/run_bench.py --dry-run
```

`--dry-run` prints every test's prompt(s) and any attached files without
calling codex — use it to sanity-check `prompts.json` before spending real
runs.

## Running tests

```bash
python3 bench/run_bench.py                        # run every test in prompts.json
python3 bench/run_bench.py --only AC10_cold        # just one test
python3 bench/run_bench.py --only AC10_cold --reps 2   # override repeat count
python3 bench/run_bench.py --models gpt-5.6-sol    # sweep the same tests across models (comma-separated)
python3 bench/run_bench.py --report-only           # rebuild report.md from existing results/, no new runs
python3 bench/run_bench.py --parallel 5            # run up to 5 reps concurrently across the whole sweep (default 3)
```

Every rep of every test+model in the sweep is queued into one shared thread pool bounded by
`--parallel` (default 3) -- so independent tests and models run concurrently, not just reps
within the same test. Each rep is an independent `codex exec` subprocess writing to its own
`run_NN/`, so there's no shared state beyond the `created_assets.jsonl` ledger (append-guarded
by a lock). Raise `--parallel` cautiously: it multiplies concurrent model/API usage and
concurrent live Tableau site calls (the preamble's "use unique names" instruction is what
keeps concurrent `publish-workbook` calls from colliding).

Each run's `codex exec`/`codex exec resume` subprocess has its OS working directory pinned to
the same throwaway temp dir passed via `-C`, so shell commands the model runs (writing
`.twbx` files, scratch folders, etc.) land there and get cleaned up with it -- not in whatever
directory you launched `run_bench.py` from.

Each test runs `repeats` times (10 by default). For each run, the harness
launches `codex exec --json ...` (chaining any additional steps onto the same
thread with `codex exec resume`), timestamps every JSONL event as it arrives,
and writes:

- `bench/results/<test_id>/<model>/run_NN/step_*.jsonl` — raw event log with a
relative-seconds timestamp prefixed on every line.
- `bench/results/<test_id>/<model>/run_NN/summary.json` — parsed record for
that run: every tool call with its duration, every non-tool "thinking" gap
(see below), the final message, token usage, and any errors/warnings.
- `bench/results/<test_id>/<model>/aggregate.json` — mean/min/max/stdev across
all reps for that test+model.
- `bench/results/report.md` — the human-readable rollup, generated after all
tests finish (or by `--report-only`). If a test ran under 2+ models, its
section starts with a comparison table (wall time / tool time / non-tool
time per model, fastest first) before the per-model detail.

Non-tool-call time is split into:

- `reasoning` — visible reasoning summaries
- `pre_tool_call` — time spent deciding to call a specific tool, up to the
moment the call starts
- `agent_message` — interim assistant messages
- `final_message` — the last assistant message of the step



### Model tracking

Every run records which model it used. `model` (in `defaults` or on a specific test)
can be a single model string, a list of models to sweep, or omitted/`null`. Resolution,
highest precedence first: the `--models` CLI flag (applies to every test) > that test's
own `model` > `defaults.model`. If none of those resolve to a model, the harness reads
the `model = "..."` line from `~/.codex/config.toml` to label the run (without forcing
`-m`, so the label reflects whatever codex actually used by default).

Whenever a test resolves to more than one model, it runs the *entire* rep count once
per model, each with `-m <model>` passed explicitly, under separate
`results/<test_id>/<model>/` directories — so you can directly compare how different
models perform on the same prompts. E.g. `"model": ["gpt-5.6-sol", "<other-valid-model>"]`
in `defaults` sweeps every test across both; overriding `model` on one specific test
limits the sweep to just that test.

**Valid model strings**: 

- gpt-5.6-sol
- gpt-5.6-terra
- gpt-5.6-luna
- gpt-5.5
- gpt-5.4
- gpt-5.4-mini



## `prompts.json` schema

```json
{
  "preamble": "instructions shared by every test, run as its own turn before each test's steps",
  "defaults": {
    "repeats": 10,
    "sandbox": "workspace-write",
    "approve_for_me": true,
    "model": null,
    "cd": null
  },
  "tests": [
    {
      "id": "unique_id",
      "description": "human-readable note",
      "repeats": 10,
      "model": ["gpt-5.6-sol", "<other-valid-model>"],
      "steps": [
        { "prompt": "..." },
        { "prompt": "...", "files": ["bench/fixtures/some_file.csv"] }
      ]
    }
  ]
}
```

- `preamble` (optional, top-level): a prompt sent as its own turn before
every test's steps (via the same cold/resume mechanism as multi-step tests
below). Use it for test-harness-only instructions that aren't part of the
plugin's own skill guidance — e.g. how to handle confirmations during a
benchmark run. It's fixed overhead shared by every test, so it's deliberately
kept out of `summary.json`'s `steps` (and therefore out of tool/timing
aggregates) — it runs as `step_preamble.jsonl` in each run's output, and its
own wall time is recorded separately as `preamble_wall_time`.
- `defaults` apply to every test unless overridden. `sandbox` and
`approve_for_me` are mutually exclusive (`--approve-for-me` implies
`workspace-write`); leave `approve_for_me: true` unless you need a
different sandbox policy.
- **A test with one step** = a single cold prompt.
- **A test with multiple steps** = a multi-turn scenario in one thread — e.g.
a context-setting turn followed by the actual task, to compare "cold" vs
"primed" performance. Step 2+ is sent via `codex exec resume`, which does
**not** support `--sandbox`/`--approve-for-me`/`--add-dir` — those only
take effect on step 1, so a later step needing shell approval or extra
directory access can stall. Put anything that needs those on step 1.
- `files` (optional, per step): paths to local files (relative to the
repo root, or absolute) that the prompt should reference. The harness
resolves and verifies each path exists, appends the absolute path(s) to the
prompt text so the model knows where to read them from disk, and grants
sandbox access to every referenced file's directory via `--add-dir` on the
first exec call — `codex exec resume` has no `--add-dir` of its own, so any
directory a later step's files need is granted up front instead. There's no
binary file-attach channel in `codex exec` (only `-i/--image` for images) —
this only works for files the model can read as text/data itself.
- `cd` (optional, in `defaults` or per-test): working directory `codex exec`
runs in, passed through as `-C <cd>`. Only takes effect on step 1 (same
`codex exec resume` limitation as `--sandbox`/`--approve-for-me`/`--add-dir`
above) — later steps inherit step 1's directory. Leave it `null` (the
default) to run from wherever you invoke `run_bench.py`; set it if a test's
prompt relies on relative paths or expects codex's shell commands to execute
somewhere other than the repo root.
- Per-test overrides: `repeats`, `sandbox`, `approve_for_me`, `model`, `cd`.
`model` (in `defaults` or per-test) may be a string or a list — see Model
tracking above for how a list triggers a sweep.



## Tracking and cleaning up published workbooks

Any successful `publish-workbook` MCP call during a run is logged to
`bench/results/created_assets.jsonl` (workbook id, name, project, URL) as it
happens — so partial/crashed sweeps don't lose track of what they created on
the live site.

```bash
python3 bench/cleanup_assets.py            # dry run: lists tracked, not-yet-deleted workbooks
python3 bench/cleanup_assets.py --yes      # preview + confirm-delete each one
python3 bench/cleanup_assets.py --yes --limit 3   # cap how many get deleted in one run
```

`--yes` talks directly to the Tableau MCP server's `delete-content` tool over
stdio JSON-RPC (no LLM involved — deterministic calls with fixed arguments),
using the same preview-then-confirm flow the plugin itself relies on, so
deleted workbooks land in Tableau Cloud's recycle bin. If the site has the
`mcp-apps` feature gate on, that tool refuses a script-driven confirm and
requires a human click in Tableau's UI — the script detects this and reports
those assets as needing manual deletion (with a direct link) instead of
trying to work around it. Progress is saved to `bench/results/cleanup_state.json`
so re-running `cleanup_assets.py` skips anything already deleted.

## Grading runs against reference fixtures

`bench/fixtures/<ACxx>/` holds a reference for each test (matched by the test id's
`ACxx` prefix, e.g. `AC01_cold` -> `bench/fixtures/AC01/`): a reference image
(`dashboard.svg` or `sheet.svg`) and, where applicable, a reference `data.csv`. A
perfect match isn't expected -- chart/dashboard design is subjective -- so grading
asks a model to judge whether each run's output satisfies the same analytical intent,
not diff it exactly.

```bash
python3 bench/grade_results.py                  # grade every completed, ungraded run
python3 bench/grade_results.py --only AC01_cold
python3 bench/grade_results.py --judge-model gpt-5.6-sol
python3 bench/grade_results.py --regrade         # re-grade runs that already have a score
```

For each run, it looks up the workbook that run published (from
`created_assets.jsonl`), calls the Tableau MCP server directly (no LLM) to find that
workbook's most recently updated view — a best-effort proxy for "the view this run
produced," not a guarantee on workbooks with many pre-existing sheets — and fetches
its rendered image + underlying data. It then rasterizes the reference SVG (via
macOS's `qlmanage`) and calls `codex exec` with both images attached plus the
reference/produced data inlined, using `--output-schema` to get back a structured
`{visual_match, visual_rationale, data_match, data_rationale}` score (1-5 each).

Output per run: `results/<test_id>/<model>/run_NN/grading/{reference.png, produced.png, produced_data.csv, judge_result.json}`. Aggregated scores land in
`results/grading_report.md`. Runs with no published asset, or a fixture with no
reference image/data, are reported as skipped rather than scored.

## Notes

- `bench/results/` is gitignored — it holds raw output from real runs against
a live Tableau site and shouldn't be committed.
- Re-running `--report-only` after manually deleting a `run_NN/` directory
(e.g. to discard a bad run) will just skip it when rebuilding the report.


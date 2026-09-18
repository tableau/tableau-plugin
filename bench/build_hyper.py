#!/usr/bin/env python3
"""Build a Tableau .hyper extract from staged benchmark result JSON files.

Reads every ``*.json`` file in a staging directory (default: ``bench/tableau``)
and writes a single ``.hyper`` file (default: ``bench/bench_results.hyper``).

``run_bench.py`` writes each rep's result straight into the staging directory
(uniquely named ``<test>__<model>__<run>__<datetime>.json``) and calls
``write_hyper`` at the end of a run, so the whole flow is one command. This
module is also runnable on its own to rebuild the extract from the staging
directory without re-running any tests.

Each JSON file has some top-level metadata plus a ``steps`` array. Every step
carries a single ordered ``timeline`` array whose entries are either tool calls
or non-tool ("thinking") segments, distinguished by ``segment_type``. This
script emits ONE ROW per timeline entry. Row ordering within a rep is preserved
by ``seq`` and by the ``start_offset_s`` / ``end_offset_s`` columns (seconds
from the rep's start), so you can see exactly what ran when and what followed a
given tool call. The requested top-level properties (``test_id``, ``model``,
``wall_time``, ``assetsCreated``) and step-level context (prompt, final message,
token usage) are repeated on every row.

Requires the Tableau Hyper API:  pip install tableauhyperapi
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tableauhyperapi import (
    Connection,
    CreateMode,
    HyperProcess,
    Inserter,
    NULLABLE,
    SqlType,
    TableDefinition,
    TableName,
    Telemetry,
)

# One shared table for the whole timeline. Columns that only apply to one kind
# of row (name/status/error for tool calls, label for segments) are left NULL on
# the other kind.
TABLE = TableDefinition(
    table_name=TableName("Extract", "segments"),
    columns=[
        # Unique numeric identifier for each row across the whole extract.
        TableDefinition.Column("row_id", SqlType.big_int(), NULLABLE),
        # Repeated top-level metadata.
        TableDefinition.Column("test_id", SqlType.text(), NULLABLE),
        TableDefinition.Column("model", SqlType.text(), NULLABLE),
        TableDefinition.Column("wall_time", SqlType.double(), NULLABLE),
        TableDefinition.Column("assetsCreated", SqlType.bool(), NULLABLE),
        TableDefinition.Column("source_file", SqlType.text(), NULLABLE),
        # Step-level context (repeated on every row belonging to the step).
        TableDefinition.Column("prompt", SqlType.text(), NULLABLE),
        TableDefinition.Column("final_message", SqlType.text(), NULLABLE),
        TableDefinition.Column("input_tokens", SqlType.big_int(), NULLABLE),
        TableDefinition.Column("cached_input_tokens", SqlType.big_int(), NULLABLE),
        TableDefinition.Column("cache_write_input_tokens", SqlType.big_int(), NULLABLE),
        TableDefinition.Column("output_tokens", SqlType.big_int(), NULLABLE),
        TableDefinition.Column("reasoning_output_tokens", SqlType.big_int(), NULLABLE),
        # Timeline entry (ordering + timing + detail).
        TableDefinition.Column("seq", SqlType.big_int(), NULLABLE),
        TableDefinition.Column("step", SqlType.int(), NULLABLE),
        TableDefinition.Column("segment_type", SqlType.text(), NULLABLE),
        TableDefinition.Column("kind", SqlType.text(), NULLABLE),
        TableDefinition.Column("operation", SqlType.text(), NULLABLE),
        TableDefinition.Column("name", SqlType.text(), NULLABLE),
        TableDefinition.Column("label", SqlType.text(), NULLABLE),
        TableDefinition.Column("preceding_tool", SqlType.text(), NULLABLE),
        TableDefinition.Column("duration", SqlType.double(), NULLABLE),
        TableDefinition.Column("start_offset_s", SqlType.double(), NULLABLE),
        TableDefinition.Column("end_offset_s", SqlType.double(), NULLABLE),
        TableDefinition.Column("status", SqlType.text(), NULLABLE),
        TableDefinition.Column("error", SqlType.text(), NULLABLE),
    ],
)

# Column order used when building each row, minus the leading row_id (assigned
# at insert time). Keep in sync with TABLE above.
_ROW_ORDER = [c.name.unescaped for c in TABLE.columns][1:]


def _text(value):
    """Coerce a value into something a Hyper text column accepts.

    Some fields (notably ``error``) are sometimes objects rather than strings;
    serialize those to JSON so they still land in the text column.
    """
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _classify_operation(kind, name):
    """Coarse operation category for a row, from its kind and name. Mirrors
    run_bench.classify_operation but works from the already-flattened name (used
    for legacy files that predate the ``operation`` field)."""
    if kind == "mcp_tool_call":
        return (name or "").split("::")[-1] or "mcp"
    if kind == "command_execution":
        cmd = (name or "").lower()
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
    if kind in ("agent_message", "final_message"):
        return "message"
    return kind  # reasoning, pre_tool_call, ...


def _legacy_timeline(step):
    """Build timeline-shaped entries from a pre-timeline summary (separate
    tool_calls / non_tool_segments arrays). Ordering was lost when those arrays
    were split, so seq / offsets / preceding_tool stay null."""
    for tc in step.get("tool_calls", []) or []:
        yield {
            "segment_type": "tool_call", "step": tc.get("step"),
            "kind": tc.get("kind"), "operation": _classify_operation(tc.get("kind"), tc.get("name")),
            "name": tc.get("name"), "label": None,
            "duration": tc.get("duration"), "status": tc.get("status"), "error": tc.get("error"),
        }
    for seg in step.get("non_tool_segments", []) or []:
        yield {
            "segment_type": "non_tool_segment", "step": seg.get("step"),
            "kind": seg.get("kind"), "operation": _classify_operation(seg.get("kind"), None),
            "name": None, "label": seg.get("label"),
            "duration": seg.get("duration"), "status": None, "error": None,
        }


def flatten_file(path: Path):
    """Yield one row (list matching TABLE columns, minus row_id) per timeline entry.

    Handles both the current single-``timeline`` schema and the legacy
    ``tool_calls`` / ``non_tool_segments`` schema.
    """
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  ! skipping {path.name}: {exc}", file=sys.stderr)
        return

    test_id = data.get("test_id")
    model = data.get("model")
    wall_time = data.get("wall_time")
    assets_created = data.get("assetsCreated")

    for step in data.get("steps", []) or []:
        usage = step.get("usage") or {}
        prompt = _text(step.get("prompt"))
        final_message = _text(step.get("final_message"))
        tokens = [
            usage.get("input_tokens"),
            usage.get("cached_input_tokens"),
            usage.get("cache_write_input_tokens"),
            usage.get("output_tokens"),
            usage.get("reasoning_output_tokens"),
        ]
        timeline = step.get("timeline")
        if timeline is None:
            timeline = _legacy_timeline(step)
        for entry in timeline or []:
            yield [
                test_id, model, wall_time, assets_created, path.name,
                prompt, final_message, *tokens,
                entry.get("seq"),
                entry.get("step"),
                _text(entry.get("segment_type")),
                _text(entry.get("kind")),
                _text(entry.get("operation")),
                _text(entry.get("name")),
                _text(entry.get("label")),
                _text(entry.get("preceding_tool")),
                entry.get("duration"),
                entry.get("start_offset_s"),
                entry.get("end_offset_s"),
                _text(entry.get("status")),
                _text(entry.get("error")),
            ]


def write_hyper(input_dir: Path, output: Path) -> int:
    """Build the .hyper extract from every JSON file in ``input_dir``.

    Returns the number of rows written (0 if there was nothing to read).
    """
    if not input_dir.is_dir():
        print(f"Staging directory not found: {input_dir}", file=sys.stderr)
        return 0

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        print(f"No JSON files found in {input_dir}", file=sys.stderr)
        return 0

    print(f"Building extract from {len(json_files)} JSON file(s) in {input_dir}")
    output.parent.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        with Connection(
            endpoint=hyper.endpoint,
            database=output,
            create_mode=CreateMode.CREATE_AND_REPLACE,
        ) as connection:
            connection.catalog.create_schema("Extract")
            connection.catalog.create_table(TABLE)

            with Inserter(connection, TABLE) as inserter:
                for path in json_files:
                    for row in flatten_file(path):
                        total_rows += 1
                        inserter.add_row([total_rows, *row])
                inserter.execute()

    print(f"Wrote {total_rows} row(s) to {output}")
    return total_rows


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=repo_root / "bench" / "tableau",
        help="Staging directory of JSON files to read (default: bench/tableau).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "bench" / "bench_results.hyper",
        help="Output .hyper file path (default: bench/bench_results.hyper).",
    )
    args = parser.parse_args()

    rows = write_hyper(args.input_dir, args.output)
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())

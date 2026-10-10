#!/usr/bin/env python3
"""Bulk-load Parquet files into a multi-table .hyper (one table per file).

Each table is created with CREATE TABLE ... AS SELECT * FROM external(parquet), so
Hyper reads the Parquet directly; nothing passes through Python rows.

Usage:
  python3 build_hyper.py OUT.hyper TABLE=FILE.parquet [TABLE=FILE.parquet ...]
      [--schema public] [--database-version N]

--database-version pins the Hyper file format (see Hyper API
`default_database_version`). Omit it to use the Hyper API's default.
Requires tableauhyperapi.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tableauhyperapi import (Connection, CreateMode, HyperProcess, Telemetry,
                             escape_name, escape_string_literal)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("tables", nargs="+", help="TABLE=FILE.parquet")
    ap.add_argument("--schema", default="public")
    ap.add_argument("--database-version")
    args = ap.parse_args()

    params = {"log_config": ""}
    if args.database_version:
        params["default_database_version"] = args.database_version
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters=params) as hp, \
         Connection(hp.endpoint, str(args.out), CreateMode.CREATE_AND_REPLACE) as conn:
        conn.execute_command(f"CREATE SCHEMA IF NOT EXISTS {escape_name(args.schema)}")
        for spec in args.tables:
            table, _, src = spec.partition("=")
            if not src:
                raise SystemExit(f"expected TABLE=FILE.parquet, got {spec!r}")
            target = f"{escape_name(args.schema)}.{escape_name(table)}"
            conn.execute_command(
                f"CREATE TABLE {target} AS (SELECT * FROM external("
                f"{escape_string_literal(str(Path(src).resolve()))}, FORMAT => 'parquet'))")
            rows = conn.execute_scalar_query(f"SELECT COUNT(*) FROM {target}")
            print(f"{args.schema}.{table}: {rows} rows")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()

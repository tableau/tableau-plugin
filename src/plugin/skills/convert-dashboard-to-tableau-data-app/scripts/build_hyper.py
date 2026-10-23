#!/usr/bin/env python3
"""
Bulk-load local files into a multi-table .hyper, one table per file.

Parquet is read by Hyper directly (CREATE TABLE ... AS SELECT * FROM external()),
so rows never pass through Python. CSV/TSV and JSON Lines are converted to
Parquet first with pyarrow, which infers column types; empty CSV cells are null.

Usage:
  python3 build_hyper.py OUT.hyper TABLE=FILE [TABLE=FILE ...]
      [--transform FILE.sql] [--schema public] [--database-version N]

--transform: Hyper SQL run after loading, for reshaping (e.g. split a flat file
  into a fact and a dimension, build a surrogate key, cast types). With it, files
  load into schema "staging", the SQL creates the final tables in --schema, and
  "staging" is dropped afterwards. Statements are separated by ";" at line end.
--database-version: pin the Hyper file format (Hyper API
  `default_database_version`) if an older Tableau Server can't open the default.

Prints one line per final table (schema.table: N rows) and the .hyper path.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from tableauhyperapi import (Connection, CreateMode, HyperProcess, Telemetry,
                             escape_name, escape_string_literal)

STAGING = "staging"
READERS = {".csv": ",", ".tsv": "\t", ".txt": ","}


def die(message: str) -> None:
    print(f"✗ {message}", file=sys.stderr)
    sys.exit(1)


def as_parquet(src: Path, scratch: Path) -> Path:
    ext = src.suffix.lower()
    if ext == ".parquet":
        return src
    import pyarrow.parquet as pq

    if ext in READERS:
        import pyarrow.csv as pacsv
        # Empty cells are nulls (pyarrow's default reads them as "" in text columns).
        table = pacsv.read_csv(src, parse_options=pacsv.ParseOptions(delimiter=READERS[ext]),
                               convert_options=pacsv.ConvertOptions(strings_can_be_null=True))
    elif ext in (".jsonl", ".ndjson"):
        import pyarrow.json as pajson
        table = pajson.read_json(src)
    else:
        die(f"{src.name}: unsupported file type {ext!r} (use .parquet, .csv, .tsv, .jsonl); "
            "export spreadsheets to CSV first")
    out = scratch / f"{src.stem}.parquet"
    pq.write_table(table, out)
    return out


def split_sql(text: str) -> list[str]:
    return [s.strip() for s in re.split(r";\s*$", text, flags=re.M) if s.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("tables", nargs="+", help="TABLE=FILE")
    ap.add_argument("--transform", type=Path)
    ap.add_argument("--schema", default="public")
    ap.add_argument("--database-version")
    args = ap.parse_args()

    specs = []
    for spec in args.tables:
        table, _, src = spec.partition("=")
        if not table or not src:
            die(f"expected TABLE=FILE, got {spec!r}")
        if not Path(src).is_file():
            die(f"{src}: file not found")
        specs.append((table, Path(src).resolve()))

    load_schema = STAGING if args.transform else args.schema
    params = {"log_config": ""}
    if args.database_version:
        params["default_database_version"] = args.database_version

    with tempfile.TemporaryDirectory() as scratch, \
         HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters=params) as hp, \
         Connection(hp.endpoint, str(args.out), CreateMode.CREATE_AND_REPLACE) as conn:
        for schema in {load_schema, args.schema}:
            conn.execute_command(f"CREATE SCHEMA IF NOT EXISTS {escape_name(schema)}")
        for table, src in specs:
            parquet = as_parquet(src, Path(scratch))
            conn.execute_command(
                f"CREATE TABLE {escape_name(load_schema)}.{escape_name(table)} AS "
                f"(SELECT * FROM external({escape_string_literal(str(parquet))}, FORMAT => 'parquet'))")

        if args.transform:
            for i, statement in enumerate(split_sql(args.transform.read_text(encoding="utf-8")), 1):
                try:
                    conn.execute_command(statement)
                except Exception as err:  # HyperException carries the SQL error text
                    die(f"{args.transform.name} statement {i} failed: {err}")
            conn.execute_command(f"DROP SCHEMA {escape_name(STAGING)} CASCADE")

        final = conn.catalog.get_table_names(args.schema)
        if not final:
            die(f"no tables in schema {args.schema!r}; the transform must create its tables there")
        for name in final:
            rows = conn.execute_scalar_query(f"SELECT COUNT(*) FROM {name}")
            print(f"{args.schema}.{name.name.unescaped}: {rows} rows")
    print(args.out.resolve())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Stream a warehouse query result to Parquet (Snowflake, Databricks, Trino).

Results are written batch by batch, so tables larger than memory are fine. Run
one query per table you want in the extract (e.g. one fact, one or more dims),
then load the files with build_hyper.py.

Credentials never go on the command line. Each engine uses its own standard
config or environment:
  snowflake   ~/.snowflake/connections.toml; --connection NAME (else the default
              connection). Browser SSO, key-pair, etc. come from that file.
  databricks  --host / --http-path (or DATABRICKS_SERVER_HOSTNAME / DATABRICKS_HTTP_PATH).
              DATABRICKS_TOKEN if set, else browser OAuth.
  trino       --host [--port 443] --user [--catalog --schema]. TRINO_PASSWORD
              (basic auth over https) if set, --oauth for browser OAuth, else none.

Usage:
  python3 export_query.py ENGINE (--sql-file Q.sql | --sql "SELECT ...") --out T.parquet [engine flags]

Types are normalized for Hyper: DECIMAL with scale 0 -> int64, other DECIMAL
wider than 18 digits -> double, TIME -> string. Binary and nested columns
(ARRAY/MAP/STRUCT/VARIANT) fail with a hint to cast or flatten in the SQL.

Prints JSON: {"out": path, "rows": N, "columns": [[name, arrow type], ...]}.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

BATCH_ROWS = 100_000


def die(message: str) -> None:
    print(f"✗ {message}", file=sys.stderr)
    sys.exit(1)


def normalize_type(name: str, t: pa.DataType) -> pa.DataType:
    if pa.types.is_decimal(t):
        if t.scale == 0:
            return pa.int64()
        return pa.float64() if t.precision > 18 else t
    if pa.types.is_time(t):
        return pa.string()
    if pa.types.is_large_string(t):
        return pa.string()
    if pa.types.is_dictionary(t):
        return normalize_type(name, t.value_type)
    if pa.types.is_binary(t) or pa.types.is_large_binary(t) or pa.types.is_nested(t):
        die(f"column {name!r} is {t}; cast it to a string or flatten it in the SQL")
    return t


def normalize_schema(schema: pa.Schema) -> pa.Schema:
    return pa.schema([pa.field(f.name, normalize_type(f.name, f.type)) for f in schema])


class Sink:
    def __init__(self, out: Path):
        self.out, self.writer, self.schema, self.rows = out, None, None, 0

    def write(self, table: pa.Table) -> None:
        if self.writer is None:
            names = table.column_names
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                die(f"duplicate column names {dupes}; alias them in the SQL")
            self.schema = normalize_schema(table.schema)
            self.writer = pq.ParquetWriter(self.out, self.schema)
        if table.num_rows:
            self.writer.write_table(table.cast(self.schema))
            self.rows += table.num_rows

    def close(self) -> dict:
        if self.writer is None:
            die("the query returned no columns")
        self.writer.close()
        return {"out": str(self.out.resolve()), "rows": self.rows,
                "columns": [[f.name, str(f.type)] for f in self.schema]}


# --- Trino: DB-API rows + type strings -> Arrow ------------------------------

TRINO_SIMPLE = {
    "boolean": pa.bool_(), "tinyint": pa.int16(), "smallint": pa.int16(), "integer": pa.int32(),
    "bigint": pa.int64(), "real": pa.float32(), "double": pa.float64(), "date": pa.date32(),
    "varchar": pa.string(), "char": pa.string(), "json": pa.string(), "uuid": pa.string(),
    "time": pa.string(), "ipaddress": pa.string(),
}


def trino_arrow_type(type_code: str) -> pa.DataType:
    t = type_code.lower().strip()
    base = re.match(r"[a-z ]+", t).group(0).strip()
    if base == "decimal":
        p, s = (int(x) for x in re.findall(r"\d+", t)[:2])
        return pa.decimal128(p, s)
    if base.startswith("timestamp"):
        return pa.timestamp("us", tz="UTC" if "with time zone" in t else None)
    if base.startswith("time"):
        return pa.string()
    if base in TRINO_SIMPLE:
        return TRINO_SIMPLE[base]
    if base in ("array", "map", "row", "varbinary"):
        return pa.binary()  # rejected by normalize_type with a cast/flatten hint
    return pa.string()


def trino_batches(cursor, size: int = BATCH_ROWS):
    schema = None
    while True:
        rows = cursor.fetchmany(size)
        if schema is None:
            if cursor.description is None:
                die("the query returned no result set")
            schema = pa.schema([(d[0], trino_arrow_type(d[1])) for d in cursor.description])
            for f in schema:
                normalize_type(f.name, f.type)  # fail fast on unsupported columns
        cols = list(zip(*rows)) if rows else [[] for _ in schema]
        yield pa.table([pa.array([str(v) if v is not None and f.type == pa.string()
                                  and not isinstance(v, str) else v for v in col], f.type)
                        for col, f in zip(cols, schema)], schema=schema)
        if len(rows) < size:
            return


# --- Engines -----------------------------------------------------------------

def run_snowflake(args, sql: str, sink: Sink) -> None:
    import snowflake.connector

    kwargs = {"connection_name": args.connection} if args.connection else {}
    with snowflake.connector.connect(**kwargs) as conn, conn.cursor() as cur:
        cur.execute(sql)
        wrote = False
        for table in cur.fetch_arrow_batches():
            sink.write(table)
            wrote = True
        if not wrote:  # empty result: still emit the schema
            sink.write(cur.fetch_arrow_all(force_return_table=True))


def run_databricks(args, sql: str, sink: Sink) -> None:
    from databricks import sql as dbsql

    host = args.host or os.environ.get("DATABRICKS_SERVER_HOSTNAME") or os.environ.get("DATABRICKS_HOST")
    http_path = args.http_path or os.environ.get("DATABRICKS_HTTP_PATH")
    if not host or not http_path:
        die("databricks needs --host and --http-path (or DATABRICKS_SERVER_HOSTNAME / DATABRICKS_HTTP_PATH)")
    host = re.sub(r"^https?://", "", host).rstrip("/")
    token = os.environ.get("DATABRICKS_TOKEN")
    auth = {"access_token": token} if token else {"auth_type": "databricks-oauth"}
    with dbsql.connect(server_hostname=host, http_path=http_path, **auth) as conn, \
         conn.cursor() as cur:
        cur.execute(sql)
        while True:
            table = cur.fetchmany_arrow(BATCH_ROWS)
            sink.write(table)
            if table.num_rows < BATCH_ROWS:
                return


def run_trino(args, sql: str, sink: Sink) -> None:
    import trino

    if not args.host or not args.user:
        die("trino needs --host and --user")
    password = os.environ.get("TRINO_PASSWORD")
    https = args.port == 443 or password or args.oauth
    auth = (trino.auth.BasicAuthentication(args.user, password) if password
            else trino.auth.OAuth2Authentication() if args.oauth else None)
    conn = trino.dbapi.connect(host=args.host, port=args.port, user=args.user,
                               catalog=args.catalog, schema=args.trino_schema,
                               http_scheme="https" if https else "http", auth=auth)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        for table in trino_batches(cur):
            sink.write(table)
    finally:
        conn.close()


ENGINES = {"snowflake": run_snowflake, "databricks": run_databricks, "trino": run_trino}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("engine", choices=sorted(ENGINES))
    q = ap.add_mutually_exclusive_group(required=True)
    q.add_argument("--sql-file", type=Path)
    q.add_argument("--sql")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--connection", help="snowflake: connections.toml entry")
    ap.add_argument("--host", help="databricks/trino host")
    ap.add_argument("--http-path", help="databricks SQL warehouse HTTP path")
    ap.add_argument("--port", type=int, default=443, help="trino port (default 443)")
    ap.add_argument("--user", help="trino user")
    ap.add_argument("--catalog", help="trino catalog")
    ap.add_argument("--schema", dest="trino_schema", help="trino schema")
    ap.add_argument("--oauth", action="store_true", help="trino: browser OAuth")
    args = ap.parse_args()

    sql = args.sql_file.read_text(encoding="utf-8") if args.sql_file else args.sql
    sql = sql.strip().rstrip(";")
    sink = Sink(args.out)
    try:
        ENGINES[args.engine](args, sql, sink)
    except ImportError as err:
        die(f"{err}; rerun through hyper_py.sh with --with {args.engine}")
    print(json.dumps(sink.close()))


if __name__ == "__main__":
    main()

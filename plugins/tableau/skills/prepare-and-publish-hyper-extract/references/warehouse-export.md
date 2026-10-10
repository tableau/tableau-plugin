# Warehouse export

`export_query.py` runs one SQL query and streams the result to a Parquet
file batch by batch (memory stays flat at any size). Run it once per table,
then load the files with `build_hyper.py`.

```bash
sh "$H/hyper_py.sh" --with <engine> export_query.py <engine> \
  --sql-file "$WORK/<table>.sql" --out "$WORK/<table>.parquet" [engine flags]
```

It prints `{"out", "rows", "columns"}`. Check the row count against what the
user expects and the column types before building.

## Credentials

Never put a password, token, or key on the command line, in the SQL file, or
in chat — and don't ask the user to paste one. Each engine reads its own
standard config or environment. If the connection fails for auth, tell the
user which of the settings below to configure, and let them do it.

### Snowflake (`--with snowflake`)

Reads `~/.snowflake/connections.toml` (or `$SNOWFLAKE_HOME/connections.toml`).
`--connection NAME` picks an entry; without it, the file's default
connection is used.

```toml
[analytics]
account = "myorg-myaccount"
user = "jane@example.com"
authenticator = "externalbrowser"   # SSO in the browser; or key-pair (private_key_file)
warehouse = "ANALYTICS_WH"
database = "SALES"
schema = "PUBLIC"
role = "ANALYST"
```

Results are fetched as Arrow batches directly — the fastest path.

### Databricks (`--with databricks`)

`--host` (workspace host, e.g. `adb-123.azuredatabricks.net`) and
`--http-path` (SQL warehouse → Connection details → HTTP path), or set
`DATABRICKS_SERVER_HOSTNAME` / `DATABRICKS_HTTP_PATH`. Auth: a personal
access token in `DATABRICKS_TOKEN` if the user has set one, otherwise
browser OAuth (U2M). Use three-part names in the SQL
(`catalog.schema.table`).

### Trino / Starburst (`--with trino`)

`--host` and `--user` are required; `--port` defaults to 443;
`--catalog` / `--schema` set defaults for unqualified names.
Auth: `TRINO_PASSWORD` in the environment → basic auth over HTTPS;
`--oauth` → browser OAuth; neither → no auth (plain HTTP unless port 443).

Trino returns rows, not Arrow, so the script builds Arrow from the declared
column types; it's slower than the other two for very large results.

## Writing the queries

- **One query per model table**, already at that table's grain: the fact
  (one row per event) and each dimension (one row per key —
  `SELECT DISTINCT` or `GROUP BY` the key if the source repeats it).
- **Push work to the warehouse**: filters, date ranges, joins that
  denormalize a snowflake schema into a dimension, derived columns. It's
  faster there than in the Hyper transform.
- **Name columns as you want them in Hyper** — `AS order_date`. Snake case
  gives good default captions. Every output column needs a unique name.
- **Keys**: same type on both sides of each relationship. Build composite
  keys into one column here (`md5(a || '::' || b)` / `sha2(...)`).
- **Size**: ask before pulling more than tens of millions of rows; offer a
  date range or an aggregate fact (e.g. daily instead of per event) when
  the app doesn't need row-level detail.

## Type handling

| Warehouse type | Parquet / Hyper |
|---|---|
| DECIMAL / NUMBER with scale 0 | int64 → BIG_INT |
| DECIMAL with scale > 0, precision ≤ 18 | decimal → NUMERIC |
| DECIMAL with precision > 18 | double |
| TIME | text |
| TIMESTAMP_TZ / WITH TIME ZONE | UTC timestamp with time zone |
| VARIANT, OBJECT, ARRAY, MAP, STRUCT, ROW, BINARY | **fails** — `CAST(... AS VARCHAR)`, `TO_JSON(...)`, or flatten in the SQL |

Snowflake `NUMBER(38,0)` IDs land as integers, so they relate cleanly to
integer keys in other tables.

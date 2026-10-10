---
name: prepare-and-publish-hyper-extract
description: Turn local files (CSV, TSV, Parquet, JSON Lines) or a warehouse query (Snowflake, Databricks, Trino) into a well-modeled multi-table Tableau extract — a .hyper with relationships, field captions, descriptions, and roles, packaged as a .tdsx — and publish it as a Tableau data source with the MCP publish-datasource tool, then hand its field list to the data-app build. Use when the user wants to build, model, or publish a data source / extract from raw data, prepare data for a data app, or relate a fact table to dimension tables without Tableau Desktop. Do not use to query or explore an already-published data source (use query-datasource directly), to edit a published data source's live connection, or to build the app itself — see tableau-data-app-authoring, which this skill hands off to.
---

# Prepare and Publish a Hyper Extract

Takes raw data to a published, well-modeled Tableau data source. No Tableau
Desktop needed. Walk the stages in order:

```
Sources → (Export*) → Build .hyper → Profile → Model → Generate .tdsx → Publish → Hand off
```

\* Only for warehouse sources. Local files go straight to Build.

The result is a one-time extract. There's no refresh schedule; to update it,
rebuild and republish with `overwrite: true` (the data source keeps its LUID,
so wired apps keep working).

**What makes it "well-modeled"** — the reason this skill exists, not just a
file upload:
- **Relationships, not one flat table.** A fact (one row per event: orders,
  visits) related to dimensions (one row per entity: customers, products).
  Measures stay at their own grain, so a dim-level number (customer
  headcount) isn't multiplied by the fact rows.
- **Captions people read** (`Order Date`, not `order_date`) and a
  **description on every field** that isn't self-explanatory. Descriptions
  surface in Tableau, Pulse, and to agents querying the data source.
- **Correct roles.** IDs are dimensions; amounts are measures.

## Setup

Every script runs through `hyper_py.sh`, which keeps a private Python
environment with the Hyper API in the plugin data directory:

```bash
H="$PLUGIN_ROOT/skills/prepare-and-publish-hyper-extract/scripts"
sh "$H/hyper_py.sh" build_hyper.py --help
```

The first run installs `tableauhyperapi` (~90 MB download, ~300 MB on disk)
and `pyarrow` — tell the user that's what's happening, it takes a minute.
Later runs start immediately. Supported: macOS, Linux x86_64, Windows x86_64.
On Linux or Windows **arm64** there is no Hyper API build; the script says so
— tell the user to run on an x86_64 machine or container.

Work in a scratch directory (`WORK="$(mktemp -d -t hyperx)"`), not inside the
user's source folders, and keep every intermediate there.

## 1. Sources

Ask what the data is and where it lives if the user hasn't said. Then decide
the **tables**: which file or query is the fact, which are dimensions, and the
key that joins each dimension to the fact. Keep to what the app or analysis
needs — extra columns cost nothing to the user but extra tables need
relationships.

Data that arrives as **one flat file** (each row repeats the customer's
region, name, ...) should usually be split into a fact and dimensions in the
Build step with `--transform`. Leave it flat if it has no repeating entity
attributes.

## 2. Export (warehouse only)

One query per table, each streamed to Parquet. See
[warehouse-export.md](references/warehouse-export.md) for per-engine
connection setup and SQL guidance. In short:

```bash
sh "$H/hyper_py.sh" --with snowflake export_query.py snowflake \
  --sql-file "$WORK/fact_orders.sql" --out "$WORK/fact_orders.parquet" [--connection NAME]
```

`--with databricks` / `--with trino` work the same way. **Credentials never
go on the command line or in chat** — each engine reads its own config file,
environment variable, or browser SSO. If a connection fails for auth, tell
the user which config to set (see the reference) and let them set it.

Do joins, filtering, and type casts in the warehouse SQL — it's the fastest
place, and it keeps unsupported types (VARIANT, ARRAY, binary) out of the
extract.

## 3. Build the .hyper

```bash
sh "$H/hyper_py.sh" build_hyper.py "$WORK/orders.hyper" \
  fact_orders="$WORK/fact_orders.parquet" dim_customer="$WORK/dim_customer.parquet"
```

Each `TABLE=FILE` becomes one table. Parquet loads directly in Hyper; CSV,
TSV, and JSON Lines are type-inferred by pyarrow first (empty CSV cells are
null). Spreadsheets: ask the user to export each sheet to CSV.

To reshape — split a flat file, build a single key from a composite one,
fix a type — pass `--transform split.sql`. Files then load into schema
`staging`; the SQL creates the final tables in `public`:

```sql
CREATE TABLE public.orders AS
  SELECT order_id, customer, order_date, amount FROM staging.sales;
CREATE TABLE public.customers AS
  SELECT DISTINCT customer, region, segment FROM staging.sales WHERE customer IS NOT NULL;
```

The script prints each final table's row count. Check them against what the
user expects before going on.

## 4. Profile

```bash
sh "$H/hyper_py.sh" profile_hyper.py "$WORK/orders.hyper" --model-out "$WORK/model.json" \
  --check fact_orders.customer_id=dim_customer.customer_id
```

Stdout is JSON: per column the type, nulls, distinct count, min/max, and top
values for low-cardinality text. Read it instead of pulling rows. It also
proposes `relationshipCandidates` (same-named, same-typed columns where one
side is unique) and `--check` validates a key you name:

- `toUnique: false` — the dimension key repeats. Fix it in the Build step
  (dedupe, or pick the right grain) — a many-to-many relationship is almost
  never what the user meant.
- `fromOrphans` / `fromNullKeys` — fact rows with no dimension match. They
  still count in fact measures but show under a null dimension value. Report
  the share to the user; it's often a real data-quality finding.

`--model-out` writes a starting model with every table, column, default
caption, and the candidate relationships (when they connect every table).

## 5. Model

Edit `model.json` — see [model-json.md](references/model-json.md) for the
full format and guidance. The parts that matter most:

- **Data source `caption` and `description`** — what it is, its grain, and
  its source/date.
- **Table order**: the fact first. Where a column name repeats across tables
  (the join key), the first table keeps the bare name.
- **Captions**: every caption must be unique. Give repeated key columns
  distinct ones (`Customer ID` on the dimension, `Customer ID (Orders)` on
  the fact — or `hidden: true` on the fact's copy).
- **Descriptions**: one sentence per field that isn't obvious — units,
  allowed values, what null means, the grain. Use the profile (values,
  ranges) to write them; don't invent business meaning — ask the user when
  a field's meaning isn't clear from its name and values.
- **Roles**: numbers default to measures except key-named ones (`id`,
  `*_id`); set `role` where that's wrong (a numeric code, a year).
- **Relationships**: exactly one per dimension, `from` the many side (fact)
  `to` the one side. Single-column keys only.

## 6. Generate the .tdsx

```bash
sh "$H/hyper_py.sh" generate_tds.py "$WORK/orders.hyper" "$WORK/model.json" \
  --out "$WORK/<Data Source Name>.tdsx" --fields-out "$WORK/fields.json"
```

It validates the model against the hyper and hard-fails with a `✗` message
on a missing table or column, a duplicate caption, mismatched key types, a
composite key, or tables that don't form one connected tree. Fix the model
(or the Build step) and rerun — don't hand-edit the generated XML.

`fields.json` is the published field list (`name` = caption, `datatype`,
`role`, `description`) — the hand-off to the data app.

## 7. Publish

Publishing creates content on the user's site: **confirm the name and
project with the user first** (`list-projects` for the project LUID; data
sources can't go to Personal Space).

> publish-datasource({ datasourceFilePath: "<abs path to .tdsx>", name: "<name>", projectId: "<LUID>", description: "<model description>" })

For hosted servers that reject `datasourceFilePath`, stage it:

> request-datasource-upload({ fileName: "<name>.tdsx" }) → { datasourceUploadId, uploadUrl, requiredHeaders }

```bash
curl -fsS -X PUT -H 'Content-Type: <from requiredHeaders>' --data-binary @"$WORK/<name>.tdsx" "<uploadUrl>"
```

> publish-datasource({ datasourceUploadId: "<id>", name: "<name>", projectId: "<LUID>" })

- **Name already exists**: the tool fails before uploading. Republishing the
  same data source (a rebuild) → ask, then `overwrite: true`. Otherwise pick
  another name.
- **`status: "pending"`**: a large extract is still processing; poll the job
  and look the data source up by name + project when it finishes.
- **`boundedContextNote`**: relay it verbatim — the MCP operator must allow
  the new LUID before the app can query it.

If `publish-datasource` isn't available on this MCP server, say so and stop
at the `.tdsx` path: the user can publish it from Tableau (Desktop's Publish
Data Source, or Server's web upload). Don't publish with your own REST calls
or ask for a token.

Report the data source name, `webpageUrl`, and LUID.

## 8. Hand off

Verify the published model with one `query-datasource` call that crosses the
relationship (a dimension field plus a fact measure) and check it against a
number you know from the profile.

For a data app, continue in **tableau-data-app-authoring** at "Wire a
datasource in", building the descriptor from the publish result and
`fields.json` — **don't wait for `get-datasource-metadata`**: Tableau Catalog
can take minutes to index a new data source, and its descriptions lag an
overwrite.

- `caption`: the published name; `repositoryId`: `datasource.contentUrl`;
  `server` / `site`: the publish result's host and `siteContentUrl`.
- `fields`: the entries of `fields.json` the app will query, with only
  `name`, `datatype`, `role`.

## Non-negotiable limits

- Don't write .tds XML by hand or patch the generated file — fix the model
  and rerun `generate_tds.py`.
- Don't put credentials (warehouse passwords, tokens, PATs) on a command
  line, in a file in the work dir, or in chat.
- Don't publish without the user's go-ahead on the name and project, and
  don't overwrite without asking.
- Don't use the TDS Edit API to build relationships; it can't. It can only
  edit captions/descriptions/roles of an already-published data source —
  see [tds-edit-api.md](references/tds-edit-api.md).

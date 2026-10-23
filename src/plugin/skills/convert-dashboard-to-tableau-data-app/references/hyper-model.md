# model.json

The input to `generate_tds.py`: which tables of the .hyper go into the data
source, how they relate, and what each field is called and means. Start from
the skeleton `profile_hyper.py --model-out` writes, then edit it.

```json
{
  "caption": "Orders",
  "description": "One row per order (2023-2025) with the ordering customer. Built from the sales warehouse on 2026-10-09.",
  "tables": [
    {
      "schema": "public",
      "name": "fact_orders",
      "caption": "Orders",
      "columns": {
        "order_id":    { "caption": "Order ID", "description": "Unique order ID; one row per order." },
        "customer_id": { "caption": "Customer ID (Orders)", "hidden": true },
        "amount":      { "caption": "Net Amount", "description": "Order total in USD after discounts." },
        "status_code": { "caption": "Status Code", "role": "dimension" }
      }
    },
    {
      "schema": "public",
      "name": "dim_customer",
      "caption": "Customers",
      "columns": {
        "customer_id": { "caption": "Customer ID", "description": "Unique customer ID." },
        "country":     { "caption": "Country", "semanticRole": "[Country].[ISO3166_2]" }
      }
    }
  ],
  "relationships": [
    { "from": { "table": "fact_orders", "column": "customer_id" },
      "to":   { "table": "dim_customer", "column": "customer_id" } }
  ]
}
```

## Keys

| Key | Required | Meaning |
|---|---|---|
| `caption` | no | Data source caption (default `Extract`). Use the published name. |
| `description` | no | Pass it as the `publish-datasource` description. Not written into the .tds. |
| `tables[].schema` | no | Hyper schema, default `public`. |
| `tables[].name` | yes | Hyper table name. Each table once. |
| `tables[].caption` | no | Logical table caption shown in Tableau (default: Title Case of the name). |
| `tables[].columns` | no | Per-column overrides, keyed by Hyper column name. Columns not listed are still included, with defaults. |
| `columns.*.caption` | no | Field name in Tableau and in every query (VDS `fieldCaption`, data-app `name`). Unique across the whole data source, case-insensitive. |
| `columns.*.description` | no | Plain text; shown in Tableau's field tooltip, Catalog, and to agents. |
| `columns.*.role` | no | `dimension` or `measure`. |
| `columns.*.semanticRole` | no | Tableau geographic role, e.g. `[Country].[ISO3166_2]`, `[State].[Name]`, `[City].[Name]`, `[ZipCode].[Name]`. |
| `columns.*.hidden` | no | `true` hides the field (e.g. the fact's copy of a join key). Hidden fields are left out of `fields.json`. |
| `relationships[]` | yes, n−1 | `from` the many side (fact) `to` the one side (dimension). |

## Defaults

- **Caption**: `snake_case` / `camelCase` → Title Case, with `id`, `url`,
  `luid` upper-cased (`customer_id` → `Customer ID`). When a column name
  repeats across tables, the later table's default caption gets
  `(<Table caption>)` appended.
- **Role**: integer and real columns are measures, except key-named ones
  (`id`, `*_id`, `*Id`); everything else is a dimension.
- **Default aggregation**: Sum for numbers, Count for text and booleans, Year
  for dates.

## Modeling guidance

**Grain first.** Write down the grain of every table ("one row per order",
"one row per customer"). The one side of each relationship must be unique
at its key — `profile_hyper.py --check` tells you. If a "dimension" repeats
its key, it's really at a finer grain: dedupe it in the Build transform, or
relate on the column that is unique.

**Shape: a star.** One fact in the middle, dimensions around it, each
related directly to the fact. A dimension of a dimension (product →
category) is fine too: relate it to its parent. The model must be a single
tree — no table related twice, no loops. Two facts at different grains
(orders and shipments) can both be in one model only through a shared
dimension; if that's not natural, publish two data sources.

**Keys.** One column on each side, same type. For a composite key, build a
single key column in both tables in the Build transform:

```sql
CREATE TABLE public.fact AS
  SELECT *, md5(CAST(store_id AS TEXT) || '::' || CAST(sku AS TEXT)) AS store_sku_key FROM staging.fact;
```

Type mismatch (an integer ID on one side, text on the other): cast one in
the transform.

**Table order.** List the fact first. Desktop's naming rule — the first
table keeps a repeated column's bare internal name — then puts the bare
names on the fact. Captions are what users see, so this only matters for
the internal names; but keep it consistent.

**Repeated join keys.** Both copies appear as fields. Usually: keep the
dimension's as `Customer ID`, and hide the fact's (`hidden: true`) or
caption it `Customer ID (Orders)`. Counting customers then reads naturally
as `COUNTD([Customer ID])`.

**Measures at the dimension grain** (customer headcount, product list
price) belong in the dimension table. Relationships aggregate them at their
own grain, so they don't inflate by the number of orders — that's the main
reason to relate tables instead of flattening.

**Descriptions.** Say what a reader can't infer: unit and currency, the set
of allowed values, what null means, how a number was derived, the time
zone of a timestamp. Use the profile's values and ranges as evidence. If a
column's meaning isn't clear from its name and values, ask the user rather
than guessing — a confident wrong description is worse than none.

**Unsupported types** fail generation: cast them in the Build transform or
warehouse SQL (intervals and geography to text, `TIME` already arrives as
text from `export_query.py`).

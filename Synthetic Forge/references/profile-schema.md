# Synthetic Forge profile schema

Read this reference when creating, reviewing, or repairing a generation profile.

## Root object

```json
{
  "version": "1.0",
  "tables": [],
  "relationships": [],
  "privacy": {
    "forbidden_values_sha256": []
  }
}
```

- `version` must be `"1.0"`.
- `tables` must contain at least one table.
- `relationships` is optional. The generator topologically orders parent tables before children and rejects cycles.
- `privacy.forbidden_values_sha256` may contain lowercase SHA-256 hashes of source values that must never appear in output.
- Keys named `source_values`, `raw_values`, or `sample_values` are rejected anywhere in the document.

## Tables and fields

```json
{
  "name": "customers",
  "rows": 1000,
  "fields": [
    {
      "name": "customer_id",
      "type": "id",
      "unique": true,
      "generator": {"kind": "sequence", "prefix": "CUS-", "start": 1, "width": 6}
    },
    {
      "name": "segment",
      "type": "string",
      "generator": {
        "kind": "categorical",
        "values": [
          {"value": "Consumer", "weight": 0.65},
          {"value": "Business", "weight": 0.35}
        ]
      }
    }
  ]
}
```

Table names and field names must be non-empty and unique within their scope. `rows` must be a positive integer. Supported types are:

- `string`
- `integer`
- `float`
- `boolean`
- `date`
- `datetime`
- `id`

Common field options:

- `nullable_rate`: number from `0` through `1`; the generator creates exactly `round(rows × nullable_rate)` nulls.
- `unique`: require non-null values to be unique. Use `sequence`, `uuid`, `synthetic_name`, or `synthetic_email`; random generators are rejected when more than one non-null value is requested.
- `decimals`: decimal places for numeric output; defaults to `0` for integers and `2` for floats.
- `validation.mean_tolerance`: optional fractional tolerance for a generator with a declared `mean`.

## Generators

| Kind | Compatible types | Required or useful parameters |
| --- | --- | --- |
| `sequence` | id, string, integer | `start`, `prefix`, `width` |
| `uuid` | id, string | none |
| `categorical` | any scalar type | non-empty `values`; entries may be scalars or `{value, weight}` |
| `integer_uniform` | integer | integer `min`, `max` |
| `uniform` | float, integer | numeric `min`, `max` |
| `normal` | float, integer | numeric `mean`, positive `stddev`; optional `min`, `max` |
| `lognormal` | float | positive arithmetic `mean`, positive `sigma`; optional `min`, `max` |
| `boolean` | boolean | `probability_true` from 0 through 1 |
| `date_range` | date | ISO dates `start`, `end` |
| `datetime_range` | datetime | ISO datetimes `start`, `end` |
| `synthetic_name` | string | optional `prefix`; produces tokens such as `Person-000123` |
| `synthetic_email` | string | optional `domain`; defaults to reserved `example.invalid` |
| `constant` | any | `value` |

When `generator` is omitted, Synthetic Forge chooses a privacy-safe type default. Defaults are intentionally generic, not statistically calibrated.

CSV uses `\N` for null and escapes string values beginning with a backslash, so an empty string remains distinct from null. SQLite uses `INTEGER`, `REAL`, or `TEXT` affinity based on the declared field type.

## Relationships

```json
{
  "parent_table": "customers",
  "parent_field": "customer_id",
  "child_table": "orders",
  "child_field": "customer_id"
}
```

The parent field must guarantee unique, non-null keys. Parent and child types must match, except that `id` and `string` are interoperable. A child field governed by a relationship is sampled from generated parent keys; its ordinary generator is ignored. `nullable_rate` may still introduce optional foreign keys. Relationship-generated child fields cannot guarantee uniqueness when more than one non-null child row is requested.

## Example multi-table profile

```json
{
  "version": "1.0",
  "tables": [
    {
      "name": "customers",
      "rows": 100,
      "fields": [
        {"name": "customer_id", "type": "id", "unique": true,
         "generator": {"kind": "sequence", "prefix": "CUS-", "width": 5}},
        {"name": "email", "type": "string", "unique": true,
         "generator": {"kind": "synthetic_email"}}
      ]
    },
    {
      "name": "orders",
      "rows": 500,
      "fields": [
        {"name": "order_id", "type": "id", "unique": true,
         "generator": {"kind": "sequence", "prefix": "ORD-", "width": 6}},
        {"name": "customer_id", "type": "id"},
        {"name": "amount", "type": "float", "decimals": 2,
         "generator": {"kind": "lognormal", "mean": 85, "sigma": 0.8, "min": 1, "max": 1000},
         "validation": {"mean_tolerance": 0.2}},
        {"name": "ordered_on", "type": "date",
         "generator": {"kind": "date_range", "start": "2025-01-01", "end": "2025-12-31"}}
      ]
    }
  ],
  "relationships": [
    {"parent_table": "customers", "parent_field": "customer_id",
     "child_table": "orders", "child_field": "customer_id"}
  ],
  "privacy": {"forbidden_values_sha256": []}
}
```

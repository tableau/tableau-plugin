# Datasource dictionary

## Scope

- **Measures and calculations:** concise default for metric-focused requests.
- **Selected fields:** best when the user names a business process or subset.
- **All accessible fields:** group by table/category and report complete coverage or explicit truncation.

## Per-field record

Include applicable properties:

| Property | Guidance |
| --- | --- |
| Display name | returned Tableau caption/name |
| Business definition | confirmed description or `confirm with data owner` |
| Technical meaning | type, role, aggregation, table, and formula classification |
| Grain/unit | only when known |
| Directionality | favorable direction only with business evidence |
| Inputs | referenced fields for a calculation |
| Usage | visible/metadata-supported role, not guessed popularity |
| Caveats | null, filter, LOD, table-calc, currency, denominator, or privacy issue |
| Evidence status | observed, inferred, or unknown |

Never define a field by restating its name. Explain formulas in plain language without losing meaningful conditions, aggregation, fixed grain, addressing/partitioning, or null/zero behavior. Do not claim a table calculation's result without knowing the view context.

## Sample/value enrichment

Only after explicit authorization, use a bounded query to obtain the specific range, example categories, date span, or magnitude needed. Record filters, aggregation, row limit, and timestamp. Avoid sensitive/free-text/identifier samples. A sample is not a full distribution and does not establish typicality without an appropriate method.

## Large schemas

Group related variants as metric families. Give fuller definitions to decision-critical measures and calculations, and concise records to secondary fields. Do not invent priorities; use visible usage, user intent, descriptions, or calculation dependencies as evidence.


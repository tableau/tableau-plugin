# Ranking input contract

The ranker reads one JSON object. It never queries Tableau itself.

## Minimal example

```json
{
  "query": {
    "terms": ["sales", "region"],
    "synonyms": ["revenue", "bookings", "territory"],
    "implied_terms": ["sales amount", "geography"],
    "temporal": true
  },
  "as_of": "2026-09-03",
  "max_per_tier": 3,
  "candidates": [
    {
      "id": "canonical-view-id",
      "type": "view",
      "name": "Regional Sales Trends",
      "description": "Monthly revenue by territory",
      "project": "Commercial Analytics",
      "workbook": "Sales Performance",
      "owner": "Analytics Team",
      "tags": ["sales", "monthly"],
      "fields": ["Region", "Sales Amount", "Order Date"],
      "has_date_field": true,
      "usage_count": 420,
      "updated_at": "2026-08-15T12:00:00Z",
      "certified": false,
      "url": "https://server-returned.example/view"
    }
  ]
}
```

## Query fields

| Field | Required | Meaning |
| --- | --- | --- |
| `terms` | Yes | Non-empty list of primary query concepts |
| `synonyms` | No | Conservative related terms; weaker than primary matches |
| `implied_terms` | No | Expected measures or dimensions inferred from the question |
| `temporal` | No | Whether a date/time capability is relevant |

## Candidate fields

`id`, `type`, and `name` are required strings. Other strings, lists, booleans, counts, and timestamps are optional. `fields` may contain strings or objects with a string `name`. `url` must come from Tableau; the ranker only passes it through.

Supported `type` values are `view`, `workbook`, `datasource`, `project`, and `pulse_metric`.

Use the same canonical candidate once. Merge evidence before ranking rather than submitting duplicate IDs.

## Scoring signals

| Signal | Points |
| --- | ---: |
| Primary term at a name word boundary | +30 |
| Primary term as name substring only | +15 |
| Synonym at a name word boundary | +15 |
| Primary field match | +25 |
| Implied or synonym field match when no primary field matched | +15 |
| Description match | +20 |
| Tag match | +10 |
| Pulse definition concept match | +20 |
| Date capability for a temporal query | +10 |
| Top-quartile usage among at least four comparable views in the same project | +5 |
| Updated within 90 days of `as_of` | +5 |

Name evidence contributes only its strongest signal. Field evidence contributes exact or implied—not both. Scores cap at 100.

Confidence tiers: High 60–100, Medium 35–59, Low 15–34. Results below 15 are omitted.

## Determinism

Pass `as_of` as `YYYY-MM-DD` when recency matters. If omitted, the ranker emits a warning and gives no recency points. Tie order is score, usage, update timestamp, certification, then case-folded name.

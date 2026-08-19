---
name: tableau-pulse-insights
description: Use when building Tableau Pulse Insights bar or line visualizations in a .twb workbook, including ARR trends, ranked products, date ranges, and field mapping.
---

# Tableau Pulse Insights

## Overview

Pulse Insights is the `pulse-insights` catalog family: two executable
bookmark templates for the bar and line shapes Pulse surfaces most often —
a ranked-product bar chart and an ARR-over-time trend line.

## Workflow

Start discovery scoped to the family (the CLI path below is relative to
this skill's own directory, `skills/tableau-pulse-insights/`):

```bash
python3 ../../scripts/tableau_resources.py list \
  --family pulse-insights \
  --tier executable
```

This returns exactly `insights__bar_chart` (rank products by a measure
within a date range) and `insights__line_chart` (a measure trending over a
date field). Pick the one matching the ask, `inspect` it, then follow
`tableau-workbook-authoring` for the field-mapping, parameter, transform
(`instantiate`/`inject`), and validate/publish steps — that skill and the
shared CLI own those rules; this skill does not repeat them.

## Common mistakes

- Searching without `--family pulse-insights` and picking an unrelated bar
  or line template from another family.
- Re-deriving mapping or validation rules here instead of following
  `tableau-workbook-authoring`.

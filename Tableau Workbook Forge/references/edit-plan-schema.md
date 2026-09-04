# Declarative edit plan

Use an edit plan to make supported changes auditable, repeatable, and atomic. Always run it against a working copy. Preview with `--dry-run` before applying it.

## Version 1.0

```json
{
  "version": "1.0",
  "operations": [
    {
      "op": "replace_run_style",
      "worksheet": "Sales Overview",
      "match": {"fontcolor": "#000000"},
      "set": {"fontcolor": "#17365D", "fontname": "Tableau Book"},
      "expected": 3
    },
    {
      "op": "rename_worksheet",
      "from": "Sheet 1",
      "to": "Sales Overview"
    },
    {
      "op": "set_zone_geometry",
      "dashboard": "Executive Overview",
      "zone_id": "12",
      "set": {"x": 20, "y": 80, "w": 600, "h": 320}
    }
  ]
}
```

Operations run in listed order. Any error stops the plan before the original working file is replaced.

## `replace_run_style`

- `worksheet` is optional. When present, exactly one worksheet with that name must exist.
- `match` must be a non-empty exact attribute map.
- `set` must be a non-empty attribute map.
- Supported attributes are `fontcolor`, `fontname`, `fontsize`, `bold`, `italic`, and `underline`.
- `expected` is optional but recommended. The operation fails if the actual match count differs.
- A zero-match operation always fails.

Inventory current styles before creating a broad replacement. Do not treat text, borders, fills, and marks as interchangeable color targets.

## `rename_worksheet`

- `from` and `to` must be non-empty and distinct in the workbook.
- Exactly one source worksheet must exist and the target must not already exist.
- Known dashboard worksheet-zone and worksheet-window references are updated.
- Any other exact reference to the old name blocks the operation. Use a compatible donor or a manually reviewed XML-aware edit for those structures.

## `replace_run_text`

- `worksheet` is optional and scopes the operation when present.
- `from` and `to` are exact text values on existing `<run>` elements.
- `expected` is optional but recommended; zero matches always fails.
- Use this for observed run-based titles, captions, or labels. Do not use it to synthesize absent XML structures.

## `set_zone_geometry`

- `dashboard` and `zone_id` must resolve to exactly one existing zone.
- `set` accepts any subset of `x`, `y`, `w`, and `h` as integers.
- Coordinates may be zero or greater; width and height must be positive when supplied.
- Inspect the dashboard first and preserve its existing geometry convention. This operation does not create zones or convert tiled/floating layout models.

## Evidence and postconditions

Save the dry-run result, applied change log, validation JSON, and exact diff. A successful local plan proves only that the supported transformations and local invariants passed; it does not prove Tableau render compatibility.

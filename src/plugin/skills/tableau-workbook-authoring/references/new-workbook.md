# New workbook route

Read this reference only when the user wants a workbook with no existing
workbook as a starting point, and the chart catalog has no matching
`tier: executable` resource (see [`catalog-templates.md`](catalog-templates.md);
check `list` before assuming no match).

## Resolve required inputs

Resolve these before authoring:

- **Published datasource:** search/list datasources and inspect its metadata.
  Never invent field names, roles, types, or captions.
- **Requested views:** establish the chart types, fields, filters, layout, and
  dashboards. Ask only about ambiguities that materially change the result.
- **Destination project:** resolve its project LUID. Run independent datasource
  and project lookups in parallel when supported.

## Author the TWB

Build a datasource block that references the real published datasource, a
worksheet per requested chart, and the requested dashboard zones. Keep all
names unique and all datasource, worksheet, and zone references consistent.

Use an existing nearby Tableau XML pattern when available. For a genuinely new
construct, consult the newest compatible schema under `resources/schemas/`; do not load
the entire XSD when a targeted element lookup is enough.

Return to `SKILL.md` for local validation, direct publish, and rendering.

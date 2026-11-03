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

Before the first publish, check the publish-only rules in `SKILL.md`
("Hand-written XML: rules publish enforces that the XSD doesn't"). Dashboard
window viewpoints are the most common miss.

### Reference the published datasource

Point the workbook at the published datasource through a `sqlproxy`
connection. Use the datasource's **`contentUrl`** (from
`list-datasources`/`search-content`) as both `repository-location id` and
`dbname`. Don't use its LUID, its caption, or the literal `sqlproxy`:

```xml
<datasource caption='Sample - Superstore' inline='true' name='sqlproxy.superstore' version='18.1'>
  <repository-location id='Sample-Superstore_17827687606970' path='/datasources' revision='1.0' />
  <connection class='sqlproxy' channel='https' dbname='Sample-Superstore_17827687606970' port='443' />
  <!-- <column> metadata for the fields you use -->
</datasource>
```

The `name` (here `sqlproxy.superstore`) is internal: any unique value works,
as long as every worksheet's `<datasource>` and `<datasource-dependencies>` use
it. Wrong values fail at publish:

- **Wrong `dbname`/`id`:** "Datasource '…' not found for workbook".
- **`federated` connection with no `<named-connections>`:** "federated
  connection is missing required named-connections element".

Use an existing nearby Tableau XML pattern when available. For a genuinely new
construct, check `resources/schemas/`, but pick the schema by the workbook's
build, not its `version` attribute (Tableau leaves that at `18.1`):
`validate_workbook.py` reports the schema it chose from `source-build`, and a
workbook built from the starter uses `2026_2`.
Don't use a schema newer than the target server's Tableau version, and look up
only the element you need rather than loading the entire XSD.

Return to `SKILL.md` for local validation, direct publish, and rendering.

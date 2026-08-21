# Tableau Plugin

Teaches Codex to explore existing Tableau content, analyze data, build and
modify Tableau `.twb` workbooks — either from a curated resource catalog or
by hand-editing TWB XML — validate workbook packages, and use the hosted
Tableau MCP server.

## Skills

- `tableau-analytics` — read-oriented querying/exploring of existing
  workbooks, data sources, views, and Pulse metrics.
- `tableau-content-viewer` — find a view/workbook by name and render it in
  the Codex side panel, no data querying or editing.
- `tableau-workbook-templating` — build, edit, and validate `.twb` workbooks
  using the bundled resource catalog and CLI; prefer this when the desired
  chart is covered by the catalog.
- `tableau-workbook-authoring` — build or modify `.twb` workbooks by
  hand-editing the raw XML and publishing it back; use this when the
  resource catalog doesn't cover what's needed.
- `tableau-pulse-insights` — build Pulse Insights bar/line visualizations
  (ARR trends, ranked products) using the `pulse-insights` catalog family.
- `validate-workbook-package` — the pre-publish validation gate.

## Resource catalog and CLI

`resources/catalog.json` indexes every chart template, worked example, and
reference document under `resources/`. Each entry declares a `tier`:

- `executable` — a bookmark template that `instantiate`/`inject` can
  render into a real worksheet and window, with a typed field-mapping and
  parameter contract.
- `reference` — a worked example, corpus entry, or schema document to
  study, never to render directly.

The CLI, `scripts/tableau_resources.py`, is the only supported way to
discover and transform these resources:

```bash
python3 scripts/tableau_resources.py list --tier executable
python3 scripts/tableau_resources.py inspect <resource-id>
python3 scripts/tableau_resources.py instantiate <resource-id> \
  --datasource-definition <file> --output <file> --worksheet-name <name> \
  --map SOURCE=TARGET --param NAME=VALUE
python3 scripts/tableau_resources.py inject <resource-id> \
  --input <existing.twb> --output <file> --datasource <name> \
  --worksheet-name <name> --map SOURCE=TARGET --param NAME=VALUE
python3 scripts/tableau_resources.py validate --input <file>
```

## Catalog-driven authoring flow (`tableau-workbook-templating`)

1. **Download-or-starter** — inspect an existing workbook's datasources, or
   prepare a `<datasource>` definition for a new one built from
   `resources/starters/minimal-workbook.twb`.
2. **Transform** — `list` and `inspect` a catalog resource, then
   `instantiate` (new workbook) or `inject` (existing workbook) it with the
   required field mappings and parameters.
3. **Validate** — run the CLI's `validate` locally, then run
   `validate-workbook-package` as the pre-publish gate.
4. **Publish** — call `create-and-publish-workbook` with the validation
   receipt `validate-workbook-package` returned.

See `skills/tableau-workbook-templating/references/resource-guide.md` for
full CLI flags, mapping syntax, and failure recovery.

If the requested chart isn't covered by the catalog (`list --tier
executable` turns up nothing suitable), fall back to `tableau-workbook-authoring`,
which builds/edits the `.twb` XML by hand via `download-workbook` /
`request-workbook-upload` / `validate-upload-and-publish-workbook` instead.

---
name: tableau-workbook-authoring
description: Create, edit, copy, or republish a Tableau workbook by editing TWB XML and publishing it through Tableau MCP. Use for create, build, edit, modify, copy, republish, or add-chart requests. Do not use for read-only analysis or for just opening/showing an existing view (tableau-content-viewer).
---

# Purpose

Build or edit a Tableau workbook — from the bundled chart catalog when the request matches it, otherwise by hand-editing TWB XML — validate, publish through Tableau MCP, and render the result.

## Canonical Tableau MCP tools

Call these tool IDs directly when they are available. Do not scan or print the
full tool catalog merely to rediscover their names or schemas.

- Workbook search:
  `mcp__tableau__search_content`
  with `{ terms, filter: { contentTypes: ["workbook"] }, limit }`
- Exact project lookup:
  `mcp__tableau__list_projects`
  with `{ filter: "name:eq:<project-name>", limit }`
- Workbook download:
  `mcp__tableau__download_workbook`
  with `{ workbookId, includeExtract: true }`
- Workbook publish:
  `mcp__tableau__publish_workbook`
  with `{ name, projectId, workbookFilePath, overwrite }`
- Staged-upload fallback:
  `mcp__tableau__request_workbook_upload`
- Workbook metadata:
  `mcp__tableau__get_workbook`
- View metadata:
  `mcp__tableau__get_view`
- Static view render:
  `mcp__tableau__get_view_image`
  with `{ viewId, format: "PNG", width, height }`

If a directly named tool is not callable, perform one focused availability
lookup for that tool only. Do not enumerate the entire Tableau or global tool
catalog.

# Routing

- Follow-up edit on a workbook already resolved this task → the fast path below.
- Building or adding a chart:
  1. First run:
     `python3 scripts/tableau_resources.py list --tier executable --query "<intent>"`
  2. If the result is empty, immediately follow the hand-edit path below. Do not read `references/catalog-templates.md`.
  3. If a match is returned, read [`references/catalog-templates.md`](references/catalog-templates.md), inspect the match, and use `instantiate` for a new workbook or `inject` for an existing one.
- Adding a breakdown/color split, or a filter, to an existing worksheet (not a whole new chart) → read [`references/field-edits.md`](references/field-edits.md) and use `add-encoding`/`add-filter`. Run `inspect-workbook` first if the field names the user gave aren't confirmed against the workbook yet.
- No catalog match, and no field-level match above, or a genuinely custom construct neither covers → hand-edit the TWB XML per the steps below.
- First edit/republish of an existing workbook this task → resolve it with `search-content` (`filter: { contentTypes: ["workbook"] }`; see [`../../references/search.md`](../../references/search.md) for disambiguating multiple matches), then `download-workbook`.
- Brand-new workbook with no starting point and no catalog match → read [`references/new-workbook.md`](references/new-workbook.md) first.
`request-workbook-upload`, `publish-workbook`, `download-workbook`, and interactive rendering may be feature-gated — report a missing tool rather than retrying it.

## Fast path for follow-up edits

Reuse the extracted TWB/TWBX, published workbook ID, project ID, name, and view URL from this task. Make the smallest targeted XML edit, validate once, and republish with whichever transport already worked (`overwrite: true` for the same workbook, `false` for a new copy). Don't re-search, re-download, or re-inspect the whole workbook unless the current artifact is missing or stale.

## Existing workbook, first pass this task

1. Resolve the workbook (and destination project, if named) — reuse LUIDs already known this task; otherwise `search-content` (see [`../../references/search.md`](../../references/search.md) for disambiguating multiple matches). Resolve independent lookups in parallel when supported.
2. `download-workbook` with `includeExtract: true` unless this is pure inspection that won't be republished. Unzip a TWBX and edit the root TWB.
3. Add or change content: prefer `inject` against a catalog match (see Routing and [`references/catalog-templates.md`](references/catalog-templates.md)); otherwise hand-edit only the affected worksheet/dashboard and its `<datasource-dependencies>`, matching adjacent XML conventions. **Skip this step** for a plain copy/republish/move with no requested content change.
4. Validate and publish (below).
5. Render the result — see [`../../references/rendering.md`](../../references/rendering.md).

If the downloaded package looks incomplete or a dependency is missing, read [`references/package-and-upload-fallbacks.md`](references/package-and-upload-fallbacks.md). For a new XML construct or a validation failure, read [`references/xml-troubleshooting.md`](references/xml-troubleshooting.md).

## Validate and publish

Skip local validation for unmodified content (plain copy/republish/move) — it's already known-valid. A workbook produced by `instantiate`/`inject` is already validated by that command itself — re-running the standalone validator on it is redundant but harmless. For a hand-edited TWB, after the edit:

```bash
sh "$PLUGIN_ROOT/scripts/run_validator.sh" path/to/workbook.twb
```

(`scripts/` is relative to the plugin root; install `scripts/requirements.txt` only if the validator reports a missing dependency.)

For TWBX, run `unzip -t` after rebuilding it. Publish with `publish-workbook`, using `workbookFilePath` when the runtime can pass a local path, otherwise `request-workbook-upload` first and pass its `workbookUploadId`. A TWB is validated inline (`status: 'invalid'` with structured `errors`/`warnings`); a TWBX is validated by Tableau during publish itself, so a failure there surfaces as a publish error instead of a findings list.

If validation fails, fix the reported lines/elements and retry once; stop after 10 cycles and report the remaining errors.

Record the workbook/project LUIDs, URL, and local artifact paths so a follow-up can use the fast path.

# Requirements

- Keep worksheet, dashboard, datasource, and zone names unique and consistent.
- Prefer fields already declared in the TWB's `<column>` metadata over inspecting the extract or datasource metadata; `inspect-workbook` (see `references/field-edits.md`) reads exactly that metadata.
- Don't invent field names, roles, or numbers not backed by inspected metadata.
- Don't force-fit a catalog template onto a chart it doesn't match — fall back to hand-editing instead of stretching the closest template.

# References

- [`../../references/search.md`](../../references/search.md) — resolving a name/keyword to a workbook and disambiguating multiple matches.
- [`references/catalog-templates.md`](references/catalog-templates.md) — chart catalog: discover, inspect, and render bundled templates via `scripts/tableau_resources.py`.
- [`references/field-edits.md`](references/field-edits.md) — add a breakdown/color split or a filter to an existing worksheet via `inspect-workbook`/`add-encoding`/`add-filter`.
- [`references/new-workbook.md`](references/new-workbook.md) — brand-new workbook, no starting point, no catalog match.
- [`references/package-and-upload-fallbacks.md`](references/package-and-upload-fallbacks.md) — incomplete TWBX package or staged-upload fallback.
- [`references/xml-troubleshooting.md`](references/xml-troubleshooting.md) — new XML construct or validation failure.
- [`../../references/rendering.md`](../../references/rendering.md) — render the published/target view.

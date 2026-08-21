---
name: tableau-workbook-authoring
description: Generate a brand-new Tableau workbook from scratch, or download and modify an existing one, by editing the underlying TWB XML directly and publishing it back to Tableau. Use whenever the user asks to create, build, generate, edit, or modify a Tableau workbook, dashboard, or view — as opposed to just querying/reading existing content (see the tableau-analytics skill for that). Before hand-editing XML, check the `tableau-workbook-templating` skill's resource catalog (`list --tier executable`) for a matching chart template — use this skill for anything the catalog doesn't cover, or for freeform edits to structure the catalog templates don't address.
---

This plugin edits Tableau workbooks as raw XML (a `.twb` file is XML) and
publishes the result back to the site through the `tableau` MCP server. There
are two entry points — **new workbook** and **modify existing workbook** — that
converge on the same validate → publish → render loop. Follow whichever one
matches the user's ask; both are described below.

Two of Tableau's MCP tool groups gate this whole workflow: `authoring`
(`download-workbook`, `request-workbook-upload`,
`validate-upload-and-publish-workbook`) and `mcp-apps`
(`render-interactive-viz`, `get-embed-token`). Both are feature-gated on
Tableau's side. If a tool call comes back as unknown/disabled, tell the user
their site likely doesn't have that feature enabled yet — this isn't
something the plugin can work around.

## Flow 1 — New workbook from scratch

Use this when the user wants a new workbook and has no existing one they want
as a starting point.

### 1. Gather the three required inputs

Don't guess any of these — get them from the user and from the site itself:

- **Published data source.** Use `list-datasources` (or `search-content`) to
  fetch/search the site's published data sources and confirm which one the
  user means. Don't invent field names — inspect the chosen data source's
  metadata before referencing its fields in the XML.
- **What to build.** Ask the user to describe the charts/dashboards they
  want (chart types, fields involved, filters, layout, how many
  worksheets/dashboards). Get enough detail to build real `<worksheet>` and
  `<dashboard>` elements — don't fill gaps with arbitrary chart choices if the
  ask was ambiguous, confirm with the user instead.
- **Destination project.** Use `list-projects` (or `search-content`) to find
  the project the user names. This is required before you can publish in
  step 4 — `validate-upload-and-publish-workbook` needs a `projectId`.

### 2. Author the `.twb` XML

Use the **newest** schema directory under `schemas/` (currently `2026_2`,
`schemas/2026_2/twb_2026.2.0.xsd`) as your structural reference — check
`ls schemas/` if you need to confirm the newest one hasn't changed. Build:

- A `<datasource>` block that references the published data source chosen in
  step 1 (matching its real field names/captions/roles from its metadata).
- One `<worksheet>` per chart the user described, each with a
  `<datasource-dependencies datasource="...">` pointing at a real datasource
  name.
- One or more `<dashboard>` elements with `<zone name="...">` entries that
  match real worksheet names, laid out per what the user asked for.

Keep names unique and references consistent throughout: worksheet names are
unique, dashboard names are unique, every `datasource-dependencies` reference
resolves to a real `<datasource name="...">`, and every dashboard `<zone>`
resolves to a real worksheet.

Then continue to **Validate, publish, and render** below.

## Flow 2 — Modify an existing workbook

Use this when the user already has (or names) a workbook to start from.

### 1. Download it

- Use `search-content` or `list-workbooks` to find it, then
  `download-workbook` with its `workbookId`. Choose `includeExtract` based on the intended outcome:
  - For copy, move, republish, backup, or Tableau Desktop workflows, call
    `download-workbook` with `includeExtract: true`. The downloaded artifact
    must be self-contained.
  - Use `includeExtract: false` only for XML inspection when the downloaded
    artifact will not itself be opened or published.
  - Do not rely solely on workbook metadata such as `hasExtracts`; inspect the
    TWB connections and package contents.
- `download-workbook` returns either `{ "path", "filename", "mimeType" }` (a
  local path on the MCP server's filesystem) or an MCP `resource_link` with a
  presigned S3 `uri` — download that yourself (e.g.
  `curl -o workbook.twbx <uri>`) before continuing.

### 2. Get to the `.twb`

- **If it's `.twbx`** (a zip, even if you asked to exclude the extract — some
  sites always bundle one): unzip it and look for the `.twb` at the
  **root** of the archive — that's the file you edit.
  ```bash
  unzip -o workbook.twbx -d workbook_extracted
  ls workbook_extracted/*.twb
  ```
- **If it's already `.twb`** (`application/xml`), edit it directly.

### 2a. Verify package completeness

Before publishing a TWBX:

1. Run `unzip -t workbook.twbx` and require a clean result.
2. List the archive members and inspect the root TWB for local dependencies,
   including `dbname` and `filename` attributes.
3. For every local Hyper or file connection, confirm that the referenced
   relative path exists as an archive member.
4. Treat a bare opaque identifier, such as a UUID used as a Hyper `dbname`,
   or any missing referenced path as an incomplete package.
5. If the package is incomplete, re-download it with `includeExtract: true`.
   Do not invent or manually rewrite the missing path.
6. When packaged dependencies exist, publish the verified TWBX rather than
   the extracted TWB alone.

A successful XSD validation proves only that the TWB XML is structurally
valid; it does not prove that referenced extracts or files are packaged.

### 3. Edit the XML

Make the change the user asked for with normal text edits — add/adjust
`<worksheet>`, `<datasource>`, `<dashboard>`/`<zone>` elements, calculated
fields, filters, formatting, etc. It's just XML; read enough of the
surrounding structure first to match the existing style (attribute names,
quoting, nesting) instead of guessing a different convention.

Keep names unique and references consistent, same as in Flow 1: worksheet
names are unique, dashboard names are unique, a dashboard's `<zone
name="...">` entries must match real worksheet names, and a worksheet's
`<datasource-dependencies datasource="...">` must match a real `<datasource
name="...">`.

If the workbook was a .twbx, make sure to re-zip it including all original files (not just the .twb).  All files in the original .twbx should also be present in the new package.

Then continue to **Validate, publish, and render** below.

## Validate, publish, and render

Both flows converge here. This whole block — validate → fix → re-validate →
publish → render — is the loop you repeat both while first landing the
workbook and later for each round of user feedback (see the last section).

### 3a. Local validation loop (structural)

Run the bundled validator against your `.twb` (needs `lxml` — install once
with `pip install -r scripts/requirements.txt`):

```bash
python3 scripts/validate_workbook.py path/to/workbook.twb
```

(Resolve `scripts/` relative to this plugin's root — use `$PLUGIN_ROOT` if
your environment exposes it.)

This validates the workbook's XML against the real Tableau TWB XSD schema for
its version, auto-detected from the file and matched against the per-version
schemas bundled under `schemas/`. It prints the detected `version`, the
`schema` file used, and either `RESULT: VALID` or a list of `ERROR`/`FATAL`
issues with line numbers. Exit code `0` means valid; `1` means structurally
invalid (fix and retry); `2` means a setup problem (missing file, or a
workbook version older than the oldest bundled schema). Add `--json` for
machine-readable output if you need to parse the issues programmatically.

This is real structural validation, but it's still **not** the full story:
the schemas deliberately leave some regions unchecked (`processContents`
`"skip"` for things like calculated-field formulas), so it cannot catch
semantic mistakes — dangling `datasource`/`worksheet` references, malformed
formulas, bad connection attributes. Do not skip to publishing while this is
failing; do treat a clean pass here as necessary, not sufficient.

### 3b. Remote validation (authoritative) and publish

Once the local check passes, hand it to Tableau Server, which does the real
authoritative validation:

1. `request-workbook-upload` with `fileName` ending in `.twb`. Returns
   `{ workbookUploadId, uploadUrl, requiredHeaders, expiresAt }`.
2. Upload the file's bytes with an HTTP PUT to `uploadUrl`, sending
   `requiredHeaders` (e.g. `Content-Type: application/xml`):
   ```bash
   curl -X PUT -H "Content-Type: application/xml" --data-binary @path/to/workbook.twb "<uploadUrl>"
   ```
3. Call `validate-upload-and-publish-workbook` with the `workbookUploadId`, a
   `name`, and the `projectId` (from Flow 1 step 1, or the existing
   workbook's project in Flow 2). Set `overwrite` only if intentionally
   replacing an existing workbook of that name.

This tool validates on Tableau's server and **only publishes if validation
passes** — one atomic call, not two.

### 3c. The fix-and-retry loop — capped at 10 attempts

If either stage fails, fix the `.twb` and retry from 3a:

- Local failure: fix the reported line/element against the XSD, re-run 3a.
- Remote failure (`{ "status": "invalid", "errors": [...] }`): each error
  includes `line`, `column`, `elementName`, `message` — fix those exact
  spots, re-run 3a, then repeat 3b from `request-workbook-upload` again
  (staged uploads are short-lived and single-use — always request a fresh one
  on retry, never reuse an old `workbookUploadId`).

**Count attempts. Stop after 10 full validate-fix cycles** for a given round
of edits. If still failing at that point, stop, tell the user what's still
failing (with the specific errors) and ask how they'd like to proceed —
don't loop indefinitely.

A successful publish returns `{ "status": "published", "data": ..., "url": ... }`
— note the workbook's `id`/LUID from `data` and the `url`, then move on to
rendering.

### 4. Render the result

If the user mentioned a specific view within the workbook (either created or modified), use that view's URL.  If not, use the default (first) view in the workbook to generate the URL.
Render the published workbook using [`../shared/rendering.md`](../shared/rendering.md) for the exact tool calls
and the fallback path.

## Handling feedback

Expect the user to ask for more changes after seeing the result — in both
flows. When they do:

1. Edit the same local `.twb` file to make the requested change (same rules
   on unique names and consistent references as above).
2. Repeat **Validate, publish, and render** from 3a — a fresh local
   validation pass, a fresh `request-workbook-upload`/publish cycle (capped
   at 10 fix-and-retry attempts again for this round), and re-render.
3. Keep repeating this cycle for as many rounds of feedback as the user gives.

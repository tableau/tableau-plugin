---
name: tableau-data-app-authoring
description: End-to-end workflow for building a Tableau data app — scaffold a new app with the scaffold-data-app MCP tool and finalize its returned postUnzip plan, wire in a published or embedded datasource, author the extension's query and visualization yourself from the human's stated criteria/vibe, then package the workspace into a .twbx and publish it with the MCP publish-workbook flow. Use for requests to create, build, vibe-code, or publish a Tableau data app or custom viz-extension web app that queries a datasource live. Do not use for a standard native Tableau workbook or dashboard built from marks, Show Me, or the chart catalog — see tableau-workbook-authoring — or to open, show, or render an already-published data app or other existing Tableau content — see tableau-content-viewer.
---

# Tableau Data App Authoring

Builds a Tableau data app from nothing to published. Walk the stages top to
bottom — every request follows all five, in order.

```
Scaffold + finalize  →  Wire datasource*  →  Author (you)  →  Package  →  Publish
```

\* Wiring is a prerequisite to a *working* app: the name-only `scaffold-data-app`
ships an empty `<datasources/>`, so a scaffolded app reaches no datasource at
runtime and renders "no data source found." Wire a datasource into the
`.twb` before authoring against it — see Wire a datasource in below. (Publishing the
starter as-is to prove packaging works does not need it.) For an embedded
datasource, Wire also inserts an extra Package + Publish checkpoint before
Author, to verify the file's inferred types actually work — see Embedded
datasource below.

**Already have a built app locally?** Skip straight to whichever applies:
**Package into a .twbx** (unpacked `<App Name>/` folder) or **Publish**
(already a `.twbx`) — but first confirm the `.twb`'s `<datasources>` is
actually wired (not empty) and the package layout is correct, since none of
this skill's tooling has run against it.

**Division of labor: you write ALL the code, every stage, always — including
`app.js`.** The human "vibe codes" by describing what they want (criteria,
theme, vibe, target insights) — they do not write `app.js` themselves. Read
the two bundled guides before authoring: [Design a data app](references/design-data-app.md)
(what to build) and [Build a data app](references/build-data-app.md) (how, using this
skill's local tools). Only skip authoring `app.js` if the human explicitly says
they want to write it themselves for this app (rare) — see the exception at
the end of Author `app.js` below.

There's no separate validation stage — `publish-workbook` is where errors
surface. Get package *layout* right (see Package into a .twbx) or the
workbook won't open at all.

## Scaffold and finalize the workspace

Call the `scaffold-data-app` MCP tool with the app name:

> scaffold-data-app({ datappName: "Sales Demo" })

**Both transports return the same static, un-substituted template *zip* plus an
identical `postUnzip` plan** — they differ only in how the zip gets onto disk:

- **local (stdio):** result has `filePath` + a `postUnzip` plan. `filePath`
  points at the same static template **zip** the S3 path serves — it is *not* a
  pre-finalized workspace directory. Unzip it to a temp dir, then apply the plan
  there. No download needed, but unzip still is.
- **remote (http):** result has `s3URL` + a `postUnzip` plan. Download the zip
  from `s3URL` first, then unzip it to a temp dir and apply the plan there.

Past the fetch step the two are identical: same unzip, same plan, including the
root-dir rename (`Data App Name` → `<displayName>`).
Apply the plan deterministically with the bundled script — applying it freehand
leaves half-replaced `TODO-MANIFEST-ID` / `TODO App Name` tokens or interleaves
edits and renames in the wrong order.

Finalize the plan (both transports — save, fetch, apply). Scripts referenced
below live under `scripts/`, relative to this skill directory (`$SKILL_DIR`):

1. Save the plan:

   ```bash
   SKILL_DIR="<absolute path to this skill directory>"
   WORK="$(mktemp -d -t dataapp)"

   # Save the postUnzip object verbatim (do NOT reformat — find tokens must match byte-for-byte)
   cat > "$WORK/plan.json" <<'PLAN_JSON'
   { …paste the result's postUnzip object here… }
   PLAN_JSON
   ```

2. Fetch the template — **remote (http)** downloads then unzips:

   ```bash
   curl -fsSL "<s3URL>" -o "$WORK/template.zip"
   mkdir -p "$WORK/unzipped"
   unzip -q "$WORK/template.zip" -d "$WORK/unzipped"
   ```

   **Local (stdio)** unzips only, no download (`filePath` is already the same
   template zip, just sitting on local disk instead of behind a presigned URL):

   ```bash
   mkdir -p "$WORK/unzipped"
   unzip -q "<filePath>" -d "$WORK/unzipped"
   ```

3. Apply the plan — identical for both transports (edits first, then renames;
   verifies no placeholders survive):

   ```bash
   python3 "$SKILL_DIR/scripts/apply_plan.py" "$WORK/unzipped" "$WORK/plan.json"
   ```

   `scripts/apply_plan.py` prints the finalized workspace root on stdout. See
   its header comment for the full contract; it hard-fails if a `find` token is
   missing (the zip is stale / out of sync with the plan) rather than emitting a
   broken workspace.

At the end of this stage you have a finalized workspace directory:
```
<App Name>/
  <App Name>.twb
  Packages/com.tableau.mcp.<slug>/
    manifest.json
    extensions/data-app.trex
    content/index.html
    content/src/app.js      ← the authoring surface
    content/src/…
```

**Sheet name:** the worksheet's name comes from the scaffold template's
default and may not be what the user wants. It's a plain string with no
hash/join-key involved, so it's freely hand-editable at any point before
packaging — just edit all 3 matching locations in the `.twb` to the same new
value: the `<worksheet name='...'>` tag, the `<window class='worksheet'
name='...'>` tag, and `<referenced-view ... viewId='...' />`.

## Wire a datasource in

The scaffolded `.twb` ships an **empty `<datasources/>`** (both at the workbook
root and inside the worksheet `<view>`). At runtime the app calls
`getAllDataSourcesAsync()` and finds nothing → it renders **"no data source found
in the workbook."** To query live data the workbook must have a real datasource
wired in — this stage is a prerequisite for a working app.

Do this once the user has told you what to connect to; it is skippable if the
user only wants to publish the starter to prove packaging.

**Ask the user: published or embedded?** Either way, the datasource's
identity can come straight from the user, or be reused from a datasource
already wired into some other existing workbook — see Reuse an existing
workbook's datasource below.

- **Published** — the app queries a datasource that already exists on the
  server (a `sqlproxy` connection, resolved live by VDS). Default choice.
- **Embedded** — the app queries a local file bundled *inside* the `.twbx`
  (a `federated` connection wrapping a connector-specific named connection).
  The wiring script dispatches by file extension: `.csv`, `.xlsx`, `.json`,
  `.hyper` (requires a `descriptor.json` with a `fields` list — its schema
  isn't stdlib-readable), `.zip` (spatial/shapefile — any `.zip` passed here
  is assumed to be a shapefile zip). Access/SPSS/SAS have no script support —
  ask the user to convert to one of the above.

Do **not** hand-edit the XML for either path — both anchors must be filled
atomically with a matching join key across multiple coordinated locations, or
the app silently reaches no data. Use the bundled wiring script for whichever
path applies.

**Published datasource:** the wiring spans four coordinated locations (root
datasource `name`, root `relation connection`, view `datasource name`,
`datasource-dependencies datasource`) that must all carry the identical
`sqlproxy.<hash>` join key. Use `scripts/wire_datasource.py`, which does all
four edits atomically and hard-fails rather than emitting a half-wired workbook.

1. **Get the datasource's identity** with `list-datasources` (LUID, name/caption,
   contentUrl, and the server host + site) and `get-datasource-metadata({ datasourceLuid })`
   (field names + datatypes). The published DS **contentUrl** is the
   `repositoryId`. (To reuse an existing workbook's datasource instead, see
   Reuse an existing workbook's datasource below — it gets you here, then
   continues at step 2.)
2. **Write a descriptor** listing *only the fields the app will query* (name +
   datatype + role), e.g.:

   ```bash
   cat > "$WORK/descriptor.json" <<'DS_JSON'
   {
     "caption": "<Friendly Name>",
     "repositoryId": "<published DS contentUrl>",
     "site": "<site>",
     "server": "<server host, e.g. 10ax.online.tableau.com>",
     "channel": "https", "port": 443,
     "fields": [
       { "name": "Profit", "datatype": "real",   "role": "measure"   },
       { "name": "Region", "datatype": "string", "role": "dimension" }
     ]
   }
   DS_JSON
   ```

3. **Run the wiring script** (it prints the wired `.twb` path, and generates a
   consistent `sqlproxy.<hash>` unless you supply `connectionName`):

   ```bash
   python3 "$SKILL_DIR/scripts/wire_datasource.py" "<App Name>/<App Name>.twb" "$WORK/descriptor.json"
   ```

The script hard-fails if an anchor is missing (already wired / template drifted),
if any empty `<datasources />` survives, or if the join key isn't referenced ≥4×.
Trust that failure over patching the XML by hand. `datatype` maps to the column
`type` (`real`/`integer` → quantitative, `date`/`datetime` → ordinal, else
nominal); `role: "measure"` gets a `Sum` aggregation, `dimension` a `Count`.

**Embedded datasource:** the wiring fills the same two anchors as the
published path but with a `federated.<hash>` join key wrapping a
connector-specific named connection instead of `sqlproxy`. Use
`scripts/wire_embedded_datasource.py`, which dispatches on file extension,
infers column datatype/role straight from the file where possible (there's no
MCP introspection tool for a local file), and copies the file into the
workspace for you. **No date type:** inference only distinguishes
integer/real/string — a date-looking column comes back `string`/nominal,
though VDS may still return it as an ISO-ish timestamp at query time
regardless of that declared type.

1. **Ask the user which file to embed** (`.csv`, `.xlsx`, `.hyper`, `.zip`
   spatial, or `.json` — see above). Get its path. (To reuse an existing
   workbook's embedded datasource instead of a fresh file, see Reuse an
   existing workbook's datasource below — it gets you here, then continues
   at step 2.)
2. **Run the wiring script:**

   ```bash
   python3 "$SKILL_DIR/scripts/wire_embedded_datasource.py" "<App Name>/<App Name>.twb" "<path-to-file>"
   ```

   - `.csv` / `.xlsx` / `.json` need no descriptor — the script reads the
     file itself (header + a row sample) to infer each column's datatype
     (integer/real/string, plus `boolean` for JSON) and role
     (measure/dimension).
   - `.hyper` **requires** a `descriptor.json` (third argument) with a
     non-empty `fields` array (`{ name, datatype }` at minimum) — a
     `.hyper`'s schema isn't stdlib-readable, so there's nothing to
     introspect.
   - `.zip` (spatial) reads the field list from the zip's `.dbf` member via a
     stdlib parser; a synthetic spatial `Geometry` field is added
     automatically.
   - `.json` (v1 scope): a flat array of flat objects only — a field whose
     value is itself an object/array is rejected rather than silently
     mistyped. Every JSON number is wired as `real`, never `integer`
     (Tableau's own JSON introspection does the same).

   This also copies the file to `<App Name>/Data/<filename>` — a sibling of
   `Packages/` at the workspace root, per the Package into a .twbx stage below.
3. **Override inference if needed.** If a column's inferred datatype/role is
   wrong (e.g. a numeric ID that should be a dimension, not a measure), pass a
   `descriptor.json` argument (required for `.hyper`, optional otherwise) with
   a `fields` array (`{ name, datatype, role }`) for just the fields to
   override — same shape as the published path's descriptor, minus
   `repositoryId`/`site`/`server`.
4. **Verify before authoring — inferred types have no ground truth to check
   against.** Publish once as a checkpoint before moving on to Author `app.js`,
   under a distinct scratch name so it can never collide with (and never
   needs to overwrite) any real workbook — `"<App Name> (checkpoint)"`, not
   `"<App Name>"`: package the current workspace (see Package into a .twbx)
   and `publish-workbook({ name: "<App Name> (checkpoint)", ... })` — the
   checkpoint's `app.js` doesn't matter yet, the unedited template default is
   fine. Then:
   - `get-workbook({ workbookId })` — confirm the datasource entry shows
     `queryability.isQueryable: true`. `queryability` can be omitted for a few
     seconds right after publish (server-side indexing lag, not a failure) —
     retry once before treating a missing/false result as broken wiring.
   - `query-datasource({ datasourceLuid, query })` against the wired fields —
     confirm real rows come back with the expected values/aggregation. VDS can
     still return sensible values through a wrong declared type in some cases
     (e.g. a date column inferred as nominal/string can still come back as an
     ISO-ish timestamp) — check the actual returned values, not just whether
     the query errored.

   If a field's datatype/role is wrong: don't hand-edit, and don't re-run the
   wiring script against this already-wired `.twb` (it hard-fails — the
   anchors are no longer template placeholders). Re-run
   `wire_embedded_datasource.py` against a fresh, unwired copy of the
   finalized workspace (keep one from before this step) with a corrected
   `descriptor.json`, then repackage and republish under the same scratch
   name (`overwrite: true` — safe here, since it only ever replaces the
   checkpoint you created), and repeat this verification.

   Only move on to Author `app.js` once verification passes. Package and
   publish again at the end **under the app's real name** to ship the
   finished app — a first-time publish, so `overwrite` stays `false` unless
   the user separately wants to replace an existing real workbook of that
   name (see Publish below). The checkpoint left under
   `"<App Name> (checkpoint)"` is not the deliverable.

The script hard-fails rather than emit a half-wired workbook — on a missing
anchor, a surviving empty `<datasources />`, the `federated.<hash>` connection
name referenced <3×, or the named connection (`textscan.<hash>` /
`excel-direct.<hash>` / `hyper.<hash>` / `ogrdirect.<hash>` /
`semistructpassivestore-direct.<hash>`) referenced <2× (this path verifies two
join keys with separate thresholds, unlike `wire_datasource.py`'s single
`sqlproxy.<hash>` key).

**Reuse an existing workbook's datasource:** point either path above at a
datasource already wired into some *other* already-published workbook,
instead of a fresh published DS or a fresh local file. Works regardless of
that datasource's type — resolve it, then continue in whichever path above
actually applies, picking up at its step 2 (you already have what its own
step 1 would have produced).

1. Find the workbook (`list-workbooks`/`search-content`; ask the user which
   if ambiguous), then call `get-workbook({ workbookId })` and read
   `upstreamDatasources[]` — ask which entry if it lists more than one.
2. Each entry's `datasourceType` says which path to continue in, and its
   `luid` is the `datasourceLuid` that path's own step 1 would have
   produced:
   - **`"published"`** — still run the rest of Published datasource step 1
     (`list-datasources` filtered by this LUID, for `contentUrl`/site/server
     — `get-workbook` doesn't carry those — plus
     `get-datasource-metadata({ datasourceLuid })` for fields), then
     continue at step 2. Filter candidate fields to `columnClass: "COLUMN"`
     (drop `CALCULATION`/`TABLE_CALCULATION` as in the embedded case, plus
     `BIN`/`GROUP` — those are also Tableau-computed groupings with no
     matching raw column). This metadata response often includes an
     explicit `role` (`"DIMENSION"`/`"MEASURE"`) per field — when present,
     lowercase and use it directly instead of inferring from
     `defaultAggregation`; fall back to the embedded case's
     `defaultAggregation`-based heuristic when `role` is absent (it isn't
     always populated). **Caveat, confirmed by direct testing:** this
     dispatch branch — a workbook whose `get-workbook` response actually
     reports `datasourceType: "published"` — could not be produced or
     exercised end-to-end in this environment. `get-workbook`'s "published"
     classification appears to require server-side provenance from
     Tableau's own "connect to a published datasource" flow, not just a
     structurally-correct `sqlproxy` connection: wiring a fresh app directly
     at a real published datasource via `wire_datasource.py` and publishing
     it came back from `get-workbook` as `datasourceType: "embedded"` with a
     brand-new LUID (unrelated to the original), even though the connection
     queried real live data correctly. A real fixture
     (`tableau-mcp/tests/e2e/fixtures/workbooks/superstore-datasource.twb`)
     shows genuine published connections carry a `derived-from` provenance
     attribute on `repository-location` that `wire_datasource.py` doesn't
     emit; manually adding it to a fresh publish gets a hard `400` from
     `publish-workbook`, confirming it's server-populated, not
     client-authorable. Treat this branch as documented-but-unverified until
     tested against a genuine Desktop/Web-Authoring-connected workbook.
   - **`"embedded"`** — continue at Embedded datasource step 2, with two
     substitutions: the file to wire is not a fresh one from the user — get
     it by calling `download-workbook({ workbookId })`, unzipping the
     result, and pulling the real file out of *somewhere* under its `Data/`
     directory — a Tableau-Desktop-authored workbook nests it a level deeper
     (`Data/<workbook name>/<filename>`, not flat `Data/<filename>`), so
     search the whole `Data/` tree rather than assuming a fixed depth.
     Preserve its original filename when you copy it out, since the wiring
     script's caption default is derived from it — but don't actually rely
     on that default: always pass an explicit `"caption"` in the descriptor,
     sourced from the matched `upstreamDatasources[].name` entry. The
     script's filename-derived default has a confirmed bug for filenames
     containing " - " (its regex only replaces the dash character, not the
     surrounding spaces it sits inside — e.g. `"Sample - Superstore.xlsx"`
     comes out as `"Sample   Superstore"`), and the authoritative name is
     already sitting in `upstreamDatasources[]` for free. And always build a
     descriptor from `get-datasource-metadata({ datasourceLuid })`'s
     authoritative fields rather than letting the script infer blind —
     first filter to `columnClass: "COLUMN"` entries in the group matching
     the datasource's real table (drop `CALCULATION`/`TABLE_CALCULATION`
     entries: those are Tableau-computed fields with no matching column in
     the actual file, so feeding them into the descriptor would describe
     columns that don't exist). For each remaining field, lowercase its
     `dataType` (`INTEGER`→`integer`, `REAL`→`real`, `STRING`→`string`,
     `BOOLEAN`→`boolean` for a JSON target, else `string`), and only set
     `role` when `defaultAggregation` disagrees with the script's own
     default (`SUM`-like → measure, `COUNT`-like → dimension) — same shape
     as any other override descriptor. Step 4's checkpoint verification still
     applies.

## Author `app.js`

**Always author `app.js` yourself — this is the fixed default, not a
fallback.** The human vibe-codes: they describe what they want (criteria,
theme, target insights, audience) and you turn that into the actual
`ds.queryAsync(...)` → chart implementation.

Read [Design a data app](references/design-data-app.md) (what to build) and
[Build a data app](references/build-data-app.md) (how — introspect the
datasource, design the chart, edit `content/src/app.js`, follow the sandbox
rules in its `AUTHOR YOUR APP HERE` comment) and follow that workflow; it is
not restated here. There is no local preview — the visual review happens live
in Tableau, after publish.

**Exception — the human wants to write `app.js` themselves:** only skip
authoring if the human explicitly says they want to write `app.js` themselves
for this app — an override of the default, not the norm. Stop and hand off:
tell them the workspace path
(`Packages/com.tableau.mcp.<slug>/content/src/app.js`) and point them at
[Design a data app](references/design-data-app.md) and
[Build a data app](references/build-data-app.md) as their own reference.
Resume at Package into a .twbx once they say it's authored.

## Package into a .twbx

A `.twbx` is a zip of the workspace **contents** with the `.twb` and `Packages/`
at the **archive root** — never nested inside the `<App Name>/` folder. Nesting
is the #1 cause of `NativeException: An unexpected error occurred opening the
packaged workbook` and `PackageValidationException: Package directory contains no
extension .trex files under extensions/`.

Package with the proven two-step zip (run from *inside* the workspace dir so
paths are root-relative), excluding OS cruft:

```bash
cd "<App Name>"                      # the finalized workspace dir
OUT="../<App Name>.twbx"
rm -f "$OUT"
zip -X    "$OUT" "<App Name>.twb"                                    # .twb at root, first
zip -rX   "$OUT" Packages -x '*.DS_Store' '*/.DS_Store' '__MACOSX*'  # package tree, no cruft
unzip -l "$OUT"                      # sanity: .twb + Packages/… at top level, no <App Name>/ prefix
```

The listing must show `<App Name>.twb` and `Packages/com.tableau.mcp.<slug>/…`
at the top level with no wrapping folder and no `.DS_Store`/`__MACOSX` entries.

**If Wire a datasource in embedded a local file** (any of `.csv`/`.xlsx`/
`.hyper`/`.zip`/`.json`), the `.twbx` also needs the `Data/` directory zipped
in at the archive root — a third step, run after the two above:

```bash
zip -rX "$OUT" Data -x '*.DS_Store' '*/.DS_Store' '__MACOSX*'
```

The listing must then also show `Data/<filename>` at the top level, alongside
`<App Name>.twb` and `Packages/…` — never nested inside `Packages/`.

> The template these workspaces come from is already publish-valid (`.twb`
> extension wired into a pane, `.trex` with `author email`, `<resources>` block,
> `<icon>`, `min-api-version`). Packaging is the only structural step you own.

## Publish

Uses the MCP publish tools (gated by the `authoring-tools` feature; not available
to Slack clients).

1. **Find the target project LUID:**
   > list-projects({})
   Pick the project the user wants (ask if ambiguous).

2. **Publish.** Two paths — pick based on transport:

   - **Local (stdio), simplest:** the `.twbx` is on the MCP server's own
     filesystem, so pass it directly:
     > publish-workbook({ workbookFilePath: "<abs path to .twbx>", name: "<App Name>", projectId: "<LUID>", overwrite: false })

   - **Remote (http) / staged uploads configured:** stage the bytes first, then
     publish by id:
     > request-workbook-upload({ filename: "<App Name>.twbx" })   → returns an upload URL + workbookUploadId
     > (upload the .twbx bytes to the returned URL — staged-workbook-upload)
     > publish-workbook({ workbookUploadId: "<id>", name: "<App Name>", projectId: "<LUID>", overwrite: false })

3. **Report the outcome.** On success `publish-workbook` returns
   `status: "published"` with the workbook `url` and any `warnings` — give the
   user the URL. If it returns `status: "invalid"` (or an error), surface the
   `errors`/`warnings` verbatim; common causes trace back to `.twb`/`.trex`
   wiring, not packaging. Set `overwrite: true` only if the user wants to replace
   an existing workbook of the same name.

## Non-negotiable limits

- Don't nest the workspace folder inside the `.twbx`. Zip the *contents*
  (`.twb` + `Packages/` at root), not the `<App Name>/` directory — always
  `unzip -l` to confirm.
- Don't apply a postUnzip plan freehand. Use `scripts/apply_plan.py` — edits
  before renames, renames deepest-first, verified; see its header comment for
  the full contract.
- Don't hand-edit the `<datasources/>` wiring. Use `scripts/wire_datasource.py`
  (published) or `scripts/wire_embedded_datasource.py` (embedded file) —
  freehand edits mismatch the join key across their coordinated locations or
  leave an empty `<datasources />` anchor, and the app silently reaches no data.
- Don't nest `Data/` inside `Packages/`, or forget to zip it at all. An
  embedded file's `Data/` directory must sit at the `.twbx` archive root, as a
  sibling of `Packages/` — not nested inside it. `scripts/wire_embedded_datasource.py`
  copies the file to the right place; the Package stage still needs the extra
  `zip -rX "$OUT" Data` step, or the workbook ships with no data behind it.
- Don't assume a local result's `filePath` is already substituted, or skip
  unzip because it's local. `filePath` points at the same static,
  un-substituted template **zip** the S3 path serves — not a finalized
  workspace directory. Unzip it (no download needed, but unzip still is) and
  apply the plan before authoring, exactly like the remote path.
- Don't hand off `app.js` to the human unprompted. Authoring `app.js` yourself
  is the fixed default — always write it from the human's stated
  criteria/vibe. Only hand off when the human explicitly says they want to
  write it themselves.
- Don't ship OS cruft. Exclude `.DS_Store` / `__MACOSX` from the `.twbx`.

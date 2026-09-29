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
starter as-is to prove packaging works does not need it.)

**Division of labor: you write ALL the code, every stage, always — including
`app.js`.** The human "vibe codes" by describing what they want (criteria,
theme, vibe, target insights) — they do not write `app.js` themselves. Read
the two bundled guides before authoring: [Design a data app](references/design-data-app.md)
(what to build) and [Build a data app](references/build-data-app.md) (how, using this
skill's local tools). Only skip authoring `app.js` if the human explicitly says
they want to write it themselves for this app (rare) — see the exception at
the end of Author `app.js` below.

There is intentionally **no separate validation stage** — a TWBX cannot be
pre-validated (Tableau validates extracts/extensions at publish time), so
`publish-workbook` surfaces any errors when you reach Publish. The one thing
you must get right before then is package *layout* (Package into a .twbx),
or the workbook won't open at all.

## Scaffold and finalize the workspace

Call the `scaffold-data-app` MCP tool with the app name:

> scaffold-data-app({ datappName: "Sales Demo" })

**Both transports return the same static, un-substituted template *zip* plus an
identical `postUnzip` plan.** They no longer differ in what's returned or how
it's finalized — only in how the zip gets onto disk:

- **local (stdio):** result has `filePath` + a `postUnzip` plan. `filePath`
  points at the same static template **zip** the S3 path serves — it is *not* a
  pre-finalized workspace directory. Unzip it to a temp dir, then apply the plan
  there. No download needed, but unzip still is.
- **remote (http):** result has `s3URL` + a `postUnzip` plan. Download the zip
  from `s3URL` first, then unzip it to a temp dir and apply the plan there.

Past the fetch step the two are identical: same unzip, same plan — including the
root-dir rename (`Data App Name` → `<displayName>`), which now applies to both.
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

## Wire a datasource in

The scaffolded `.twb` ships an **empty `<datasources/>`** (both at the workbook
root and inside the worksheet `<view>`). At runtime the app calls
`getAllDataSourcesAsync()` and finds nothing → it renders **"no data source found
in the workbook."** To query live data the workbook must have a real datasource
wired in — this stage is a prerequisite for a working app.

Do this once the user has told you what to connect to; it is skippable if the
user only wants to publish the starter to prove packaging.

**Ask the user: published or embedded?**

- **Published** — the app queries a datasource that already exists on the
  server (a `sqlproxy` connection, resolved live by VDS). This is the default
  and what most apps want.
- **Embedded** — the app queries a local file bundled *inside* the `.twbx`,
  with no server-side datasource at all (a `federated` connection wrapping a
  connector-specific named connection). Useful for demos, fixtures, or data
  that has nowhere published to live. The wiring script dispatches by file
  extension:
  - **`.csv`, `.xlsx`, `.json`** — validated end-to-end (scaffold → wire →
    package → publish → query-datasource returning real rows, including
    correct `SUM`/`COUNT` aggregation).
  - **`.hyper`** (wiring-only — the file must already exist; requires a
    `descriptor.json` with a `fields` list, since a `.hyper`'s schema isn't
    stdlib-readable) and **`.zip`** (spatial/shapefile — v1 assumes any `.zip`
    passed here is a shapefile zip) — file-level wiring and packaging are
    proven correct against real ground-truth data, but neither has a
    confirmed live query-datasource pass on this environment: Hyper hit an
    extract-server connectivity error (reproduced even on an untouched
    control workbook), and ogrdirect hit a 403 site-capability error
    (reproduced on a valid embedded datasource but not on a no-datasource
    control) — both look like environment/site gaps, not connector defects,
    but treat them as "wiring validated, live query unconfirmed" rather than
    fully supported until re-tested somewhere that isn't blocked.
  - Tableau can in principle also embed Access/SPSS/SAS files, but those have
    no script support here — ask the user to provide (or let you convert to)
    one of the supported types above.

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
   `repositoryId`.
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
connector-specific named connection instead of `sqlproxy` — `textscan`
(`.csv`), `excel-direct` (`.xlsx`), `hyper` (`.hyper`), `ogrdirect` (`.zip`,
spatial), or `semistructpassivestore-direct` (`.json`). Use
`scripts/wire_embedded_datasource.py`, which dispatches on file extension,
infers column datatype/role straight from the file where possible (there's no
MCP introspection tool for a local file), and copies the file into the
workspace for you. **No date type:** inference only distinguishes
integer/real/string — a date-looking column comes back `string`/nominal,
though VDS may still return it as an ISO-ish timestamp at query time
regardless of that declared type.

1. **Ask the user which file to embed** (`.csv`, `.xlsx`, `.hyper`, `.zip`
   spatial, or `.json` — see above). Get its path.
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

The script hard-fails rather than emit a half-wired workbook — on a missing
anchor, a surviving empty `<datasources />`, the `federated.<hash>` connection
name referenced <3×, or the named connection (`textscan.<hash>` /
`excel-direct.<hash>` / `hyper.<hash>` / `ogrdirect.<hash>` /
`semistructpassivestore-direct.<hash>`) referenced <2× (this path verifies two
join keys with separate thresholds, unlike `wire_datasource.py`'s single
`sqlproxy.<hash>` key).

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

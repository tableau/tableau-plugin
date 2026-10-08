---
name: tableau-data-app-authoring
description: End-to-end workflow for building a Tableau data app — scaffold a new app with the scaffold-data-app MCP tool and finalize its returned postUnzip plan, wire in a published datasource, author the extension's query and visualization yourself from the human's stated criteria/vibe, then package the workspace into a .twbx and publish it with the MCP publish-workbook flow. Use for requests to create, build, vibe-code, or publish a Tableau data app or custom viz-extension web app that queries a datasource live. Do not use for a standard native Tableau workbook or dashboard built from marks, Show Me, or the chart catalog — see tableau-workbook-authoring — or to open, show, or render an already-published data app or other existing Tableau content — see tableau-content-viewer.
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

If `scaffold-data-app` is absent or errors, report that to the user — don't
hand-build the template.

The result carries an un-substituted template **zip** plus a `postUnzip` plan,
and either `filePath` (the zip on local disk) or `s3URL` (download it first).
Branch on whichever is present; past the fetch step the steps are identical.
It also returns `allowedOrigins: string[]` — any external origin the app
fetches from must be in that list.

Apply the plan deterministically with the bundled script — applying it freehand
leaves half-replaced `TODO-MANIFEST-ID` / `TODO App Name` / `TODO Sheet Name` tokens or interleaves
edits and renames in the wrong order.

Finalize the plan (save, fetch, apply). Scripts referenced
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

2. Fetch the template — with `s3URL`, download then unzip:

   ```bash
   curl -fsSL "<s3URL>" -o "$WORK/template.zip"
   mkdir -p "$WORK/unzipped"
   unzip -q "$WORK/template.zip" -d "$WORK/unzipped"
   ```

   With `filePath`, unzip only:

   ```bash
   mkdir -p "$WORK/unzipped"
   unzip -q "<filePath>" -d "$WORK/unzipped"
   ```

3. Apply the plan (edits first, then renames; verifies no placeholders
   survive):

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
    extensions/data-app.trex
    content/index.html
    content/src/app.js      ← the authoring surface
    content/src/styles.css
    content/src/tableau.extensions.1.latest.js
```

**Sheet name:** the worksheet is named after the app's display name. It's a
plain string with no hash/join-key involved, so it's freely hand-editable at
any point before packaging — edit all 3 matching locations in the `.twb` to
the same new value: the `<worksheet name='...'>` tag, the `<window class='worksheet'
name='...'>` tag, and `<referenced-view ... viewId='...' />`.

## Wire a datasource in

The scaffolded `.twb` ships an **empty `<datasources/>`** (both at the workbook
root and inside the worksheet `<view>`). At runtime the app calls
`getAllDataSourcesAsync()` and finds nothing → it renders **"no data source found
in the workbook."** To query live data the workbook must have a real datasource
wired in — this stage is a prerequisite for a working app.

Do this once the user has told you what to connect to; it is skippable if the
user only wants to publish the starter to prove packaging.

The app queries a datasource that already exists on the server (a `sqlproxy`
connection, resolved live by VDS). Its identity can come straight from the
user, or be reused from a datasource already wired into some other existing
workbook — see Reuse an existing workbook's datasource below.

Do **not** hand-edit the XML — the anchors must be filled atomically with a
matching join key across multiple coordinated locations, or the app silently
reaches no data. Use the bundled wiring script.

**Published datasource:** the wiring spans four coordinated locations (root
datasource `name`, root `relation connection`, view `datasource name`,
`datasource-dependencies datasource`) that must all carry the identical
`sqlproxy.<hash>` join key. Use `scripts/wire_datasource.py`, which does all
four edits atomically and hard-fails rather than emitting a half-wired workbook.

**More than one datasource:** wire them all in **one run** — the script fills
the empty anchors once, so it can't add another datasource to an already-wired
`.twb` (re-scaffold instead). It lists every datasource on the app's sheet,
which is required: the server only connects datasources listed there, so a
datasource placed only on some other sheet fails at query time. Don't move
datasources onto separate sheets afterward.

1. **Get the datasource's identity** with `list-datasources` (LUID, name/caption,
   contentUrl, and the server host + site) and `get-datasource-metadata({ datasourceLuid })`
   (field names + datatypes). The published DS **contentUrl** is the
   `repositoryId`. (To reuse an existing workbook's datasource instead, see
   Reuse an existing workbook's datasource below — it gets you here, then
   continues at step 2.)
2. **Write a descriptor** listing *only the fields the app will query* (name +
   datatype + role). Use `"site": ""` for the Default site. One datasource:

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

   Several datasources (any number) go in a `datasources` array, **primary
   first**; each entry has the same shape as the single-datasource object:

   ```json
   { "datasources": [ { "caption": "Orders", "...": "..." },
                      { "caption": "People", "...": "..." } ] }
   ```

   The primary is the sheet's main datasource. The app reaches every one by
   caption via `getAllDataSourcesAsync()` — look each up by `name`, never by
   position (the list isn't returned in wiring order).

3. **Run the wiring script** (it prints the wired `.twb` path, and generates a
   consistent `sqlproxy.<hash>` unless you supply `connectionName`):

   ```bash
   python3 "$SKILL_DIR/scripts/wire_datasource.py" "<App Name>/<App Name>.twb" "$WORK/descriptor.json"
   ```

The script hard-fails if an anchor is missing (already wired / template drifted),
if any empty `<datasources />` survives, if a join key isn't fully referenced, or
if a `repositoryId` or `connectionName` repeats across datasources.
Trust that failure over patching the XML by hand. `datatype` maps to the column
`type` (`real`/`integer` → quantitative, `date`/`datetime` → ordinal, else
nominal); `role: "measure"` gets a `Sum` aggregation, `dimension` a `Count`.

**Reuse an existing workbook's datasource:** point the Published path above
at a datasource already wired into some *other* already-published workbook,
instead of a fresh published DS. Only applies when that datasource actually
resolves as published — resolve it, then continue in Published datasource
above, picking up at its step 2 (you already have what its own step 1 would
have produced).

1. Find the workbook (`list-workbooks`/`search-content`; ask the user which
   if ambiguous), then call `get-workbook({ workbookId })` and read
   `upstreamDatasources[]` — ask which entry if it lists more than one.
2. Check the matched entry's `datasourceType`:
   - **`"embedded"`** — it can't be reused via this path; ask the user for a
     published datasource instead.
   - **`"published"`** — still run the rest of Published datasource step 1
     (`list-datasources` filtered by this LUID, for `contentUrl`/site/server
     — `get-workbook` doesn't carry those — plus
     `get-datasource-metadata({ datasourceLuid })` for fields, whose
     top-level `datasourceType` should also read `"published"` when present),
     then continue at step 2. Filter candidate fields to `columnClass: "COLUMN"`
     (drop `CALCULATION`/`TABLE_CALCULATION`/`BIN`/`GROUP` — those are
     Tableau-computed groupings with no matching raw column). This metadata
     response often includes an explicit `role` (`"DIMENSION"`/`"MEASURE"`)
     per field — when present, lowercase and use it directly instead of
     inferring from `defaultAggregation`; fall back to that heuristic when
     `role` is absent.

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

Package with `scripts/package_twbx.py`. It hard-fails with a `✗` message if
the workspace isn't packageable; fix what it reports rather than zipping by
hand:

```bash
python3 "$SKILL_DIR/scripts/package_twbx.py" "<App Name>"   # the finalized workspace dir
```

It writes `<App Name>.twbx` next to the workspace dir (pass a second arg to
override), overwriting any existing file, and prints the path for Publish.

> The template these workspaces come from is already publish-valid (`.twb`
> extension wired into a pane, `.trex` with `author email`, `<resources>` block,
> `<icon>`, `min-api-version`). Packaging is the only structural step you own.

## Publish

Uses the MCP publish tools (not available to Slack clients).

1. **Pick the destination.** Omit `projectId` to publish to the caller's
   Personal Space. Include it only if the user names a project, or if the
   tool requires `projectId` or errors that Personal Space is unavailable or
   read-only — then ask the user for a project from
   > list-projects({ capability: "Write" })
   and retry with its `projectId`. If the error says the workbook landed in a
   project instead of Personal Space, tell the user where it went.

2. **Publish.** Pass the `.twbx` path directly:
   > publish-workbook({ workbookFilePath: "<abs path to .twbx>", name: "<App Name>", overwrite: false })

   If the tool errors that `workbookFilePath` isn't supported (staged uploads
   configured), stage the bytes and publish by id:
   > request-workbook-upload({ fileName: "<App Name>.twbx" })   → { workbookUploadId, uploadUrl, requiredHeaders, maxSizeBytes, expiresAt }

   ```bash
   # send every header in requiredHeaders
   curl -fsS -X PUT -H 'Content-Type: <from requiredHeaders>' --data-binary @"<App Name>.twbx" "<uploadUrl>"
   ```

   > publish-workbook({ workbookUploadId: "<id>", name: "<App Name>", overwrite: false })

   Add `projectId` to either call when publishing to a project.

3. **Report the outcome.** On `status: "published"`, save the result JSON
   verbatim to `$WORK/publish.json` and run:

   ```bash
   cat > "$WORK/publish.json" <<'PUBLISH_JSON'
   { …paste the publish-workbook result here… }
   PUBLISH_JSON

   python3 "$SKILL_DIR/scripts/summarize_publish_access.py" "$WORK/publish.json" [--published-datasource ["<name>"]]
   ```

   Pass `--published-datasource` when the app is wired to a published data
   source (the normal case after `wire_datasource.py`, or when reusing one),
   with the descriptor's caption/name as `<name>`. Omit it when no data source
   was wired. Do no extra permission lookups. Relay its stdout to the user
   verbatim.

   If `publish-workbook` returns `status: "invalid"` (or an error), surface the
   `errors`/`warnings` verbatim; common causes trace back to `.twb`/`.trex`
   wiring, not packaging. Set `overwrite: true` only if the user wants to replace
   an existing workbook of the same name.

4. **Promote (optional).** To move a published app into a shared project:
   > move-workbook({ workbookId: "<publish result data.id>", projectId: "<LUID>" })   → { id, name, projectId }

   If `move-workbook` isn't available, tell the user.

## Non-negotiable limits

- Don't zip the `.twbx` freehand. Use `scripts/package_twbx.py` — it keeps
  `.twb` + `Packages/` at the archive root, never nested under `<App Name>/`.
- Don't apply a postUnzip plan freehand. Use `scripts/apply_plan.py` — edits
  before renames, renames deepest-first, verified; see its header comment for
  the full contract.
- Don't hand-edit the `<datasources/>` wiring. Use `scripts/wire_datasource.py` —
  freehand edits mismatch the join key across its coordinated locations or
  leave an empty `<datasources />` anchor, and the app silently reaches no data.
- Don't interpret `publish-workbook` permissions freehand. Use
  `scripts/summarize_publish_access.py` and relay its stdout verbatim.
- Don't assume the scaffold result's zip is already substituted, or skip
  unzip. Whether it arrives as `filePath` or `s3URL`, it's the same static,
  un-substituted template **zip** — unzip it and apply the plan before
  authoring.
- Don't hand off `app.js` to the human unprompted. Authoring `app.js` yourself
  is the fixed default — always write it from the human's stated
  criteria/vibe. Only hand off when the human explicitly says they want to
  write it themselves.

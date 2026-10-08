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
   - **`"published"`** — still run the rest of Published datasource step 1
     (`list-datasources` filtered by this LUID, for `contentUrl`/site/server
     — `get-workbook` doesn't carry those — plus
     `get-datasource-metadata({ datasourceLuid })` for fields), then
     continue at step 2. Filter candidate fields to `columnClass: "COLUMN"`
     (drop `CALCULATION`/`TABLE_CALCULATION`/`BIN`/`GROUP` — those are
     Tableau-computed groupings with no matching raw column). This metadata
     response often includes an explicit `role` (`"DIMENSION"`/`"MEASURE"`)
     per field — when present, lowercase and use it directly instead of
     inferring from `defaultAggregation`; fall back to that heuristic when
     `role` is absent (it isn't always populated). **Caveat, confirmed by
     direct testing:** this dispatch branch — a workbook whose `get-workbook`
     response actually reports `datasourceType: "published"` — could not be
     produced or exercised end-to-end in this environment, and a targeted
     sweep of real site content (multiple independently-authored workbooks,
     different owners/projects) never observed it either — every workbook
     checked, real or synthetic, came back `"embedded"` instead.
     `get-workbook`'s "published" classification appears to require
     server-side provenance from Tableau's own "connect to a published
     datasource" flow, not just a structurally-correct `sqlproxy` connection:
     wiring a fresh app directly at a real published datasource via
     `wire_datasource.py` and publishing it came back from `get-workbook` as
     `datasourceType: "embedded"` with a brand-new LUID (unrelated to the
     original), even though the connection queried real live data correctly.
     A real fixture
     (`tableau-mcp/tests/e2e/fixtures/workbooks/superstore-datasource.twb`)
     shows genuine published connections carry a `derived-from` provenance
     attribute on `repository-location` that `wire_datasource.py` doesn't
     emit; manually adding it to a fresh publish gets a hard `400` from
     `publish-workbook`, confirming it's server-populated, not
     client-authorable. Treat this branch as documented-but-unverified until
     tested against a genuine Desktop/Web-Authoring-connected workbook.

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

> The template these workspaces come from is already publish-valid (`.twb`
> extension wired into a pane, `.trex` with `author email`, `<resources>` block,
> `<icon>`, `min-api-version`). Packaging is the only structural step you own.

## Publish

Uses the MCP publish tools (not available to Slack clients).

1. **Default to the caller's Personal Space — omit `projectId`.**
   `publish-workbook` publishes there automatically when the site supports it
   (falls back to requiring `projectId` otherwise). `projectId` is optional:
   only resolve one if the user names a specific project:
   > list-projects({})
   Pick the project the user wants (ask if ambiguous).

2. **Publish.** Two paths — pick based on transport. Omit `projectId` entirely
   for Personal Space; include it only for a specific project.

   - **Local (stdio), simplest:** the `.twbx` is on the MCP server's own
     filesystem, so pass it directly:
     > publish-workbook({ workbookFilePath: "<abs path to .twbx>", name: "<App Name>", projectId: "<LUID or omit for Personal Space>", overwrite: false })

   - **Remote (http) / staged uploads configured:** stage the bytes first, then
     publish by id:
     > request-workbook-upload({ filename: "<App Name>.twbx" })   → returns an upload URL + workbookUploadId
     > (upload the .twbx bytes to the returned URL — staged-workbook-upload)
     > publish-workbook({ workbookUploadId: "<id>", name: "<App Name>", projectId: "<LUID or omit for Personal Space>", overwrite: false })

3. **Report the outcome.** On success `publish-workbook` returns
   `status: "published"` with the workbook `url` and any `warnings` — give the
   user the confirmation and URL, and surface any warnings. The tool returns
   facts; interpret its permission output here rather than expecting a
   prewritten access message.

   For a project publication with `permissions`, summarize the rules using
   workbook terminology. The relevant capabilities are `Read` (View),
   `Connect` (Full Data Query), and `VizqlDataApiAccess` (API Access):

   - Only when the array is nonempty and **every returned user/group rule**
     explicitly allows all three capabilities, summarize that the returned
     rules grant those workbook permissions. A conflicting entry for any of
     the three capabilities prevents this conclusion.
   - Otherwise, explain that some intended viewers may not be able to view
     the workbook by default, and identify View, Full Data Query, and API
     Access on the published workbook as the permissions to check. Treat a
     missing capability or `Unspecified` as unconfirmed, not as an explicit
     denial. `AIAccess` does not substitute for API Access.

   These are configured rules, not a determination of everyone's effective
   access. Do not infer group membership, guarantee access for every project
   member, or enumerate raw grantee IDs and unrelated capabilities. Empty
   rules do not prove that nobody has access; empty warnings do not prove
   restricted access. Use the publish output and existing task context only;
   do not perform additional permission lookups.

   If `permissionsNote` is returned, surface it and explain that viewer access
   was not verified; the publish itself still succeeded. When both
   `permissions` and `permissionsNote` are absent, show only the publish
   confirmation and link, with no access summary or parent-source reminder.
   Personal Space publications omit these fields.

   After an access summary, use existing parent-source context for the beta
   reminder. For a known published parent, say viewers also need API Access
   on that published data source, naming it when known. If there is no
   published parent, omit the reminder. If parent usage is unknown, qualify
   it: "If this workbook is backed by a published data source, viewers also
   need API Access on that source." Do not look up parent permissions or claim
   they were checked; a successful query by the publisher does not establish
   other viewers' access.

   If it returns `status: "invalid"` (or an error), surface the
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
- Don't hand-edit the `<datasources/>` wiring. Use `scripts/wire_datasource.py` —
  freehand edits mismatch the join key across its coordinated locations or
  leave an empty `<datasources />` anchor, and the app silently reaches no data.
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

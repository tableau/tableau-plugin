---
name: tableau-data-app-authoring
description: Build and publish a Tableau data app, a custom viz-extension web app that queries a published datasource live, or a data file embedded in the workbook. Scaffolds the app with the scaffold-data-app MCP tool, writes its query and visualization from the user's criteria or vibe, then packages it as a .twbx and publishes it. Requires scaffold-data-app, which may be unavailable depending on the user's site role, site settings, or Tableau Server version; don't invoke this skill unless it is available. Use to create, build, vibe-code, or publish a data app. Not for native workbooks or dashboards built from marks, Show Me, or the chart catalog (tableau-workbook-authoring), or for opening existing content, including published data apps (tableau-content-viewer).
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

**Modifying an existing app?** Read every file in its `Resources/.agents/`
first (unzip a `.twbx` to reach it). Those docs hold the app's spec, design,
and past decisions; if `README.md` is the only file, none have been written yet.

**Division of labor: you write ALL the code, every stage, always — including
`app.js`.** The human "vibe codes" by describing what they want (criteria,
theme, vibe, target insights) — they do not write `app.js` themselves. Read
the two bundled guides before authoring: [Design a data app](references/design-data-app.md)
(what to build) and [Build a data app](references/build-data-app.md) (how, using this
skill's local tools). Only skip authoring `app.js` if the human explicitly says
they want to write it themselves for this app (rare) — see the exception at
the end of Author `app.js` below.

**External APIs can come up at any point.** If the user asks for a
third-party API, remote images, or any other outside host, whether at the
start or after the app is already published, run Add external origins
below, then re-package and republish. Read Security best practices first.

There's no separate validation stage — `publish-workbook` is where errors
surface. Get package *layout* right (see Package into a .twbx) or the
workbook won't open at all.

## Preflight requirements

Complete this preflight before designing, scaffolding, coding, or creating
application files.

### Publishing access

This workflow requires the connected Tableau user to have:

- a Creator or Explorer (can publish) site role; and
- permission to publish to the target project.

Do not treat a generic Explorer license as sufficient: the user must have the
Explorer (can publish) site role or equivalent publishing capability.

Use Tableau metadata or permission information already available in the task
when it conclusively establishes publishing access. If the user's site role or
publishing access cannot be determined through the available Tableau tools,
ask the user to confirm that they have Creator or Explorer (can publish) and
permission to publish to the target project.

Do not begin substantive data-app work while this prerequisite remains
unconfirmed.

### Required Tableau MCP capabilities

Before beginning substantive work, verify that all of the following are
callable:

- `scaffold-data-app`;
- `publish-workbook`;
- `request-workbook-upload`

Interactive rendering is not required. It's the recommended way to verify the
published app with the user, but never block on it: when it isn't available,
open the published app in an embedded browser if you have one available or
encourage the user to open and verify it in their own browser instead.

When the app will use a published datasource, also verify that the tools needed
to resolve that datasource and inspect its metadata are callable.

A capability is not unavailable merely because it has not yet been loaded.
Perform one focused availability lookup for a missing capability when
necessary.

If `scaffold-data-app` is unavailable, stop and report the missing capability.
Do not hand-build or substitute for its scaffold.

If any other required capability is unavailable, stop before scaffolding or
authoring and tell the user exactly which capability is missing and why it
prevents completion. Do not create an unpublished data app while presenting
it as completion.

## Scaffold and finalize the workspace

Call the `scaffold-data-app` MCP tool with the app name:

> scaffold-data-app({ datappName: "Sales Demo" })

The preflight must establish that `scaffold-data-app` is callable. If the tool
is present but the scaffold call fails, report the error and stop. Do not
hand-build the template or substitute another scaffold.

The result carries an un-substituted template **zip** plus a `postUnzip` plan.
The zip arrives one of three ways — branch on whichever field is present;
past the fetch step the steps are identical:

- `downloadUrl` — a short-lived blob-storage link (newer servers).
- `s3URL` — the same thing on older servers.
- `filePath` — the zip already on local disk (no blob storage); skip the
  download.

A `downloadUrl`/`s3URL` link expires about 60 seconds after the call, so
download it **immediately**, before doing anything else. If the download fails
with an expired-link error, call `scaffold-data-app` again for a fresh link.

The result also carries:

- `wiring` (newer servers) — `server`, `site`, `channel`, and `port` for the
  Tableau site this session is signed in to. Keep it: Wire a datasource in
  copies these into every datasource descriptor. Older servers omit it.
- `allowedOrigins: string[]` — the external origins the site lets data apps
  reach. May be empty, in which case the app can't fetch any external origin.
- `requestedOrigins` — which file declares the origins the app requests
  (`file`) and how to write them (`instructions`). Every origin you put there
  must also appear in `allowedOrigins`; see External origins below.

Apply the plan deterministically with the bundled script — applying it freehand
leaves half-replaced `TODO-MANIFEST-ID` / `TODO App Name` / `TODO Sheet Name` tokens or interleaves
edits and renames in the wrong order.

Finalize the plan (fetch, save, apply). Fetch first — the link expires. Scripts
referenced below live under `scripts/`, relative to this skill directory
(`$SKILL_DIR`):

1. Fetch the template — with `downloadUrl` (or `s3URL` on older servers),
   download right away, then unzip:

   ```bash
   SKILL_DIR="<absolute path to this skill directory>"
   WORK="$(mktemp -d -t dataapp)"

   curl -fsSL "<downloadUrl or s3URL>" -o "$WORK/template.zip"
   mkdir -p "$WORK/unzipped"
   unzip -q "$WORK/template.zip" -d "$WORK/unzipped"
   ```

   With `filePath`, skip the download and unzip only:

   ```bash
   SKILL_DIR="<absolute path to this skill directory>"
   WORK="$(mktemp -d -t dataapp)"

   mkdir -p "$WORK/unzipped"
   unzip -q "<filePath>" -d "$WORK/unzipped"
   ```

2. Save the plan:

   ```bash
   # Save the postUnzip object verbatim (do NOT reformat — find tokens must match byte-for-byte)
   cat > "$WORK/plan.json" <<'PLAN_JSON'
   { …paste the result's postUnzip object here… }
   PLAN_JSON
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
    manifest.json           ← requestedOrigins lives here
    extensions/data-app.trex
    content/index.html
    content/src/app.js      ← the authoring surface
    content/src/styles.css
    content/src/tableau.extensions.1.latest.min.js
  Data/.gitkeep             ← placeholder; embedded datasource files go here
  Resources/.agents/README.md   ← which agent docs travel with the workbook
```

**Sheet name:** the worksheet is named after the app's display name. It's a
plain string with no hash/join-key involved, so it's freely hand-editable at
any point before packaging — edit all 3 matching locations in the `.twb` to
the same new value: the `<worksheet name='...'>` tag, the `<window class='worksheet'
name='...'>` tag, and `<referenced-view ... viewId='...' />`.

### External origins

The extension sandbox blocks every external origin the package doesn't
declare. To let the app reach one (an API, an image host), declare it in the
file named by the scaffold result's `requestedOrigins.file`, in the format its
`requestedOrigins.instructions` gives. Every origin you request must also
appear in the result's `allowedOrigins` — the site blocks any other origin even
when the manifest requests it. If `allowedOrigins` is empty, the app can't
fetch any external origin: tell the user the site admin must allow the origin
first, or design the app without it. Don't request origins the app doesn't
use.

## Wire a datasource in

The scaffolded `.twb` ships an **empty `<datasources/>`** (both at the workbook
root and inside the worksheet `<view>`). At runtime the app calls
`getAllDataSourcesAsync()` and finds nothing → it renders **"no data source found
in the workbook."** To query live data the workbook must have a real datasource
wired in — this stage is a prerequisite for a working app.

Do this once the user has told you what to connect to; it is skippable if the
user only wants to publish the starter to prove packaging. Only add, remove, or
swap datasources the user asked for; if you think a different or extra
datasource would help, ask first.

The app queries either kind of datasource, in any mix:

- **Published:** a datasource that already exists on the server (a `sqlproxy`
  connection, resolved live by VDS). Its identity can come straight from the
  user, or be reused from a datasource already wired into some other existing
  workbook (see Reuse an existing workbook's datasource below).
- **Embedded file:** a data file the user supplies, copied into
  the workspace's `Data/` folder and packed into the `.twbx` (see Embedded
  file datasource below).

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
   contentUrl) and `get-datasource-metadata({ datasourceLuid })`
   (field names + datatypes). The published DS **contentUrl** is the
   `repositoryId`. (To reuse an existing workbook's datasource instead, see
   Reuse an existing workbook's datasource below — it gets you here, then
   continues at step 2.)

   **Server, site, channel, and port come from the scaffold result's
   `wiring`.** Copy `wiring.server`, `wiring.site`, `wiring.channel`, and
   `wiring.port` verbatim into every descriptor. Don't guess them, parse them
   out of a URL, or ask the user. `wiring.site` is `""` for the Default site —
   keep it empty, don't substitute a name.

   **Older servers return no `wiring`.** Then use the server host and site from
   `list-datasources` as before, with `"channel": "https", "port": 443`. If they
   aren't there either, ask the user for the server host and site. Never invent
   them.
2. **Write a descriptor** listing *only the fields the app will query* (name +
   datatype + role). One datasource:

   ```bash
   cat > "$WORK/descriptor.json" <<'DS_JSON'
   {
     "caption": "<Friendly Name>",
     "repositoryId": "<published DS contentUrl>",
     "site": "<wiring.site>",
     "server": "<wiring.server>",
     "channel": "<wiring.channel>", "port": <wiring.port>,
     "fields": [
       { "name": "Profit", "datatype": "real",   "role": "measure"   },
       { "name": "Region", "datatype": "string", "role": "dimension" }
     ]
   }
   DS_JSON
   ```

   Several datasources (any number) go in a `datasources` array, **primary
   first**, with nothing else at the top level; each entry has the same shape
   as the single-datasource object:

   ```json
   { "datasources": [ { "caption": "Orders", "...": "..." },
                      { "caption": "People", "...": "..." } ] }
   ```

   The primary is the sheet's main datasource. The app reaches every one by
   caption via `getAllDataSourcesAsync()` — look each up by `name`, never by
   position (the list isn't returned in wiring order).

   Captions must be distinct. A caption is only this workbook's display name;
   the server matches the published datasource by `repositoryId`, so if two
   published datasources share a name, give them different captions here
   (e.g. "Sales Orders" / "Finance Orders") rather than renaming them on the
   server.

3. **Run the wiring script** (it prints the wired `.twb` path, and generates a
   consistent `sqlproxy.<hash>` unless you supply `connectionName`):

   ```bash
   python3 "$SKILL_DIR/scripts/wire_datasource.py" "<App Name>/<App Name>.twb" "$WORK/descriptor.json"
   ```

The script hard-fails if the `.twb` is already wired (re-scaffold, keep your `app.js`),
if an anchor is missing (template drifted),
if any empty `<datasources />` survives, if a join key is missing from where the server
reads it (including the host sheet's view listing every datasource), or
if a `repositoryId`, `caption`, or `connectionName` repeats across datasources.
Trust that failure over patching the XML by hand. `datatype` maps to the column
`type` (`real`/`integer` → quantitative, `date`/`datetime` → ordinal, else
nominal); `role: "measure"` gets a `Sum` aggregation, `dimension` a `Count`.

**Embedded file datasource:** use this when the user hands you a data file
instead of naming a published datasource. The same script wires it (and rejects
file types it can't); the descriptor just has `"type": "file"`.

1. **Copy the file into the workspace** under `Data/`, conventionally
   `Data/Datasources/<file>`. The script fails if the file isn't there, or if
   its path is outside `Data/`.
2. **Write a descriptor.** `file` is the path relative to the `.twb`. `table`
   picks the table in a file that holds several (an Excel sheet); the script
   says when it's needed. Field names must match the column names Tableau reads
   from the file, usually its header row. No server, site, or `repositoryId`:

   ```bash
   cat > "$WORK/descriptor.json" <<'DS_JSON'
   {
     "type": "file",
     "caption": "Sample - Superstore",
     "file": "Data/Datasources/Sample - Superstore.xls",
     "table": "Orders",
     "fields": [
       { "name": "Sales",  "datatype": "real",   "role": "measure"   },
       { "name": "Region", "datatype": "string", "role": "dimension" }
     ]
   }
   DS_JSON
   ```

   To mix it with published datasources, put every entry in one
   `datasources` array (primary first) as above.
3. **Run the wiring script** the same way as for a published datasource.

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
   - **`"embedded"`**: its data lives inside that workbook, so it can't be
     reused by reference. Ask the user for either a published datasource or
     the source data file, and wire the file as an Embedded file
     datasource above.
   - **`"published"`** — still run the rest of Published datasource step 1
     (`list-datasources` filtered by this LUID, for `contentUrl` — and
     site/server only when the scaffold result had no `wiring`;
     `get-workbook` doesn't carry those — plus
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

**Record context in `Resources/.agents/`** when it would help whoever edits the
app next: `spec.md` (what it does, for whom), `design.md` (datasources, queries,
chart choices), `memories.md` (decisions, gotchas, the user's preferences).
Update them when you change the app. Follow the folder's `README.md`: no
secrets, tokens, or personal data (anyone who can download the workbook can
read them), and never put these docs under `Packages/<id>/content/`.

**Exception — the human wants to write `app.js` themselves:** only skip
authoring if the human explicitly says they want to write `app.js` themselves
for this app — an override of the default, not the norm. Stop and hand off:
tell them the workspace path
(`Packages/com.tableau.mcp.<slug>/content/src/app.js`) and point them at
[Design a data app](references/design-data-app.md) and
[Build a data app](references/build-data-app.md) as their own reference.
Resume at Package into a .twbx once they say it's authored.

## Add external origins (any time)

Run this whenever the app needs to reach a host outside its package: the user
asks for an external API (at the start of the session or after the app is
published), or `app.js` calls one. The rules behind these steps (two-part
allowlisting, origin format, CORS) live in
[Calling external APIs](references/external-apis.md).

1. **Get a fresh site allow-list.** Call `scaffold-data-app` again with the
   app's name and use only its `allowedOrigins`; ignore the zip and plan. The
   list from the start of the session may be stale. Save it:

   ```bash
   cat > "$WORK/allowed.json" <<'ALLOWED_JSON'
   [ …paste the allowedOrigins array here… ]
   ALLOWED_JSON
   ```

2. **Check every origin you need is on it.** If one isn't, stop and tell the
   user: a site admin has to add it under Settings > Extensions > Extension
   Package Allowed Origins. Don't work around it.

3. **Declare the origins in the package:**

   ```bash
   python3 "$SKILL_DIR/scripts/declare_origins.py" "<App Name>" --allowed "$WORK/allowed.json" \
     --add https://api.example.com https://auth.example.com
   ```

   It writes `requestedOrigins` into `Packages/<package id>/manifest.json`,
   merges with origins already declared, and fails if an origin isn't on the
   allow-list or isn't a plain `https` origin. Use `--list` to see what's
   declared and `--remove` to drop an origin the app no longer uses.

4. **Re-package and republish** (Package into a .twbx, then Publish with
   `overwrite: true` if the app is already published). The new policy takes
   effect only after republishing.

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

It also packs `Data/` and `Resources/.agents/` at the archive root. Under
`Data/`, only the files the `.twb` references are packed. Hidden files are
never packed.

It writes `<App Name>.twbx` next to the workspace dir (pass a second arg to
override), overwriting any existing file, and prints the path for Publish.
It also prints `⚠` warnings for problems that only show up at runtime:
undeclared external origins, dotfiles, package-relative `fetch()`, and
secret-looking keys. They don't stop packaging, but fix them or tell the user
about them before publishing.

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

   python3 "$SKILL_DIR/scripts/summarize_publish_access.py" "$WORK/publish.json" [--published-datasource ["<name>"]]...
   ```

   Pass `--published-datasource` when the app is wired to a published data
   source (the normal case after `wire_datasource.py`, or when reusing one),
   with its published name from `list-datasources` as `<name>` (not the
   descriptor's caption, which can differ). Repeat it once per wired data
   source. Omit it for embedded file datasources and when no data source was
   wired. Do no extra permission lookups. Relay its stdout to the user
   verbatim.

   If `publish-workbook` returns `status: "invalid"` (or an error), surface the
   `errors`/`warnings` verbatim; common causes trace back to `.twb`/`.trex`
   wiring, not packaging. Set `overwrite: true` only if the user wants to replace
   an existing workbook of the same name.

4. **Promote (optional).** To move a published app into a shared project:
   > move-workbook({ workbookId: "<publish result data.id>", projectId: "<LUID>" })   → { id, name, projectId }

   If `move-workbook` isn't available, tell the user.

## Limitations and gotchas

### Multiple datasources

`wire_datasource.py` wires any number of published datasources, with these
constraints:

- **One run, all at once.** List every datasource in the descriptor's
  `datasources` array, primary first. The script refuses an already-wired
  `.twb`, so adding a datasource later means re-scaffolding, copying
  `content/src/app.js` into the new workspace, and wiring the full set again.
- **What gets wired.** Each datasource gets its own root `<datasource>` and its
  own `sqlproxy.<hash>` join key (unique across the set), and all of them are
  listed on the host sheet's `<view>` — the server only connects datasources
  listed there. Only the primary gets `datasource-dependencies`; the others are
  reached through `getAllDataSourcesAsync()`.
- **Distinct identities.** `caption`, `repositoryId`, and `connectionName` must
  each be unique across the set, or the script hard-fails. Captions matter
  most: they are how `app.js` finds each datasource.
- **Find by name in `app.js`, never by position.** `getAllDataSourcesAsync()`
  doesn't return datasources in wiring order. The starter's `pickDataSource()`
  takes `list[0]`, so a multi-datasource app must replace it with a lookup by
  `ds.name` (the caption).
- **No blending or joins.** Query each datasource separately with its own
  `queryAsync()` and combine the rows in `app.js`. Don't add blend or
  relationship XML.

### External origins and package hosting

Read [Calling external APIs](references/external-apis.md) before building
anything that leaves the package: it covers what the sandbox blocks no matter
what, allowlisting, CORS, and how to debug a blocked call. What the package
host serves is in [Build a data app](references/build-data-app.md), Sandbox and
lifecycle rules. `package_twbx.py` warns about undeclared origins, unserved
files, and package-relative `fetch()`.

## Security best practices

- **Prefer network-isolated apps.** Build the app so it talks only to Tableau
  through the Extensions API. Every external origin needs a site admin's
  approval and gives data a path out of Tableau. Before adding one, ask whether
  the feature needs it, and tell the user what data would leave Tableau.
- **Keep secrets and credentials out of the package.** Anything in `content/`
  (API keys, client secrets, refresh tokens) can be read by anyone who can
  open or download the workbook. If the user still wants one embedded (e.g. a
  personal demo), tell them that first, keep the workbook out of shared
  projects, and keep the secret out of git. Expect the agent's safety checks
  to ask for explicit approval before publishing or downloading a workbook
  that contains credentials. `package_twbx.py` warns about secret-looking keys.
- **Avoid hardcoding data where possible.** Query the datasource live with
  `queryAsync()` instead of copying rows into `app.js` or a bundled file. If
  data must be hardcoded, tell the user the implications first: it's a
  snapshot that won't refresh, and Tableau's query-time protections, such as
  row-level security policies and user filters, don't apply to it, so every
  viewer sees all of it.

## Non-negotiable limits

- Don't zip the `.twbx` freehand. Use `scripts/package_twbx.py` — it keeps
  `.twb`, `Packages/`, and any `Data/`/`Resources/.agents/` at the archive root, never
  nested under `<App Name>/`.
- Don't apply a postUnzip plan freehand. Use `scripts/apply_plan.py` — edits
  before renames, renames deepest-first, verified; see its header comment for
  the full contract.
- Don't hand-edit the `<datasources/>` wiring. Use `scripts/wire_datasource.py` —
  freehand edits mismatch the join key across its coordinated locations or
  leave an empty `<datasources />` anchor, and the app silently reaches no data.
- Don't hand-edit `manifest.json` to allow external origins. Use
  `scripts/declare_origins.py` — Tableau ignores an array or an
  `allowedOrigins` key without any error, and the app stays blocked.
- Don't interpret `publish-workbook` permissions freehand. Use
  `scripts/summarize_publish_access.py` and relay its stdout verbatim.
- Don't assume the scaffold result's zip is already substituted, or skip
  unzip. Whether it arrives as `downloadUrl`, `s3URL`, or `filePath`, it's the
  same static, un-substituted template **zip** — unzip it and apply the plan
  before authoring.
- Don't guess a descriptor's `server`, `site`, `channel`, or `port`. Copy them
  from the scaffold result's `wiring`; without `wiring`, use `list-datasources`
  or ask the user.
- Don't hand off `app.js` to the human unprompted. Authoring `app.js` yourself
  is the fixed default — always write it from the human's stated
  criteria/vibe. Only hand off when the human explicitly says they want to
  write it themselves.

# Build a data app — the HOW (workflow + mechanics)

> The **HOW** layer of authoring, adapted for this skill's local MCP tools. Read
> [design-data-app.md](design-data-app.md) first for **WHAT** to build. This file owns the workflow;
> the in-code mechanics (sandbox rules, VDS query shape, safe DOM, Vega-Lite-local) are owned by the
> `AUTHOR YOUR APP HERE` comment block in the scaffolded `content/src/app.js` — follow it there, this
> file only points at it.

## Live-query model (read this first)

**The data app queries its datasource live via the Tableau Extensions API — there is NO embedded data
snapshot.** The shipped app calls `readMetadataAsync()` / `queryAsync()` at view time against the
published datasource, so it always reflects current data. Two consequences:

1. **The app reaches datasources through the workbook, and queries them directly.** It is a viz
   extension hosted on a worksheet, so it uses
   `tableau.extensions.workbook.getAllDataSourcesAsync()` to reach every datasource wired into the
   workbook, then calls `ds.readMetadataAsync()` / `ds.queryAsync(query)`. It does **not** read
   marks-card summary data and the host worksheet declares **no encodings** — the app builds its own
   VDS query. Results come back in the standard VizQL Data Service shape `{ data: [...] }`; the
   starter's `extractData()` helper reads `result.data` — use it, and match columns by field name
   (not position).
   - **Prerequisite:** the workbook must actually have that datasource wired in. Our name-only
     `scaffold-data-app` ships an **empty `<datasources/>`**, so a freshly scaffolded workbook
     reaches *nothing* at runtime and renders "no data source found." **The SKILL's 'Wire a
     datasource in' stage wires the datasource into the `.twb`** — do that before authoring, or the
     live query has no target.
2. **You cannot run the live query yourself.** A live query only executes inside the Tableau host, so
   you cannot see real rows until the app is published and opened in Tableau. While authoring,
   introspect the datasource with `get-datasource-metadata` / `query-datasource` to design and
   sanity-check the query; do the **visual** review in Tableau **after** publishing. (For an
   **embedded (CSV or Excel)** datasource, this introspection itself requires one publish first — there's no LUID
   to query until the workbook exists on the server; see Workflow step 3 below.)

## Workflow

1. **Detect intent.** Author a real app (beyond the starter) when the user asks to "chart",
   "visualize", "build a dashboard", or otherwise wants a live visual over a specific published
   datasource. Skip it when the answer is a single-value lookup or text and the user hasn't signaled
   interest in a reusable visual — then the starter handoff (the SKILL's 'Author `app.js`' default)
   is enough.
2. **Identify the datasource(s).**
   - **Published:** find the target published datasource and its LUID with `list-datasources` (ask
     the user which one if ambiguous). You can wire more than one if the app genuinely needs it. This
     LUID drives both the 'Wire a datasource in' `.twb` wiring and your introspection queries.
   - **Embedded (CSV or Excel):** `list-datasources` only sees published datasources — an embedded one has no
     LUID until the workbook is published. Wire the file in first ('Wire a datasource in'), then get a
     queryable LUID for it per the Embedded case in step 3 below.
3. **Introspect the datasource before writing `app.js`.**
   - **Published:**
     - `get-datasource-metadata({ datasourceLuid })` → fields, data model, parameters. This is the
       field list the app will match by name.
     - `query-datasource({ datasourceLuid, query, limit })` → preview real VDS `{ data: [...] }` rows
       so you can sanity-check the exact query the app will run before you commit to a chart. Match
       columns by field caption/name, not by position.
   - **Embedded (CSV or Excel):** there's no MCP tool that queries an embedded datasource straight from the
     wired `.twb` — it only gets a queryable LUID once the workbook is published. This still counts
     as the SKILL's "ask explicitly before publishing" gate below — it creates content on the user's
     site just like the final publish does, so get a clear yes before doing it, same as any other
     publish. Once you have it, after 'Wire a datasource in' has wired the file, publish the workbook
     as-is (a stub `app.js` is fine; you don't need the real chart written yet):
     1. `publish-workbook(...)` to get a `workbookId`.
     2. `get-workbook({ workbookId })` — its `upstreamDatasources` now includes the embedded entry
        (`datasourceType: 'embedded'`) with a queryable `luid` and a `queryability: { isQueryable,
        reason? }` flag. `isQueryable: false` usually means the site has embedded-datasource querying
        disabled — surface `reason` rather than guessing why the next step fails.
     3. `query-datasource({ datasourceLuid: <that luid>, query, limit })` — same call shape as a
        published datasource, previewing real rows before you write the real chart logic.
     - **Don't assume the CSV's raw text survives the wire unchanged.** VDS can reformat values
       independent of the wiring script's inferred datatype — e.g. a column wired as plain `string`
       because its values look like `7/22/2024` can still come back from a live query as an ISO
       timestamp (`"2024-09-30T00:00:00"`), not the original text. Confirm the *actual* shape via this
       preview query — especially for anything date/time-shaped — before writing parsing logic in
       `app.js` against an assumed format.
4. **Author `content/src/app.js`** — see Author `app.js` below.
5. **Package** the workspace into a flat `.twbx` per the SKILL's 'Package into a .twbx' stage
   (`.twb` + `Packages/` at the archive root; `unzip -l` to confirm; no `.DS_Store`/`__MACOSX`).
   There is **no separate validation tool and no local preview** — a `.twbx` cannot be pre-validated;
   Tableau validates at publish time.
6. **Ask explicitly before publishing.** Never auto-publish. Ask, in plain language, whether the
   user wants this app published — publishing creates content on their Tableau site, and that is
   their decision. "Looks good" is not consent to publish; get a clear yes to publishing
   specifically. If there is no clear yes, stop.
7. **Publish** on an explicit yes, with `publish-workbook` (via `list-projects` for the target
   project LUID). Surface the returned canonical `url` verbatim and report any warnings.
   `publish-workbook` surfaces any structural/extension errors at this point (it is where validation
   effectively happens).
8. **Review the live app in Tableau** — see Review the live app in Tableau below.

## Author `app.js`

There is no upsert tool — **edit the file on disk.** Inside the `AUTHOR YOUR APP HERE` block, replace
the `renderStarter(...)` call with the real flow:

- Build a VDS query (fields + optional filters/aggregations) and call `ds.queryAsync(query)`.
- Read rows with the provided `extractData()` helper (returns `result.data`); match columns by field
  name.
- Render with **hand-rolled inline SVG/Canvas** (`document.createElementNS`, manual mark
  positioning) — no vendored charting library. Confirmed 2026-09-28: vendoring the
  Vega/Vega-Lite/Vega-Embed stack (~830KB across 3 files) broke live extension loading
  ("Extensions API not loaded"); a sibling app with zero vendored library loaded fine.
  Mechanism unconfirmed — treat vendoring a large third-party charting library as a known
  way to break the live load.

Prefer to derive new fields / change data shapes **at query time** rather than in JS. There is no
required file layout, chart count, or palette — a good app clearly addresses the user's objective.
See [design-data-app.md](design-data-app.md) for encoding, narrative, integrity, and color.

## Sandbox and lifecycle rules

The published app runs inside the Tableau viz-extension sandbox, not a browser. The authoritative
rules live in the `AUTHOR YOUR APP HERE` comment in the scaffolded `app.js` and are **not restated
here** to avoid drift. In brief, that comment requires: surface every error on-screen (no visible
console — use the starter's `renderError`); render first / initialize second; **vendor libraries
locally, no CDN** (mirroring how `tableau.extensions.1.latest.js` is already vendored and loaded
before `app.js`) — but keep the vendored payload small; a ~830KB Vega/Vega-Lite/Vega-Embed vendor
broke live loading (see Author `app.js` above), so prefer hand-rolled SVG/Canvas over pulling in a
large charting library; prefer 2D (SVG/Canvas/DOM) over WebGL; use safe DOM APIs
(`textContent` / `createElement`), never `innerHTML` with live values.

## Review the live app in Tableau

There is **no local preview** — the live query only runs inside Tableau. Open the published workbook
(the user's personal space is the natural iteration target) and confirm the viz-extension worksheet
renders the real chart — not "no data source found" ('Wire a datasource in' wiring missing) or "Live
query unavailable" (query/render error). A one-time extension trust prompt on first load is expected,
not a failure. Apply the design checks in [design-data-app.md](design-data-app.md) (5-second +
takeaway test). To iterate: edit `app.js` (Author `app.js`), re-package (Workflow step 5), republish
(Workflow steps 6–7).

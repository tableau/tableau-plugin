# Spec: `request-datasource-upload` + `publish-datasource` (Tableau MCP)

Status: draft, 2026-10-09
Target repo: `tableau-mcp` (`src/tools/web/datasources/`)
Consumer: `prepare-and-publish-hyper-extract` skill (tableau-plugin), then `tableau-data-app-authoring`

## Why

The `prepare-and-publish-hyper-extract` skill builds a `.hyper` and a `.tds`, then packages them as a
`.tdsx`. Today nothing in Tableau MCP can publish that file. Publishing from Python would need its own
sign-in (a PAT), because the MCP's OAuth session isn't available outside the MCP. That's a second
credential for every user, including external ones. Publishing through MCP reuses the session the user
already has.

The TDS Edit API (REST 3.30) doesn't fill this gap. It only edits a data source that's already
published, and it needs Tableau+ or the Data Management add-on.

## Shape: two tools, mirroring the workbook pair

Hosted clients can't pass a local path to a remote MCP server, so publishing workbooks takes two steps.
Data sources should do the same, for the same reason:

1. `request-datasource-upload({ fileName })` returns a presigned S3 PUT URL.
2. The client uploads the bytes (`curl -T`), outside the MCP context.
3. `publish-datasource({ datasourceUploadId, ... })` streams the staged bytes into a Tableau
   `fileUploads` session and publishes the data source.

Local MCP servers (no S3 configured) accept `datasourceFilePath`, the same way `publish-workbook`
accepts `workbookFilePath`.

**Alternative considered:** one generic `request-content-upload({ fileName, contentType })` shared by
both publish tools. That's cleaner long-term, but it changes the workbook tool's contract. Keep the
tools separate and share the internals instead (see Implementation).

## Tool 1: `request-datasource-upload`

| | |
|---|---|
| Group | `authoring` |
| Feature gate | `authoring-tools`; disabled for Slack clients (same as the workbook tools) |
| Min role | `CREATOR` (see Open question 1) |
| MCP scope | `tableau:mcp:datasource:create` (new) |
| API scopes | none, because it only touches S3 |
| Annotations | `readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true` |
| Passthrough auth | Rejected, same as `request-workbook-upload` |

**Params**

```ts
fileName: z.string().min(1)
  .describe('Name of the data source file to upload. Must end in .tdsx or .hyper.')
```

**Result:** same shape as `RequestWorkbookUploadResult`:

```ts
{ datasourceUploadId: string; uploadUrl: string; expiresAt: string;
  maxSizeBytes: number; requiredHeaders: Record<string, string> }
```

S3 key: `{keyPrefix}datasource-uploads/{uuid}/datasource.{tdsx|hyper}`. Content-Type is
`application/octet-stream` for both file types.

## Tool 2: `publish-datasource`

| | |
|---|---|
| Group | `authoring` |
| Feature gate | `authoring-tools`; disabled for Slack clients |
| Min role | `CREATOR` (see Open question 1) |
| MCP scope | `tableau:mcp:datasource:create` (new) |
| API scopes | `tableau:datasources:create`, `tableau:file_uploads:create` |
| Optional scope | `tableau:permissions:read`, for the permissions read after publishing (separate session, same pattern as `PUBLISH_WORKBOOK_PERMISSIONS_API_SCOPE`) |
| Annotations | `readOnlyHint: false, destructiveHint: true` (because `overwrite` replaces content), `idempotentHint: false, openWorldHint: true` |

**Params**

```ts
datasourceUploadId: z.string().min(1).optional()
  .describe('Staged upload id from request-datasource-upload. Use for hosted clients.'),
datasourceFilePath: z.string().min(1).optional()
  .describe('Path to a local .tdsx or .hyper on the MCP server filesystem. Only when S3 staging is not configured. A bare .hyper must contain exactly one table; send multi-table models as .tdsx.'),
name: z.string().min(1)
  .describe('Name of the published data source.'),
projectId: z.string().min(1)
  .describe('Project LUID to publish into (use list-projects). Required: data sources cannot be published to Personal Space.'),
description: z.string().optional()
  .describe('Optional data source description.'),
overwrite: z.boolean().default(false)
  .describe('Replace an existing data source with the same name in the project. Defaults to false.'),
```

Deliberately left out of v1:
- **`.tds` (live connection).** It would need connection credentials in the publish payload, and
  credentials must not pass through the agent. The skill's output is always an extract.
- **`append`.** The skill builds the data once; refresh is out of scope.
- **`connectionCredentials`, `useRemoteQueryAgent`, tags.** Not needed for extracts.

**Behavior**

1. Validate inputs. Exactly one of `datasourceUploadId` or `datasourceFilePath`, with the same rules
   and error text as `resolveWorkbookInput`. The extension must be `.tdsx` or `.hyper`.
2. Run `assertProjectAllowedByBoundedContext(projectId, boundedContext)`.
   Then look up `name` in `projectId`. If it exists and `overwrite=false`, fail now, before
   uploading. An async publish would only report a silent job failure. If it exists and
   `overwrite=true`, set `overwritten: true`. The LUID is preserved.
3. Resolve the bytes. **Stream** from S3 into `fileUploads` in 64 MB chunks, instead of loading the
   whole object into a `Buffer` the way `resolveStagedWorkbookUpload` does. Extracts are routinely
   hundreds of MB (the reference WAM extract is 373 MB), and the staging limit is 5 GB. Buffering that
   much on a shared hosted server isn't safe.
4. `POST /sites/{siteId}/datasources?uploadSessionId={id}&datasourceType={tdsx|hyper}&overwrite={bool}&asJob=true`
   with the payload
   `<tsRequest><datasource name="…" description="…"><project id="…"/></datasource></tsRequest>`.
5. **Async publish.** Large extracts can take longer than an HTTP request allows, so use `asJob=true`
   and poll the job (`GET /sites/{siteId}/jobs/{jobId}`) with backoff, up to a configurable limit
   (default 120 s).
   - If the job succeeds, look up the data source (step 6).
   - If the job fails, return its error notes.
   - If the limit runs out, return `status: 'pending'` with the `jobId`. The skill can poll
     with `list-jobs` and resolve the data source by name + project.
6. Look up the published data source (`GET /sites/{siteId}/datasources?filter=name:eq:…,projectName…`,
   or by the LUID if the job result includes one) to get `id`, `contentUrl`, `project`, `webpageUrl`.
7. After the publish session signs out, read the data source's permission rules on a separate session.
   This is best-effort, with a `permissionsNote` on failure, mirroring `publish-workbook`. The data-app
   skill's `summarize_publish_access.py` already consumes this shape.

**Result**

```ts
type PublishDatasourceResult =
  | {
      status: 'published';
      datasource: {
        id: string;            // LUID → data-app wiring + get-datasource-metadata
        name: string;
        contentUrl: string;    // → data-app descriptor `repositoryId`
        project: { id: string; name: string };
        webpageUrl?: string;
      };
      server: string;          // config.server
      siteContentUrl: string;  // extra.getSiteName()
      overwritten: boolean;
      permissions?: GranteeCapability[];
      permissionsNote?: string;
      boundedContextNote?: string; // see below
    }
  | { status: 'pending'; jobId: string; name: string; projectId: string }
  | { status: 'failed'; jobId?: string; message: string };
```

**Bounded context note.** If `boundedContext.datasourceIds` is set, the new LUID won't be in it.
`query-datasource` and `get-datasource-metadata` would then reject the data source the user just
published. Don't change the allow-list. Instead, set `boundedContextNote` to explain that the operator
must add the LUID before the data app can query it. The skill shows that note to the user.

**Errors** (each maps to an existing `McpToolError` subclass)

| Condition | Error |
|---|---|
| Both or neither input given; wrong extension; empty file | `ArgsValidationError` |
| `projectId` outside the bounded context | existing bounded-context error |
| Name exists and `overwrite=false` | `ArgsValidationError` with the hint "pass overwrite: true or choose another name". Detect it with a **pre-publish lookup** by name + project. The server returns **HTTP 403, code `403007`** (not 409) on a synchronous publish. On `asJob=true` the job just fails with `finishCode: 1` and empty notes. |
| Publish permission denied on the project (403, any code other than `403007`) | Tableau error passed through, with a "use list-projects to find a project you can publish to" hint |
| Extract rejected by the server (bad `.tdsx`/`.hyper`) | `status: 'failed'` with the server's message, sanitized like `sanitizeFindingText` |
| S3 not configured / Passthrough auth | same messages as the workbook tools |

## Implementation notes

- **Generalize staging.** Rename `workbooks/stagedWorkbookUpload.ts` → `web/stagedUpload.ts`,
  parameterized by `{ prefixSegment, fileTypes, contentTypeFor }`. Keep the workbook exports as thin
  wrappers so `request-workbook-upload` and `publish-workbook` don't change.
- **Streaming chunks.** Add `uploadStreamInChunks({ siteId, filename, stream })` to
  `PublishingMethods`, next to `uploadFileInChunks`. Read 64 MB at a time from the S3 `GetObject` body,
  or from `fs.createReadStream` for local paths. Both input modes then share one code path.
- **SDK.** Add `publishDatasource`, `getJob` (if `jobsMethods` lacks it) and
  `queryDatasourcePermissions` to the datasources/jobs methods, plus endpoints in `datasourcesApi.ts`.
- **Wiring.** Add both names to `webToolNames` and `webToolGroups.authoring` in `toolName.ts`.
  Register in `tools.ts`. Add scope entries in `server/oauth/scopes.ts` (new
  `PUBLISH_DATASOURCE_API_SCOPES`). Add both to the `authoringToolsEnabled` deletion block (~line 588).
- **Logging.** Redact `datasourceUploadId` and `datasourceFilePath` in `logAndExecute` args, as
  `publish-workbook` does.

## Tests

Mirror `publishWorkbook.test.ts` / `requestWorkbookUpload.test.ts`:

- Input validation: both, neither, wrong extension, empty file, S3 enabled + local path.
- Bounded context: project rejected; `boundedContextNote` set when `datasourceIds` is restricted.
- Chunking: a 150 MB stream produces 3 appends with ≤ 64 MB each, in order.
- Job polling: success → lookup; failure → `failed`; timeout → `pending` with `jobId`.
- `overwrite=false` + 409 → hint message. `overwrite=true` → `overwritten: true`.
- Permissions read fails → `permissionsNote`, publish still succeeds.
- Tool is disabled when `authoring-tools` is off and for Slack clients.

## Prototype results (2026-10-09, test-dataplane1 / tableauagent1, REST 3.31)

Script: `prototypes/publish-datasource/publish_datasource.py`. It's stdlib only and runs the exact
sequence this spec describes.

1. **A Desktop-authored multi-table `.tdsx` publishes intact through REST.** Zach's WAM `.tdsx`, with
   `<repository-location>` and `xml:base` removed, went up in 4 × 64 MB chunks. Upload took 38 s and
   the async job took 7 s, 46 s end to end. Checks on the result:
   - The relationship, table captions and all field captions came back from VDS.
   - The stored `.tds` has all 41 `<desc>` elements.
   - A query that crosses the relationship gives the same results as the original.
   - **A `.tds` generated without Desktop also works.** `generate_tds.py` builds it from the
     `.hyper` schema (read with `tableauhyperapi`) plus a model JSON with table captions, column
     captions, descriptions, roles, semantic roles and relationships. It writes the federated
     connection, the collection relation, the `<cols>` map, metadata records, columns with `<desc>`,
     and the object graph. Published as "WAM Prototype - Generated TDS"
     (`c2dd24ab-aac8-48f5-a810-e2fd5cc9f236`) in 46 s, the same as the roundtrip. VDS showed both
     logical tables and the relationship. All 41 descriptions appeared in `get-datasource-metadata`.
     The cross-relationship query matched the original row for row. Fields Desktop writes that
     the generator leaves out (`approx-count`, `semantic-values`, `source-platform`, the build
     comment) aren't needed.
2. **A bare multi-table `.hyper` is rejected:** "Could not make a data source from the given Hyper
   file: it must contain exactly one fact table." Keep accepting `.hyper`, but document that it must
   be single-table. Multi-table models must be sent as `.tdsx`.
3. **`asJob=true` works, but the job result has no data source LUID.** So step 6's lookup by name +
   project is required, not optional. A failed job also comes back with **empty `statusNotes`**: the
   bare-hyper failure only gave `finishCode: 1`, and the reason only appeared in the synchronous
   publish. When a job fails with no notes, return a message listing the known causes (multi-table
   `.hyper`, malformed `.tds`, missing extract), or retry with `asJob=false` for files under ~64 MB.
4. **`description` in the publish payload is honored.** The REST data source description gets set.
5. **Catalog lags behind publishing.** Several minutes after publishing, the Metadata API still hadn't
   indexed the new data source. `get-datasource-metadata` therefore showed no descriptions, roles or
   data categories, even though the stored `.tds` has them. Consequence: the hyper-extract skill should
   hand its own field list and descriptions straight to the data-app step, not re-read them through
   `get-datasource-metadata` right after publishing. The tool could also return the field captions it
   published. The lag varies. For the generated-TDS copy, my direct Metadata API query showed it
   not yet indexed, but `get-datasource-metadata` called right after it returned all
   descriptions. Don't count on either outcome.
6. Site roles: not tested; out of scope for now. Keep `CREATOR`.
7. **A Parquet-built `.hyper` publishes and queries correctly.** `build_hyper.py` loads Parquet into a
   two-table hyper with `CREATE TABLE … AS SELECT * FROM external(…)`. The test was 500K orders and
   5K customers, covering BIG_INT, INT, SMALL_INT, DOUBLE, NUMERIC(5,2), TIMESTAMP and BOOL, with the
   Hyper API's default file format. `generate_tds.py` builds the `.tds` and the result publishes as
   "Prototype Orders - Built From Parquet" (`f95bb3f1-ff78-45ef-af1d-56ce63bc4cdc`) in 5.6 s.
   - VDS aggregates crossing the relationship (COUNT, SUM of integer, real and numeric columns, AVG)
     match local Hyper SQL exactly.
   - Dim-table measures aggregate at dim grain, so this is a relationship, not a join.
   - Orphan fact rows show up under a null dim value.
   - Columns left out of the model default correctly (integer/real → measure, `Sum`).
   - Not tested: older Tableau Server versions reading the default file format.
8. **Overwrite keeps the LUID.** Republishing with `overwrite=true` kept
   `f95bb3f1-…`. New captions, new descriptions (9 → 11) and the new REST description all took
   effect. A data app wired to the LUID survives a rebuild. Without the flag, the collision behaves as
   in the error table (403007 sync, silent `finishCode: 1` async), which is why the tool needs the
   pre-publish name check.
9. **The skill's field list wires a data app without Catalog.** The skill's own scripts rebuilt the
   Orders `.tdsx` and published it with an overwrite, again keeping `f95bb3f1-…`. The data-app
   descriptor was built straight from `generate_tds.py --fields-out`. VDS field names equal the
   model captions for all 13 fields, so the descriptor `name` is the caption. Datatypes and roles
   match too. `wire_datasource.py`, `package_twbx.py` and `publish-workbook` all succeeded:
   "Orders Region Explorer" (`fad0d06d-c0f3-496c-99c3-f2a74a1a8255`, joecon).
   - The app's query works through VDS: revenue by Region × Channel crosses the relationship, plus a
     SET filter on a dim-table boolean.
   - The new REST description took effect at once. `get-datasource-metadata` still returned the old
     one, because its descriptions come from Catalog. That's one more reason to hand off the skill's
     field list.
   - The server-side image render of an extension view only shows a sign-in page, so checking the
     live render needs a person in a browser.

## Open questions

1. **Min role.** Does Explorer (can publish) succeed at publishing a new data source through REST, or
   only Creator? Default to `CREATOR` until the prototype says otherwise.
2. **Polling limit.** Is 120 s right for hosted MCP request limits, or should the tool always return
   `pending` immediately and let the skill poll?
3. **Generic upload tool.** Fold both request tools into `request-content-upload` later?

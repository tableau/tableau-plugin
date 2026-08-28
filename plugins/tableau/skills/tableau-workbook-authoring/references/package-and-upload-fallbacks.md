# Package and upload fallbacks

Read only when package completeness is uncertain, a packaged dependency is
missing, or the selected runtime requires staged upload.

## TWBX completeness

1. Run `unzip -t workbook.twbx` and require a clean result.
2. List archive members and inspect the root TWB's local `dbname` and
   `filename` references.
3. Confirm every referenced Hyper or local file exists at the expected archive
   path.
4. Treat a bare opaque identifier used as a Hyper `dbname`, or a missing
   referenced path, as incomplete.
5. Re-download with `includeExtract: true` when incomplete. Do not invent or
   rewrite a missing dependency path.
6. Publish the verified TWBX, not the extracted TWB alone, whenever packaged
   dependencies exist.

XSD validation establishes TWB structure; it does not establish package
completeness.

## Staged-upload fallback

Use this when the callable tool schema/runtime cannot pass a server-accessible
`workbookFilePath`, or after a local-path call explicitly reports that the
transport is unsupported:

1. Call `request-workbook-upload` with the real `.twb` or `.twbx` filename.
2. Upload the exact file bytes to the returned URL using every required header.
3. Call `publish-workbook` with the returned `workbookUploadId`, name, the
   destination project's **LUID** (`projectId` — the `id` string from
   `list-projects`, e.g. `9dbd2263-16b7-...`; never a numeric ID pulled from a
   URL or another tool's output), and overwrite setting.

Staged upload IDs are short-lived and single-use. Request a fresh ID after a
failed attempt; never retry a consumed or expired ID. If staged-upload storage
is not configured, report that configuration error rather than retrying it.

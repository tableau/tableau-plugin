---
name: tableau-adhoc-analysis
description: Ad-hoc analysis of a local delimited text data file (CSV, TSV, TXT) using Tableau's VizQL Data Service without publishing a data source first. Upload the file with the upload-data-file MCP tool, inspect its fields with get-datasource-metadata, and answer questions with query-datasource, then optionally carry the analysis into a live data app. This skill relies on tools that a user may not have access to: upload-data-file. Don't invoke this skill unless that tool is available. Use when the user wants to explore, profile, or answer questions about a data file they have locally, or says "analyze this CSV with Tableau". Do not use for data already published to Tableau -- query that datasource directly -- or for Excel, Hyper, or other non-text files.
---

# Tableau Ad-hoc Analysis

Analyzes a local text data file with Tableau's query engine without
publishing anything. The file is uploaded once and then queried like a
datasource.

```
Upload  ->  Inspect fields  ->  Query (iterate)  ->  Summarize  ->  (optional) Build a data app
```

## Preflight

Verify these MCP tools are callable before starting:

- `upload-data-file`
- `get-datasource-metadata` and `query-datasource`, whose schemas include a
  `fileUpload` argument

If `upload-data-file` is missing or the other tools have no `fileUpload`
argument, the connected Tableau MCP server does not support ad-hoc file
analysis. Stop and say so; do not fall back to reading the file yourself and
presenting the result as Tableau analysis.

Only delimited text is supported: `.csv`, `.tsv`, `.txt`, `.tab`, `.txn`. For
other formats, ask the user to export to CSV.

## Upload the file

Pass a local path when the MCP server runs on the same machine:

> upload-data-file({ filePath: "/abs/path/sales.csv" })

If the tool reports `filePath` is not supported (hosted MCP server), pass the
text instead:

> upload-data-file({ content: "<file text>", fileName: "sales.csv" })

Omit `textOptions` unless you know Tableau will infer them wrong. Look at the
first few lines of the file first. Set them only when the file has:

- a separator other than the one the extension implies, e.g. `;` in a `.csv`
  or `|` in a `.txt` (`separator`);
- no header row (`hasHeader: false`);
- a non-UTF-8 encoding (`characterSet`);
- locale-specific numbers or dates, e.g. `1.234,56` (`locale`).

The result carries a `fileUpload` object. Keep it verbatim. Every later call
passes it unchanged in place of `datasourceLuid`. Never pass both.

## Inspect the fields

> get-datasource-metadata({ fileUpload: <fileUpload> })

This returns field captions, data types, and default aggregations as Tableau
inferred them from the file. There is no datasource model, description, or
Metadata API enrichment for an uploaded file.

Check the inference before querying:

- Numeric IDs or ZIP codes typed as numbers: treat them as dimensions and
  avoid `SUM`.
- Dates typed as strings: the locale or format was not recognized. Re-upload
  with `textOptions.locale`, or parse them with a calculation in the query.
- A single field holding entire rows means the separator is wrong. Re-upload
  with `textOptions.separator`.

If a re-upload is needed, use the new `fileUpload` from then on.

## Query

> query-datasource({ fileUpload: <fileUpload>, query: { fields: [...], filters: [...] } })

The query language is the same as for a published datasource. Use exact
field captions from the metadata. Calculated fields go in `calculation`.
Start with aggregate queries, such as counts, totals by a dimension, or date
trends. Pull row-level detail only when the question needs it, and set
`limit`.

Each call re-reads the uploaded file, so iterating is cheap. Reuse the same
`fileUpload` for every call.

**Upload not found:** uploads are private to the user who created them and
expire after a period of inactivity. If a call says the uploaded file was not
found, run `upload-data-file` again with the same file and options, then
continue with the new `fileUpload`. Don't ask the user first.

## Summarize

Report findings with the numbers that support them. State any assumptions
you made about field meaning or type. Keep a running record of the questions
answered and the queries that answered them. The data-app handoff below uses
it.

## Transition to a data app

When the user wants the analysis as a live app, read the
`tableau-data-app-authoring` skill and follow its workflow. One thing
changes: **a data app cannot query an upload.** The app queries a
**published** datasource at runtime, and an upload is private and temporary.
The file must be published first.

1. **Get the file published as a datasource.** This MCP server has no
   publish-datasource tool, so the user does this step: Tableau web authoring
   (New > Published Data Source, then upload the file) or Tableau Desktop
   (connect to the text file, then Server > Publish Data Source). Ask them
   to tell you the published name.
2. **Resolve it** with `list-datasources`. Then run
   `get-datasource-metadata({ datasourceLuid })` and compare its fields with
   the upload's metadata. Captions and types usually match, but republishing
   can rename or retype fields. Map any differences before reusing queries.
3. **Write a handoff brief** to `$WORK/analysis-brief.md` containing:
   - the questions answered;
   - the fields used, with role and type;
   - the `query-datasource` queries that answered them, rewritten to the
     published field captions;
   - the key findings the app should surface.

   Use it as the design input for Design a data app.
4. **Continue** at the data-app skill's Preflight. The published datasource
   is wired with `wire_datasource.py` like any other. The brief's queries
   map onto the app's `queryAsync` calls.

If the user wants the app to keep the uploaded data private, or does not want
a published datasource, say this is not supported yet and stop at the
summary.

## Non-negotiable limits

- Never pass both `datasourceLuid` and `fileUpload`.
- Never edit the `fileUpload` object; pass it as returned.
- Don't compute answers from the raw file yourself and attribute them to
  Tableau. Answers must come from `query-datasource`.
- Don't try to wire an upload into a data app. Data apps require a published
  datasource.

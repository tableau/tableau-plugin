---
name: tableau-content-viewer
description: Show, open, or render an existing Tableau view, dashboard, or workbook live via render-interactive-viz, by name or keyword — for "show me/open/pull up this dashboard/view" requests. Do not use to query or analyze the data behind it or to create/edit/publish a workbook (tableau-workbook-authoring).
---

# Purpose

Find a specific Tableau view (or workbook) and render it live via `render-interactive-viz`. Never touches a `.twb` file.

Tool names here are the Tableau MCP server's own names. The host may list them
with a server prefix (e.g. `mcp__<server>__search-content`); call the listed
tool whose name ends in the name given here.

# Routing

- Find the content → `search-content` — see [`../../references/search.md`](../../references/search.md) for the call shape and how to disambiguate multiple matches. Reuse an already-resolved LUID/URL instead of searching again for the same content.
- Get a render-ready URL → `get-view` (resolved `luid` as `viewId`) or `get-workbook` (as `workbookId`, only when no specific view matched). `search-content` never returns a URL — this call is required.
- Render → `render-interactive-viz` with the resolved `luid` and matching `objectType`. If unavailable, open the direct `/t/SITE/views/...` URL in the in-app browser (`navigate`); failing that, give the URL as a hyperlink and show a `get-view-image` PNG inline — see [`../../references/rendering.md`](../../references/rendering.md).

# Requirements

- Prefer a view result when the user asked for a view; a workbook-only match is fine only when the user asked for the workbook as a whole.
- Don't fabricate a view/workbook name or URL the search tools didn't surface.
- A missing `render-interactive-viz`/search/content tool usually means a site admin disabled its group (`mcp-apps`/`EXCLUDE_TOOLS`) — that's site config, not a bug.
- If the `download-workbook` tool returns a temporary URL, download the file locally

# References

- [`../../references/search.md`](../../references/search.md) — resolving a name/keyword to content and disambiguating multiple matches.
- [`../../references/rendering.md`](../../references/rendering.md) — exact render call sequence and URL construction.

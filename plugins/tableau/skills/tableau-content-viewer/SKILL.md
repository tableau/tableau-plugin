---
name: tableau-content-viewer
description: Find a specific view (or workbook) on the Tableau site by name or keyword and render it live in the Codex right-side panel so the user can see it — for "show me/open/pull up this dashboard/view" requests. Not for querying or analyzing the data behind it (use tableau-analytics for that) and not for creating or editing a workbook (use tableau-workbook-authoring for that).
---

Use this when the user just wants to **see** a piece of Tableau content, not
query its data or change it. This skill never touches a `.twb` file — it only
finds content and renders it.

## 1. Find the content

Use `search-content` (or `list-views`/`list-workbooks` if you already know
which kind of content it is) to locate what the user means, by name or
keyword. The user said they want a **view**, not a workbook, so prefer a
result that's typed as a view — if the search surfaces a workbook instead,
that's fine as a way to navigate (a workbook is made of views), but confirm
with the user which specific view inside it they want rendered, since
`render-interactive-viz` renders one piece of content at a time.

If more than one result plausibly matches what the user asked for, don't
guess — list the candidates and ask which one before rendering.

## 2. Get the view's LUID and URL

Once you've confirmed the right view, note its `id` (LUID) and `contentUrl`/
`url` from that same search/list result — that's everything the render step
needs. No download step here; you never need the underlying `.twb`/`.hyper`
to render a view, only its identifiers.

## 3. Render it

See [`../shared/rendering.md`](../shared/rendering.md) for the exact tool
calls. Use the view's LUID with `objectType: "view"`, and its URL for the
fallback path.

## 4. Repeat for follow-ups

If the user then asks to see a different view or workbook, go back to step 1
with the new request — each render is independent, there's nothing to carry
over between them.

## Notes

- `render-interactive-viz`/`get-embed-token` are gated by Tableau's
  `mcp-apps` tool group — see [`../shared/rendering.md`](../shared/rendering.md)
  for what to tell the user if it's unavailable.
- A site admin can disable search/content tool groups via Tableau's
  `EXCLUDE_TOOLS` site setting. If an expected tool isn't available, treat
  that as a site configuration matter, not a bug to work around.
- Don't fabricate a view/workbook name or URL if the search tools don't
  surface it — say so instead of guessing.

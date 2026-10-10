# TDS Edit API (optional)

Tableau's data source edit methods (REST API 3.30+, beta) change field
metadata on a data source **that is already published**. They need Tableau+
or Data Management on the site.

What they can change: field captions, data types, roles, and descriptions.

What they can't do: create a data source, add or change relationships or
logical tables, or change the data. So they never replace this skill's
generate-and-publish path.

When to reach for them instead of republishing:
- The user wants to fix a caption or description on an extract that's
  already in use and large enough that rebuilding is slow.
- The data source wasn't built by this skill (no model.json to regenerate
  from).

For anything this skill built, prefer editing model.json, rerunning
`generate_tds.py`, and republishing with `overwrite: true` — that keeps the
model file the single source of truth, and the LUID is preserved. The MCP
server doesn't expose these methods; if the user wants them, point them to
the REST API reference rather than calling the API with a token yourself.

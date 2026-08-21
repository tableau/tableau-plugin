---
name: tableau-analytics
description: Explore, query, and analyze existing Tableau content (workbooks, data sources, views, Pulse metrics) through the hosted Tableau MCP server. Use for read-oriented questions about Tableau dashboards, data sources, published data, Pulse metrics, or site content. For creating or modifying a workbook/dashboard, use the tableau-workbook-authoring skill instead.
---

Use the `tableau` MCP server's tools to answer the request. The server proxies
Tableau's REST, VizQL Data Service (VDS), Metadata, and Pulse APIs using the
signed-in user's own OAuth token, so results are automatically scoped to
whatever that user can already see in Tableau — never assume broader access
than what the tools return.

## Workflow

1. **Find content before querying it.** Use the content-exploration/search
   tools first to locate the relevant workbook, data source, or view by name
   or keyword rather than guessing IDs.
2. **Inspect a data source before querying it.** Use the data source metadata
   tools to see available fields, then query through VDS for aggregated or
   filtered results instead of estimating numbers from memory.
3. **Prefer Pulse for KPI/trend questions.** If the user is asking about a
   metric that already exists as a Pulse metric (e.g. "how's revenue
   trending"), check Pulse metrics and insights before building a custom
   query — Pulse insights are pre-computed and often answer the question
   directly.
4. **Use workbook/view tools to read dashboards** — for example to pull the
   underlying data of a view or describe what a dashboard shows.
5. **Treat project tools as context, not the goal.** Use them to understand
   how content is organized or to scope a search, not as an end in
   themselves.
6. **Be conservative with jobs, tasks, users, token-management, and
   admin-insights tools.** These can trigger extract refreshes, touch site
   configuration, or surface other users' details. Only use them when the
   user explicitly asks for that action, and confirm before doing anything
   that changes state (starting a job, revoking a token, editing a user).

## Notes

- A site admin can disable entire tool groups (e.g. `pulse`, `workbook`,
  `admin-insights`) via Tableau's `EXCLUDE_TOOLS` site setting. If an expected
  tool isn't available, treat that as the site's configuration rather than an
  error to work around.
- The first time this plugin's MCP server is used, Codex needs an OAuth
  sign-in to Tableau Cloud/Server (`codex mcp login tableau`, or the
  in-product "Authenticate" prompt). If a call fails with an auth error,
  suggest re-running that login rather than retrying blindly.
- Don't fabricate workbook names, field names, or numbers — if the search or
  metadata tools don't surface something, say so instead of guessing.

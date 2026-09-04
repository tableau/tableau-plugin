# Tableau content search strategy

Use the stages that the active Tableau MCP server supports. Tool names, parameters, permissions, and returned fields may vary.

## 1. Resolve project scope

When the user names a project, search or list projects to resolve the canonical project identity and hierarchy. Use descriptions and parent metadata as evidence. For a fuzzy or owner-based hint, present a small candidate set instead of silently selecting a project.

When the user asks to browse projects, prefer top-level results first and drill into children on request. Do not assume that wildcard, owner, or parent filters exist; inspect the active tool schema and post-filter returned metadata when necessary.

## 2. Choose search breadth

- **Small scoped project:** a bounded inventory of views/workbooks plus relevant datasources can maximize recall.
- **Large scoped project:** lead with server-side content search and supplement only when results are sparse or naming is opaque.
- **Full site:** use bounded server-side search with a few deliberate term sets. Do not download a complete site inventory by default.

If project size is unknown, start with a bounded search rather than making a separate expensive counting pass.

## 3. Search concepts

Extract:

- primary nouns and business concepts;
- implied measures and dimensions;
- time intent such as trend, monthly, YTD, or historical;
- conservative synonyms.

Useful starter relationships include:

| Concept | Related terms |
| --- | --- |
| sales | revenue, orders, bookings, ARR, MRR |
| customers | clients, accounts, users, subscribers |
| churn | attrition, retention, cancellation |
| profit | margin, earnings, net income, EBIT |
| pipeline | funnel, opportunities, deals, prospects |
| performance | KPI, metrics, scorecard, health |
| trend | time series, historical, monthly, weekly |
| region | geography, territory, market, location |
| product | SKU, item, catalog, offering, category |
| employee | headcount, staff, workforce, HR |

Do not treat every related term as equivalent. Add domain-specific synonyms supplied by the user or established in the current conversation.

## 4. Layer evidence

Start with content names, descriptions, tags, project context, and types. Add field metadata only for promising datasources or the datasources behind leading views. Add view/workbook detail when it provides a canonical URL, usage metadata, upstream datasource evidence, or companion views.

Pulse definitions are in scope only when the user asks about a metric/KPI or requests a broad sweep and the server exposes Pulse discovery.

## 5. Handle degraded access

- Search unavailable: use bounded list operations if available.
- Datasource listing denied: use upstream datasource references returned with views.
- Field metadata unavailable: retain name/description evidence and lower the certainty of field-level claims.
- Pulse unavailable: omit it from searched counts and name it as unavailable only when it was requested or material.
- Canonical URL unavailable: omit the link instead of constructing one.

Separate an empty successful search from a permission or availability failure.

## 6. Evidence normalization

Build candidate records only from returned metadata. Deduplicate identical canonical IDs before ranking. If the same object appears through several searches, merge non-conflicting evidence and retain the server-returned canonical link.

Use an explicit `as_of` date in the ranking input when applying the 90-day recency signal. Without it, the ranker omits recency so repeated runs remain deterministic.

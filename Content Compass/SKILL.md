---
name: tableau-content-compass
description: Find and rank existing Tableau views, workbooks, datasources, projects, and Pulse metrics for a business question using Tableau MCP metadata. Use for content discovery and gap identification; do not use to build, modify, critique, document, or query the underlying data.
---

# Tableau Content Compass

Help users answer “Do we already have Tableau content for this?” Search existing metadata, rank candidates from explicit evidence, and distinguish strong coverage from a genuine gap. Keep the workflow read-only.

## Resolve the request

Identify:

- the business question or topic;
- any stated project, owner, site, or content-type scope;
- whether the user wants views, datasources, Pulse metrics, projects, or a broad sweep.

Use established conversation context when it clearly resolves scope, but do not read or write persistent memory merely because this skill is active. Never persist search history or inferred preferences unless the user separately requests it and the runtime supports it.

Ask one focused scope question only when the missing choice would materially change cost or results. Do not always require a project: for an unscoped “find anything about churn” request, a bounded site search is a reasonable default. Confirm before an exhaustive inventory of a large site.

Route build, workbook-editing, visual critique, documentation, and underlying-data query requests to an appropriate available capability. For a mixed request, complete discovery first and preserve the remaining requested work rather than silently discarding it.

## Discover Tableau capabilities

Use the actual Tableau MCP tools and schemas available in the current runtime. Look for capabilities that can:

- search or list projects and navigate parent/child projects;
- search Tableau content by term and type;
- list project-scoped views, workbooks, or datasources;
- retrieve datasource field metadata;
- list Pulse metric definitions;
- retrieve view/workbook detail and canonical URLs.

Do not invent a missing tool, filter syntax, field, response limit, or identifier format. Treat URL route segments and display names as lookup inputs, not canonical IDs. Use only identifiers and links returned by the active Tableau server.

If no Tableau content-discovery capability is available, stop and ask the user to connect Tableau or provide a metadata export. Do not infer that content is absent and do not fabricate candidates.

Read [search-strategy.md](references/search-strategy.md) before executing a search. Adapt its stages to the capabilities that actually exist.

## Search efficiently

Extract primary concepts, implied measures and dimensions, useful synonyms, and temporal intent from the question. Preserve the user's project and content-type limits.

Prefer server-side term search for full-site or large-project discovery. For a small project, a bounded project inventory may provide better recall. Expand synonyms conservatively; a related term improves recall but is weaker evidence than an exact concept match.

Enrich only the leading candidates when deeper metadata calls are expensive. A default ceiling of five datasource-detail calls and five view/workbook-detail calls is reasonable unless the user requests broader coverage or the server makes a batch route cheaper.

If a capability is unavailable or permission-denied, continue with the evidence available and state the limitation. Do not treat “not searchable with current access” as “does not exist.”

## Rank candidates

Normalize the gathered metadata into the contract in [ranking-schema.md](references/ranking-schema.md). Resolve the absolute directory containing this loaded `SKILL.md`, then invoke its `scripts/rank_content.py` with the absolute path to the candidate JSON. Do not assume the skill directory is the current working directory.

The ranker scores name, field, description, tag, Pulse, temporal, usage, and recency evidence without double-counting the same name or field evidence. It produces High, Medium, and Low tiers, filters noise below 15, caps displayed results per tier, and returns the top scoring signals for explanation.

The helper is the arithmetic authority, not the search authority. Review its output against the source metadata. Never boost a weak match manually to make the result set look better.

## Present results

Lead with the best match and answer the user's question in plain language. Include:

- query and search scope;
- searched content types and any unavailable sources;
- up to three results per confidence tier;
- content type, project/workbook context, owner when useful, and server-returned link when available;
- “why this matches” using the top two named scoring signals;
- a coverage assessment: Fully covered, Partially covered, Not covered, or Unknown with current access.

Do not guess URLs, dump raw field inventories, or imply that popularity proves correctness. Usage and recency are tie-breakers and weak confidence signals, not endorsements.

When no candidate clears the threshold, describe the search performed and its access limits. Call it a confirmed gap only when the relevant scope was searched with adequate coverage; otherwise say no match was found with current access.

## Refinement

Carry the current scope forward unless the user changes it. For “dig deeper,” enrich the referenced candidate and its companion workbook views. For new terms, rerun and merge results while identifying new matches. For broader scope, expand deliberately and group results by project.

After three refinements without a new High-confidence result, summarize the exhausted search paths and ask whether to try a different concept or treat the result as a likely gap. Do not loop indefinitely.

## Boundaries

- Discovery requests do not authorize content edits, publication, subscriptions, comments, downloads, or data queries.
- Never recommend a content item that was not returned by Tableau or supplied by the user.
- Do not expose raw field metadata when a concise evidence summary is sufficient.
- Minimize personal or sensitive metadata in the response.
- Do not call a match certified, current, popular, or authoritative unless the returned metadata supports that exact claim.

For implementation changes, run `python -m unittest discover -s scripts/tests -v` and the active skill validator.

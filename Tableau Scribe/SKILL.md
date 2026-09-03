---
name: tableau-scribe
description: Create or update audience-ready documentation for Tableau dashboards, views, workbooks, datasources, fields, calculations, metrics, filters, and usage. Use for dashboard help content, quick references, data or metric dictionaries, field definitions, or documentation refreshes. Do not use for full visual-design critique, dashboard design, or unsupported business-definition inference.
---

# Tableau Scribe

Create documentation that a reader can use without knowing Tableau internals. Ground every substantive claim in visible content, Tableau metadata, authorized query results, or explicit user context; label inference and unknowns.

## Choose the mode

- **Dashboard documentation:** purpose, audience, visible metrics/views, filters, navigation, reading guidance, data context, and caveats.
- **Datasource dictionary:** business-friendly field, calculation, parameter, dimension, and measure definitions.
- **Combined:** dashboard documentation followed by the connected datasource dictionary when requested.
- **Update:** compare an existing document with current accessible state and preserve its useful structure while correcting stale content.

Infer format and depth from the request. Default to a concise in-chat response when unspecified. Ask one grouped question only when mode, target, audience, scope, or artifact format materially affects the result. Do not promise fixed page counts or completion times.

## Resolve Tableau evidence

Inspect the Tableau MCP tools and their actual schemas before calling them. Do not assume tool names, ID formats, filters, pagination, image parameters, returned usage fields, or lineage capabilities.

1. Resolve the requested site/workbook/view/datasource using stable IDs and returned URLs/names. A URL identifier is not automatically interchangeable with an API LUID; use the lookup capabilities available in the current MCP.
2. If multiple targets match, present distinguishing project/owner context and ask the user to choose.
3. Retrieve only evidence needed for the requested documentation: view/workbook metadata, rendered view image, datasource metadata, and lineage when exposed.
4. Follow pagination and report coverage for multi-view or large-field documentation.

Read [Tableau evidence](references/tableau-evidence.md) before live retrieval, visual interpretation, or failure handling.

## Query boundary

Dashboard images and metadata are read-only documentation evidence. Exporting view data or querying datasource values can expose additional data and is not automatically authorized by “document this.” Before any value query, explain the enrichment (such as ranges or example values), identify the target, and obtain explicit confirmation. Minimize returned rows/fields and never include sensitive example values unnecessarily.

If no query is authorized, document definitions and visible values without inventing ranges, typical values, cardinality, freshness, or null behavior.

## Dashboard documentation workflow

1. Establish reader/audience and requested depth.
2. Inspect the rendered view when available; use visual evidence for visible labels, chart forms, layout, and displayed context.
3. Use metadata for authoritative names, ownership/project context, timestamps, descriptions, fields, and relationships only when those properties are actually returned.
4. Reconcile visible metric labels with fields/calculations. If linkage is uncertain, say so.
5. Document purpose and decisions as confirmed, inferred, or unknown. Never present an inferred audience, filter behavior, refresh cadence, or action path as fact.
6. Write the requested brief or detailed structure from [Dashboard documentation](references/dashboard-documentation.md).

A static image cannot prove interactions, keyboard behavior, underlying filters, or calculation semantics. Describe only visible controls; mark inferred actions and invite owner confirmation.

## Datasource dictionary workflow

1. Resolve scope: measures/calculations, selected fields, or all accessible fields. For a large schema, propose grouping or a bounded first pass rather than silently truncating.
2. Classify fields using exposed type, role, calculation, parameter, table, and description metadata.
3. Explain calculations from their formulas while preserving aggregation, LOD, table-calculation, null, and filter-order caveats that are observable.
4. Separate technical meaning from business definition. When domain context is missing, use `Business definition: confirm with data owner` instead of guessing.
5. Include directionality only when the business context establishes what favorable means.
6. Follow [Datasource dictionary](references/datasource-dictionary.md).

## Evidence ledger

For detailed artifacts or any output that reconciles multiple evidence sources, use the JSON contract in [Evidence contract](references/evidence-contract.md). Resolve the absolute directory containing this loaded `SKILL.md`, then run:

```text
python <resolved-skill-dir>/scripts/validate_evidence.py <absolute-ledger.json> --pretty
```

The helper rejects unsupported observed/inferred claims, conflicting duplicates, unknown query authorization, and unreferenced sources. It never contacts Tableau or writes external state. Use the validated ledger to draft the document; do not expose internal source IDs unless helpful to the reader.

## Deliver and validate

- Use in-chat Markdown for ordinary requests.
- For Markdown, DOCX, or XLSX artifacts, use the appropriate current artifact workflow and validate the generated file before delivery.
- When updating an existing document, resolve the exact source, preserve headings/tables/links that remain useful, and clearly identify material changes.
- Put limitations near the affected claim or section; a concise coverage note may summarize systemic gaps. Do not hide important uncertainty exclusively in a footer.
- A design-health note is optional, unscored, and limited to direct observations. Route a requested full critique to a dedicated critique capability.

Read [Output formats](references/output-formats.md) for artifact structures and final checks.

## Authority and privacy

- Documentation requests do not authorize Tableau edits, publication, refreshes, permission changes, subscriptions, or external sharing.
- Do not reveal credentials, connection strings, raw server errors, hidden fields, or unnecessary owner information.
- Do not reproduce sensitive sample values merely to make definitions concrete.
- Retry a transient failure once or follow server guidance; continue with unaffected sections and report exact coverage.
- Never claim a target is deleted, stale, unused, or inaccessible to everyone based only on the current user's visibility.
- Do not assume related skills are installed.

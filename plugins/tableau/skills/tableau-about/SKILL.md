---

## name: tableau-about
description: Explain what the Tableau plugin is for and how it helps users work with existing or new Tableau content. Use when someone asks about the plugin, its purpose, suitable use cases, or why they should use it.

# Tableau Plugin Overview

The Tableau plugin connects Codex to Tableau so users can explore existing analytics content, understand dashboard data, plan new dashboards, evaluate datasource metadata, review visualization design, and create or modify workbooks.

## Core capabilities

### Explore existing Tableau content

Find and open Tableau views, dashboards, workbooks, datasources, and metrics by name or keyword. Use the appropriate focused Tableau skill when the user wants to inspect or work with a specific item.

### Analyze dashboard data

Answer questions using the summary data exposed by a Tableau view. This can include identifying trends, comparing categories, applying supported filters, and finding marks that meet a condition.

Do not imply unrestricted access to underlying row-level data. Analysis is limited to the data and metadata Tableau makes available through the connected capabilities and the user’s permissions.

### Create or modify workbooks

Build a new Tableau workbook or update an existing one from a natural-language request. This can include creating sheets, calculations, charts, dashboards, filters, and layouts, then publishing the result when requested and authorized.

The model constructs the workbook definition programmatically. Users do not need to understand or edit workbook XML themselves.

## Planning and review capabilities



### Design dashboard blueprints

Turn business questions, audience needs, and available datasource metadata into an implementation-ready Tableau dashboard plan.

A blueprint can specify:

- KPIs and analytical questions
- Recommended charts
- Dashboard hierarchy and layout
- Filters, actions, and tooltips
- Desktop and tablet behavior
- Accessible colors and typography
- Tableau implementation guidance
- A deterministic HTML wireframe when useful

This is a planning workflow. It does not build or publish the workbook unless the user separately requests that work.

### Review datasource metadata quality

Evaluate published Tableau datasource metadata for:

- Schema hygiene
- Field naming
- Likely type or role mismatches
- Calculation complexity
- Documentation gaps
- Available freshness signals

The review can produce full scans, priority-only reports, datasource comparisons, changed-only results, or comparisons with a prior baseline.

This is a metadata-only assessment. It does not claim to detect row-level nulls, duplicates, distributions, PII, or underlying-data freshness when those facts are not exposed by the available metadata.

### Critique visualization design

Review and score Tableau dashboards or views using rendered-image evidence, available Tableau metadata, and a seven-domain design rubric.

The critique can assess:

- Audience adaptation
- Message alignment
- Chart selection
- Layout and storytelling
- Color
- Textual elements
- Typography and readability

Recommendations should be prioritized and tied to visible or explicitly supplied evidence. The critique is read-only: it does not modify workbooks, validate source-data accuracy, assess business performance, or infer interactions and accessibility behavior that cannot be observed.

## Routing guidance

Use the focused Tableau skill that best matches the requested outcome:

- Use `tableau-content-viewer` to find, open, or show existing Tableau content.
- Use `tableau-dashboard-blueprint` to plan a dashboard or create a wireframe.
- Use `tableau-data-quality-sentinel` to review published datasource metadata.
- Use `tableau-viz-critique` to evaluate an existing dashboard or view.
- Use `tableau-workbook-authoring` to create, edit, copy, or publish a workbook.

For requests spanning multiple workflows, sequence them explicitly. For example, critique an existing dashboard before handing approved recommendations to workbook authoring.

## Representative requests

- `Find and open the regional sales dashboard.`
- `Explain the largest trends in this view.`
- `Which products shown here meet this condition?`
- `Design an executive dashboard for regional sales performance.`
- `Create a desktop and tablet wireframe for this dashboard plan.`
- `Run a metadata quality scan on the Sales datasource.`
- `Compare metadata quality for Orders and Orders v2.`
- `Review this dashboard and prioritize its three highest-impact improvements.`
- `Add a monthly trend chart to this workbook and publish the update.`


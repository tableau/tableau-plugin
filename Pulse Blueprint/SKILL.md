---
name: pulse-blueprint
description: Design, review, and optimize Tableau Pulse metric definitions from business questions, datasource metadata, or existing configurations. Use for Pulse metric blueprints, metric-program recommendations, configuration audits, filtered metric strategy, or implementation-ready change plans. Do not use for dashboard design, general datasource profiling, or current metric insight summaries.
---

# Tableau Pulse Blueprint

Translate decision needs and observable Tableau configuration into a small, actionable Pulse metric program. Distinguish recommendations, current configuration, and assumptions.

## Route the request

- **Design:** turn a business question into one or more metric-definition blueprints.
- **Recommend:** rank useful metrics for a datasource or business area.
- **Audit:** evaluate existing definitions against their intended decisions and available configuration.
- **Optimize:** compare current and recommended settings without silently changing them.
- For current metric values or generated insights, use an insight-reading workflow rather than this design skill.
- For dashboard layout or broad datasource quality, use the relevant capability instead.

If intent is clear, proceed. Ask one focused question when the measure, decision owner, favorable direction, cadence, or target datasource cannot be resolved without materially changing the result.

## Discover current capabilities

Inspect the Tableau MCP tools and their actual schemas before use. Do not assume tool names, enum values, filters, pagination, response fields, or whether this MCP exposes Pulse mutations. Distinguish:

1. what Tableau Pulse APIs may support;
2. what the connected MCP exposes;
3. what the current user is authorized and asking to do.

Use read capabilities to inventory definitions, retrieve definition/metric details, and inspect candidate datasource metadata when available. Follow pagination and record coverage. If tools are absent, build from supplied information and label unverified fields.

Read [Tableau Pulse capabilities](references/tableau-pulse-capabilities.md) when selecting tools, using enums, or considering a mutation.

## Design workflow

1. **Frame the decision.** State metric owner/audience, question, action, review cadence, favorable direction, and required comparison.
2. **Check overlap when possible.** Search accessible existing definitions for semantic overlap. If an apparent match exists, present it and ask whether to optimize, create a distinct variant, or stop. Lack of read access is not proof that no duplicate exists.
3. **Resolve data evidence.** Identify datasource, measure, aggregation, time dimension, data grain, useful breakdown dimensions, fixed filters, and known caveats. Read [Metric design](references/metric-design.md).
4. **Specify configuration.** Recommend supported granularities, comparisons, sentiment/favorable direction, formatting, insights, optional goals, and row-level settings only when applicable.
5. **Validate.** Verify every field reference against observed metadata when available, confirm aggregation semantics, check time grain and filter compatibility, and flag properties requiring live-schema verification.
6. **Deliver.** Provide the blueprint or ranked program, reasoning, blockers, and a concise implementation/change checklist using [Output contract](references/output-contract.md).

Do not require arbitrary minimum counts for dimensions, granularities, comparisons, goals, filtered metrics, or insight types. Each choice must serve the metric’s decision and data shape.

## Audit and optimization

For an audit, retrieve the fullest accessible definition objects and related metrics. Treat missing API properties as `not assessed`, not misconfigured. Apply the contextual checks in [Audit methodology](references/audit-methodology.md); observations are not penalties.

Normalize scored findings with [Audit scoring contract](references/audit-scoring-contract.md). Resolve the absolute directory containing this loaded `SKILL.md`, then run:

```text
python <resolved-skill-dir>/scripts/score_audit.py <absolute-audit.json> --pretty
```

The helper validates input, deduplicates findings, excludes failed/partial definitions from the composite, and never contacts Tableau. If local execution is unavailable, calculate manually and label the result. Never present an audit score without reporting coverage and unassessed checks.

For optimization, show current versus recommended configuration, evidence, expected benefit, tradeoff, and whether the change is required, optional, or blocked. Do not infer a goal from history unless the user authorizes the necessary data query and the method is appropriate.

## Mutation boundary

A design, recommendation, audit, or optimization request authorizes read-only analysis—not creation, update, deletion, subscription changes, or notification changes.

If the MCP exposes a requested Pulse mutation:

1. prepare and show the exact target and proposed configuration/change;
2. resolve ambiguous IDs and verify fields/enums against the live tool schema;
3. obtain explicit confirmation immediately before the write;
4. execute only the confirmed action and verify by reading current state when safe;
5. never delete, overwrite, or broaden followers/subscriptions as an incidental step.

If no mutation capability exists, provide UI-ready instructions or a structured payload draft; do not claim the change was applied.

## Baselines and continuity

Use prior results only when the user supplies them or an authorized persistent destination is available. Saving a baseline is a separate write and requires confirmation of destination. Match definitions by stable ID and findings by `definition_id + rule_id + evidence_key`. If methodology or observable fields differ, label comparisons non-equivalent and avoid a numeric delta.

Read [State and comparison](references/state-and-comparison.md) only for saved audits, delta reviews, or recurring monitoring.

## Non-negotiable limits

- Never hard-code a historical enum catalog as universally current; use the live schema or label values for verification.
- Do not infer field cardinality, freshness, metric values, goals, or data quality from names alone.
- Do not treat neutral sentiment, one comparison, few dimensions, no goal, or no row-level configuration as inherently defective.
- Do not recommend every insight type by default.
- Do not expose credentials, connection details, raw server errors, or unnecessary owner information.
- Do not assume related skills are installed.

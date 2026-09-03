---
name: tableau-governance-scanner
description: Audit Tableau Cloud or Server content governance through a connected Tableau MCP server. Use for evidence-backed reviews of stale-looking content, adoption signals, certification, naming, ownership concentration, project organization, performance risk indicators, and metadata completeness; for project or site comparisons; or for repeatable governance baselines. Operate read-only unless the user separately approves a specific remediation. Do not use for row-level data quality, visual-design critique, permissions assurance, or measured performance testing.
---

# Tableau Governance Scanner

Produce a compact, reproducible governance assessment without overstating what Tableau metadata proves.

## Start here

1. Infer the scope, policy profile, and output from the request. If a material choice is missing, ask one concise question. Default to Standard, the narrowest clearly intended scope, and an in-chat Markdown report.
2. Inspect the currently available Tableau MCP tools and their schemas. Do not assume a particular server, tool name, field, page size, or response shape.
3. Confirm that the connected identity can read the intended scope. State that results cover only visible content.
4. Run discovery and analysis read-only. Never rename, move, tag, certify, archive, delete, refresh, or republish content during a scan.
5. Validate coverage and evidence before scoring. Missing or failed fields are `not assessed`, never passes.
6. Deliver the executive summary first, then prioritized findings and coverage limits.

Read [references/methodology.md](references/methodology.md) before collecting or classifying evidence. Read [references/mcp-and-evidence.md](references/mcp-and-evidence.md) when mapping the available Tableau tools and fields. Read [references/reporting.md](references/reporting.md) when producing a file, comparison, score, or baseline.

## Establish the scan contract

Resolve these decisions from the request and prior conversation:

- **Scope:** site, project, or an explicit list of content identifiers.
- **Policy:** Light, Standard, Strict, or user-supplied thresholds.
- **Output:** chat Markdown, Markdown file, JSON, XLSX, DOCX, or self-contained HTML.
- **Comparison:** none, another scope, or a supplied prior baseline.

Treat bundled thresholds as starting policies, not universal standards. Echo the effective thresholds in the report. If a date boundary matters, use UTC unless the user specifies another timezone.

Do not search unrelated memory or files automatically. Reuse a prior baseline only when the user identifies it or it is already available in the conversation/workspace. Do not save a baseline unless the user requests or approves it.

## Discover Tableau capabilities

Inspect tool descriptions and input schemas first. Prefer read operations that can enumerate projects, workbooks, views, published data sources, owners, tags, descriptions, timestamps, usage statistics, and lineage. Use stable Tableau identifiers when available; names are display labels, not reliable join keys.

Build a capability map before scanning:

| Evidence family | Required to assess | Otherwise |
|---|---|---|
| Inventory | stable ID, type, name, visible scope | Mark the affected inventory partial |
| Modification age | a documented content modification timestamp | Skip age rules; do not call it data freshness |
| Adoption | a defined usage measure and its time semantics | Report cumulative counts only as cumulative; do not infer recent use |
| Trust | certification/warning fields actually returned | Mark certification not assessed |
| Lineage | explicit upstream/downstream relations | Do not claim orphaned, duplicated, or safe-to-remove content |
| Performance | measured telemetry or documented structural proxy | Label proxies as candidates, never measured slowness |

Follow the server's actual pagination or continuation contract until the requested scope is complete or a declared bound is reached. Deduplicate by stable ID. Do not infer hidden content from count gaps.

## Collect in phases

1. **Inventory:** projects, workbooks, views, and published data sources visible in scope.
2. **Join:** relate items using IDs returned by Tableau. Record unresolved joins.
3. **Enrich:** query details only where they materially change a rule or recommendation. Use small batches and stop when marginal value is low.
4. **Classify:** apply the selected policy and contextual exceptions.
5. **Validate:** verify identifiers, evidence fields, scope, coverage, deduplication, and compound severity.
6. **Score:** normalize across assessed items with `scripts/score_governance.py` when a numeric score is useful.
7. **Report:** separate facts, inferences, observations, and recommended follow-up.

Continue after non-core failures when a useful partial scan remains possible. State exactly which domains and counts are partial. If the core inventory cannot be established, stop and explain what access or capability is missing.

## Evidence rules

- Cite a stable content ID or resolvable content URL, the observed value, and the observation time for every finding.
- A content `updatedAt`-style field is evidence of content modification age, not extract freshness, source freshness, or recent use.
- A `totalViewCount`-style field is cumulative unless the tool explicitly documents a window. Never turn it into views per month or “active in the last N days.”
- Empty strings count as missing only when the field was returned and its schema makes that interpretation valid. An absent field is not assessed.
- “Uncertified” means an explicit false/unset certification state was observed. If the property is unavailable, say certification was not assessed.
- “Orphaned,” “unused,” “safe to archive,” and “high downstream impact” require direct evidence with defined lineage or usage semantics.
- Naming matches are review candidates. Apply project context and quote the matched pattern.
- Owner concentration is a portfolio risk signal, not criticism of a person.
- Structural characteristics such as workbook size, sheet count, or live connections are performance-risk indicators, not measured performance.

Consolidate duplicate evidence into no more than one finding per entity, domain, and rule. Compound related findings only when the evidence supports every component. Escalation changes prioritization; it does not strengthen the underlying evidence.

## Safety and authority

The scan is read-only by default. Recommendations may mention changes, but do not execute them in the same run.

Before any later remediation:

1. Show the exact target IDs and proposed actions.
2. Explain impact and reversibility.
3. Obtain explicit user approval for that bounded action set.
4. Re-read the current item state immediately before mutation.
5. Report successes and failures per target.

Never characterize content as safe to delete based only on age, naming, ownership, descriptions, tags, or cumulative view counts.

## Comparison and repeat scans

Compare only scans with compatible scope, policy, identity visibility, evidence semantics, and coverage. Otherwise show the differences side by side without claiming improvement or regression.

Use stable keys of `content_type + stable_id + domain + rule_id` for deltas. Distinguish new findings, resolved findings, severity changes, content no longer visible, and methodology or coverage changes.

Do not write scan state automatically. For a requested baseline, save normalized JSON plus the effective policy, scope, observation time, visible counts, tool/schema notes, and skill version or content hash.

If the user requests a recurring scan, create an automation only through the automation capability available in the current Codex environment. The scheduled prompt must identify the scope and policy, require the Tableau connection, remain read-only, and treat a missing baseline or connection as a reported limitation rather than inventing a comparison.

## Output requirements

Lead with scope, policy, timestamp, visible inventory counts, coverage, optional normalized score and grade, a one-sentence verdict, up to five quick wins, and up to three longer-term recommendations.

Group detailed findings by severity. Each must include content type, name, stable ID or URL, domain, rule, evidence, inference, owner when observed, and proposed next step. Clearly label observations that are not scored.

Never estimate effort or projected score improvement as fact. If useful, label it as an estimate and state assumptions. If the result is partial, place that warning before the score.

For a file output, use the applicable Codex artifact skill. Make HTML self-contained and accessible; escape inserted values. For XLSX, keep Summary, Findings, Coverage, and Inventory sheets. For DOCX, keep an executive summary, prioritized findings, coverage, methodology, and appendix. JSON must follow [references/reporting.md](references/reporting.md).

## Final verification

Before delivery, confirm:

- requested scope and policy are explicit;
- visible/assessed/partial/failed counts reconcile;
- no missing field was treated as a pass or negative;
- usage and timestamps retain their documented semantics;
- every scored finding has traceable evidence;
- comparisons use compatible baselines;
- recommendations are not represented as completed actions;
- no mutation occurred without explicit approval.

Offer a narrower domain deep dive or an independently run Tableau-connected prompt test when useful. Do not claim live validation unless the scan actually ran through the user's connected Tableau MCP server.

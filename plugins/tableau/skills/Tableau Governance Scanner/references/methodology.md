# Governance methodology

## Policy profiles

These defaults are starting points. Echo them and allow the user to override them.

| Rule | Light | Standard | Strict |
|---|---:|---:|---:|
| Modification-age candidate | 365 days | 180 days | 90 days |
| New-content grace period | 30 days | 14 days | 7 days |
| Owner concentration review | 60% | 50% | 30% |
| Sandbox workbook review | 250 | 150 | 100 |
| Workbook sheet-count candidate | 40 | 25 | 15 |

Modification age is not data freshness. A rule match says “review this content,” not “remove it.” Usage thresholds are intentionally absent because a meaningful threshold requires a documented time window and local expectations.

## Domains and classification

### 1. Modification age

Use a documented content modification timestamp. Exempt content within the grace period. Reduce priority for an explicitly identified archive, sandbox, training, or periodic-report context, but preserve the observation.

- beyond threshold: MEDIUM review candidate;
- beyond twice threshold plus documented recent windowed use: HIGH maintenance risk;
- do not escalate from cumulative usage alone.

### 2. Adoption

Prefer usage telemetry with an explicit window. Report metric name, start/end, timezone, and whether it counts views, sessions, users, or another event.

- zero events in a defined, representative window: MEDIUM review candidate;
- high reliance on content with another verified governance gap: HIGH;
- cumulative totals are observations only unless paired with a valid recent window.

### 3. Trust and lineage

- explicitly uncertified published data source: LOW by itself;
- missing description on a datasource: LOW;
- explicit warning or deprecated status: MEDIUM;
- uncertified source with verified broad downstream lineage: HIGH;
- active warning affecting verified relied-upon content: CRITICAL only with direct evidence.

Do not treat every uncertified source as a defect; many organizations certify only shared authoritative sources.

### 4. Naming

Run case-insensitive candidate patterns against returned display names:

| Rule ID | Candidate pattern | Default severity |
|---|---|---|
| `default-sheet` | `^Sheet\s*\d+$` | MEDIUM |
| `copy-prefix` | `^Copy\s+of\s+` | MEDIUM |
| `test-token` | `\btest\b` | HIGH |
| `default-workbook` | `^(New Workbook|Book\d+|Untitled)$` | MEDIUM |
| `collision-suffix` | `\(\d+\)\s*$` | MEDIUM |
| `temporary-token` | `\b(tmp|temp|draft)\b` | MEDIUM |
| `lifecycle-token` | `\b(delete|archive|old|deprecated)\b` | HIGH |

Reduce `test-token` or `temporary-token` to LOW in a clearly identified QA, testing, sandbox, or personal project. Treat lifecycle tokens as evidence to review intent, not permission to remove content. Do not flag “Dashboard 1” unless the user supplies a rule that does.

### 5. Structure and ownership

- content in a project explicitly named Default: MEDIUM organization candidate;
- sandbox count over the selected policy threshold: MEDIUM systemic candidate;
- owner share over threshold: MEDIUM continuity risk; over 60% may be HIGH;
- many projects relative to workbooks: unscored observation unless a local policy defines a ratio.

Never attach blame to an owner. State the portfolio concentration and continuity implication.

### 6. Performance-risk indicators

- sheet count above policy threshold: MEDIUM design-review candidate;
- large file size, live connections, or many sheets plus defined high recent use: HIGH investigation candidate;
- measured latency or failures may support stronger findings when the telemetry and window are explicit.

Do not call a workbook slow from its size, connection type, or sheet count alone.

### 7. Metadata completeness

- observed empty workbook or datasource description: LOW;
- observed empty tags: LOW only if a tagging policy is in scope;
- site-wide adoption below a user-defined target: MEDIUM systemic candidate.

Absence of a property from the response is a coverage gap, not empty metadata.

## Context and compound findings

Use one-level escalation only when two independently evidenced domains combine into materially higher risk. Never escalate above HIGH from hygiene signals alone. Reserve CRITICAL for an evidenced active trust, availability, security, or decision risk requiring prompt attention.

Aggregate repetitive findings for presentation, but retain item-level evidence in JSON or the inventory. Aggregation must not change the normalized score.

## Scoring

Scoring is optional. Prefer counts and coverage when data is partial or policy maturity is low.

For each fully assessed content item, each applicable domain begins at 100 and takes the score associated with its most severe validated finding:

| Worst severity | Domain score |
|---|---:|
| none | 100 |
| LOW | 90 |
| MEDIUM | 75 |
| HIGH | 50 |
| CRITICAL | 0 |

An item's score is the mean of its applicable domain scores. The overall score is the mean of included, fully assessed item scores. Domain scores are means over included, fully assessed items for which that domain applies. This normalization prevents a larger inventory from receiving a lower score merely because it contains more items.

Exclude partial and failed items from scores and show them in coverage. Exclude systemic observations from the score unless they map to explicit assessed entities. Use `scripts/score_governance.py` to calculate consistently.

Grade mapping: A+ 97–100, A 93–96.99, A- 90–92.99, B+ 87–89.99, B 83–86.99, B- 80–82.99, C+ 77–79.99, C 73–76.99, C- 70–72.99, D+ 67–69.99, D 63–66.99, D- 60–62.99, F below 60.

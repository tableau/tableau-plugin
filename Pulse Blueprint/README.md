# Tableau Pulse Blueprint

A Codex skill for designing, reviewing, and optimizing Tableau Pulse metric definitions from business questions, datasource metadata, and existing configurations.

## What it provides

- decision-centered metric blueprints;
- ranked metric-program recommendations;
- evidence-aware audits and optimization plans;
- current-schema handling for Pulse enums and MCP capabilities;
- explicit approval boundaries for creates, updates, deletes, subscriptions, and notifications;
- deterministic audit scoring with partial-coverage protection.

## Example prompts

- `Design a Tableau Pulse metric for monthly recurring revenue.`
- `Recommend Pulse metrics for this pipeline datasource.`
- `Audit my accessible Pulse metric definitions.`
- `Optimize our churn metric for weekly operating reviews.`
- `Compare this Pulse audit with my previous baseline.`

## Package layout

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Core routing, workflow, and mutation boundaries |
| `references/tableau-pulse-capabilities.md` | MCP/API capability and enum handling |
| `references/metric-design.md` | Measure, grain, dimension, insight, and filtered-metric design |
| `references/audit-methodology.md` | Contextual audit rules and scoring |
| `references/audit-scoring-contract.md` | Normalized helper schema |
| `references/output-contract.md` | Blueprint, program, audit, and optimization formats |
| `references/state-and-comparison.md` | Consent-based baselines and monitoring |
| `scripts/score_audit.py` | Deterministic audit scoring engine |
| `scripts/tests/test_score_audit.py` | Success, failure, coverage, and portability tests |

## Local validation

```bash
python -m unittest discover -s scripts/tests -v
python -m py_compile scripts/score_audit.py
```

Run scoring from any directory with absolute paths:

```bash
python /absolute/path/to/pulse-blueprint/scripts/score_audit.py /absolute/path/to/audit.json --pretty
```

The skill does not assume that a particular Tableau MCP is read-only or writable. It discovers current capabilities and requires explicit confirmation before any mutation.

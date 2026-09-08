# Tableau Data Quality Sentinel

A Codex skill for evidence-based, metadata-only quality reviews of published Tableau datasources.

## What it does

- discovers Tableau MCP capabilities at runtime;
- checks schema, naming, likely type/role issues, calculation complexity, documentation, and freshness proxies;
- supports full, alert-only, comparison, changed-only, and delta reports;
- scores normalized findings with a deterministic, tested helper;
- keeps data queries, persistence, scheduling, and Tableau mutations behind explicit approval.

It does **not** infer row-level nulls, duplicates, distributions, PII, or underlying-data freshness from metadata.

## Example prompts

- `Run a metadata quality scan on the Sales datasource.`
- `Compare metadata quality for Orders and Orders v2.`
- `Show only high-priority Tableau datasource issues.`
- `Compare this scan with my prior baseline.`
- `Schedule a weekly alert if the metadata quality score drops.`

## Package layout

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Trigger, workflow, authority boundaries, and routing |
| `references/methodology.md` | Six-domain checks, escalation, and grades |
| `references/tableau-routing.md` | MCP discovery, resolution, and failures |
| `references/scoring-contract.md` | Helper input/output contract |
| `references/output-formats.md` | Report and artifact guidance |
| `references/state-and-automation.md` | Consent-based baselines and scheduling |
| `scripts/score_findings.py` | Deterministic scoring engine |
| `scripts/tests/test_score_findings.py` | Success, failure, and portability tests |

## Local validation

```bash
python -m unittest discover -s scripts/tests -v
python -m py_compile scripts/score_findings.py
```

Run the helper from any directory with absolute paths:

```bash
python /absolute/path/to/tableau-data-quality-sentinel/scripts/score_findings.py /absolute/path/to/findings.json --pretty
```

The skill uses current Tableau tool schemas rather than hard-coded server calls. Missing metadata is `not assessed`, never an automatic pass.

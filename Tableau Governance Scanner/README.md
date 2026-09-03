# Tableau Governance Scanner for Codex

An evidence-first Codex skill for read-only governance audits of Tableau Cloud and Tableau Server through a connected Tableau MCP server.

## What it does

- Inventories visible projects, workbooks, views, and published data sources.
- Reviews modification age, adoption evidence, trust and lineage, naming, organization, ownership concentration, performance-risk indicators, and metadata completeness.
- Produces compact findings with stable IDs, observed evidence, calibrated inference, and next steps.
- Supports project/site comparisons and user-approved baselines.
- Uses normalized scoring so larger sites are not penalized merely for containing more content.

## What it does not do

- It does not equate content modification time with data freshness.
- It does not treat cumulative view counts as recent adoption.
- It does not claim measured performance from structural proxies.
- It does not audit row-level data quality, visual design, or permissions completeness.
- It does not mutate Tableau content during a scan.

## Requirements

- Codex with a connected Tableau MCP server.
- Read access to the intended Tableau scope.
- Optional artifact capabilities for XLSX, DOCX, or HTML outputs.

The available Tableau MCP implementation determines which domains can be assessed. The skill discovers tool schemas at runtime and reports coverage gaps.

## Install

Place the `tableau-governance-scanner` directory in a Codex skills location, then restart or refresh Codex so it discovers the skill.

## Example prompts

```text
Use $tableau-governance-scanner to audit the Finance project with the Standard policy.
```

```text
Run a read-only Strict governance scan for the visible Tableau site and return JSON plus a concise executive summary.
```

```text
Compare these two Tableau projects for governance health. Do not rank them if coverage differs.
```

## Package contents

- `SKILL.md` — Codex operating instructions.
- `agents/openai.yaml` — UI metadata and Tableau MCP dependency.
- `references/methodology.md` — policies, domains, severity, and normalized scoring.
- `references/mcp-and-evidence.md` — capability discovery and evidence semantics.
- `references/reporting.md` — report, JSON, comparison, and baseline contract.
- `scripts/score_governance.py` — deterministic validation and scoring helper.
- `scripts/test_score_governance.py` — unit tests.

## Scoring helper

```bash
python scripts/score_governance.py scan.json --pretty
```

The helper validates the normalized scan contract, excludes partial/failed entities, deduplicates findings, and calculates item-, domain-, and overall scores.

## Safety

All scans are read-only. Any later rename, move, tag, certification, archive, deletion, refresh, or publish action requires a separate bounded proposal and explicit user approval.

## Validation status

Local structure, unit, and static checks can validate the package. A true forward test requires a separate Codex session connected to Tableau MCP; do not interpret local tests as proof of live connector compatibility.

## License

No license is asserted by this conversion. Add one only if you have the right to do so.

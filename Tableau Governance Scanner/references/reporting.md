# Reporting and baseline contract

## Compact report order

1. Title, timestamp, scope, policy.
2. Coverage warning when any content or domain is partial.
3. Score/grade only when defensible, plus a calibrated verdict.
4. Domain table with score or `not assessed`, coverage, and one-line status.
5. Up to five quick wins.
6. Up to three longer-term recommendations.
7. Findings grouped by CRITICAL, HIGH, MEDIUM, LOW.
8. Unscored observations and methodology notes.

Use “candidate,” “signal,” or “review” when the evidence is a proxy. Avoid fabricated effort estimates. A projected score may be calculated only from a named set of hypothetical resolved findings and must be labeled a projection.

## Normalized JSON

```json
{
  "scan_metadata": {
    "observed_at": "2026-09-03T00:00:00Z",
    "scope": {"type": "project", "id": "stable-id", "name": "Finance"},
    "policy": "Standard",
    "policy_overrides": {},
    "visibility_note": "Visible to the connected identity",
    "tool_notes": []
  },
  "entities": [
    {
      "id": "stable-id",
      "type": "workbook",
      "name": "Executive Finance",
      "status": "assessed",
      "include_in_score": true,
      "applicable_domains": ["modification_age", "adoption", "naming", "structure", "performance", "metadata"]
    }
  ],
  "findings": [
    {
      "entity_id": "stable-id",
      "domain": "metadata",
      "rule_id": "missing-description",
      "severity": "LOW",
      "summary": "Description returned as empty",
      "evidence": {"property": "description", "observed_value": "", "observed_at": "2026-09-03T00:00:00Z"},
      "recommendation": "Add purpose, audience, owner, and refresh expectations"
    }
  ],
  "observations": [],
  "coverage": {
    "inventory_complete_for_visible_scope": true,
    "limitations": []
  }
}
```

Allowed entity statuses are `assessed`, `partial`, and `failed`. `include_in_score` is explicit so site/project summary records do not accidentally double-weight content. Findings against partial or failed entities remain visible but are excluded from scores.

## Comparisons

Compare normalized records using `type + id + domain + rule_id`. Before a delta, verify the same intended scope and stable IDs, compatible policies and metric semantics, comparable connected-identity visibility, and similar coverage. If compatibility fails, provide a side-by-side inventory and methodology comparison only.

## File formats

- **Markdown:** compact report order above.
- **JSON:** normalized contract plus computed score summary.
- **XLSX:** Summary, Findings, Coverage, Inventory; freeze headers and use accessible conditional formatting.
- **DOCX:** executive summary, findings, coverage, methodology, appendix.
- **HTML:** self-contained, keyboard accessible, responsive, and safe against inserted markup. Include filters only if they work without external dependencies.

Do not embed credentials, tokens, raw personal data not required by the report, or mutable action controls.

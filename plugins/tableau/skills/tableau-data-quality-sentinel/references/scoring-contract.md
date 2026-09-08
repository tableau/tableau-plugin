# Scoring helper contract

The helper accepts one JSON object:

```json
{
  "scan_id": "optional-label",
  "sources": [
    {"id": "ds-1", "name": "Orders", "status": "profiled", "assessed_domains": ["schema", "naming", "types", "calcs", "metadata", "freshness"]},
    {"id": "ds-2", "name": "Restricted", "status": "failed", "assessed_domains": []}
  ],
  "findings": [
    {
      "source_id": "ds-1",
      "domain": "types",
      "rule_id": "type.date_as_string",
      "severity": "high",
      "evidence_key": "created_date",
      "summary": "Created Date is stored as STRING",
      "additional_domains": ["metadata"],
      "systemic": false,
      "observation": false
    }
  ]
}
```

Required source keys are `id` and `name`. `status` is `profiled`, `reused`, or `failed` and defaults to `profiled`. `assessed_domains` defaults to all six domains for a non-failed source and must be empty for a failed source. List it explicitly for partial metadata so unavailable domains receive null scores rather than false passes.

Required finding keys are `source_id`, `domain`, `rule_id`, `severity`, `evidence_key`, and `summary`. Severity is `critical`, `high`, `medium`, or `low`. Domains are `schema`, `naming`, `types`, `calcs`, `metadata`, and `freshness`.

Optional finding keys are `additional_domains`, `systemic`, `combined_critical`, and `observation`. The helper rejects unknown source references, duplicate source IDs, invalid enum values/types, and unknown keys. It deduplicates scored findings by source, rule, and evidence key, retaining the highest effective severity. Observations are returned separately.

Output includes methodology version, coverage, findings, observations, source scores, domain scores, overall score, and grade. Failed sources are never scored. A `reused` source also requires top-level `"methodology_version": "1.0"`; otherwise the helper rejects the comparison.

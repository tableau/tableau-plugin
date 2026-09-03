# Audit methodology

Audit relative to the metric's stated decision contract and the fields actually returned. A finding is scored only when the evidence establishes a concrete configuration risk. Otherwise record an observation or `not assessed`.

## Scored checks

| Rule ID | Condition | Default severity |
| --- | --- | --- |
| `identity.generic_name` | explicit name is empty, placeholder-like, or cannot distinguish the metric | MEDIUM |
| `identity.no_description` | description property is present and empty, leaving measure/scope ambiguous | MEDIUM |
| `data.missing_measure` | full definition explicitly lacks a measure | CRITICAL |
| `data.missing_time_dimension` | full definition explicitly lacks required time configuration | CRITICAL |
| `data.invalid_field_reference` | definition references a field absent from a complete, matched datasource schema | HIGH |
| `aggregation.incompatible` | aggregation contradicts the documented metric definition or data grain | HIGH |
| `aggregation.running_total_misuse` | running total is applied to a rate, average, or point-in-time measure without justification | HIGH |
| `format.currency_unspecified` | explicit currency format lacks required currency context | MEDIUM |
| `configuration.no_granularity` | full configuration exposes an empty supported-granularity set | HIGH |
| `configuration.invalid_enum` | stored value is rejected by the active tool/product schema | HIGH |
| `insights.none_for_required_use` | all applicable insights are explicitly disabled despite a stated alert/explanation requirement | MEDIUM |
| `privacy.unsafe_row_label` | row-level display exposes sensitive/raw identifiers to the intended audience | HIGH |

Adjust severity only with explicit impact evidence. Deduplicate identical rule/evidence pairs.

## Contextual observations

These are not automatically defects:

- count of allowed dimensions or filtered metrics;
- neutral favorable direction;
- one/no comparison;
- absent goals;
- absent row-level configuration;
- disabled individual insight types;
- datasource update timestamp as a freshness proxy;
- lack of a year-over-year comparison;
- metric definition with zero accessible metrics.

Promote an observation to a scored finding only when the metric's decision contract shows a concrete failure—for example, no comparison on a metric explicitly intended to report period-over-period change. Document that rationale.

## Scoring

Start at 100 per fully assessed definition. Subtract 10/5/2/0.5 for CRITICAL/HIGH/MEDIUM/LOW and bound to 0–100. A partial definition may receive a provisional score but is excluded from the composite. Failed definitions receive no score. The composite is the mean of fully assessed definition scores.

Grade bands: A+ 97–100; A 93–96.5; A− 90–92.5; B+ 87–89.5; B 83–86.5; B− 80–82.5; C+ 77–79.5; C 73–76.5; C− 70–72.5; D+ 67–69.5; D 63–66.5; D− 60–62.5; F below 60.


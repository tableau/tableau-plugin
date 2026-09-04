# Metric design

## Decision contract

A useful metric has an owner, a question, an action, a cadence, and an interpretation. Define:

| Property | Evidence needed |
| --- | --- |
| Measure | field/calculation and business definition |
| Aggregation | sum, count, distinct count, average, ratio, or supported custom behavior |
| Time dimension | field, timezone/calendar context, and grain |
| Favorable direction | up, down, neutral, or context-dependent |
| Comparison | previous period, prior year/fiscal period, target, or none |
| Dimensions | breakdowns that plausibly explain movement |
| Fixed filters | scope intrinsic to the definition |
| Goal | authoritative target, owner, period, and effective date |

Confirm numerator/denominator behavior for rates, deduplication for counts, null/zero treatment, and additive versus non-additive measures. Running totals fit accumulating measures, not rates, averages, or point-in-time balances without special justification.

## Datasource evidence

Verify measure/time/dimension fields against metadata when available. A numeric type does not prove a useful measure; a string may be an ID, label, or encoded value. Do not infer distinct counts or value sets unless the tool returns them or an authorized query measures them.

Choose breakdown dimensions because they explain actionably different drivers. IDs, free text, sensitive attributes, and extremely granular fields are usually poor breakdowns, but use observed semantics rather than a universal numeric threshold.

## Granularity and comparisons

Match the primary grain to decision cadence and data latency. Offer additional grains only when interpretation remains valid. Previous-period and prior-year comparisons answer different questions; seasonality may justify year-over-year, but it is not mandatory for every metric.

## Insights and row-level settings

Select insight types from the live schema based on measure behavior, history, breakdown dimensions, entitlements, and the decision. Driver/detractor insights need meaningful dimensions; forecast/pace features need suitable history and may require specific entitlements or configurations; row-level outliers need a stable entity ID and safe display name.

Do not enable unsupported or irrelevant insights. Do not expose sensitive row-level identifiers or names without considering audience and permissions.

## Filtered metrics

Recommend filtered variants only for durable, owned cohorts that merit separate following or goals. Avoid duplicating every dimension member. State the filter, owner/audience, cadence, and why a saved variant is better than ad hoc exploration.


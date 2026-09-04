# Output contract

## Metric blueprint

1. decision owner, question/action, and cadence;
2. definition name/description and datasource identity;
3. measure, aggregation, time dimension, grain, running-total behavior, and fixed filters;
4. granularities, comparisons, favorable direction, number format, and optional goal;
5. allowed dimensions with a one-line reason for each;
6. insight settings with applicability rationale and entitlement/schema caveats;
7. row-level settings only when a safe natural entity exists;
8. justified filtered variants;
9. evidence status, blockers, and implementation checklist.

Use exact enum/API values only when confirmed by the current tool schema; otherwise pair a plain-language recommendation with `verify in target environment`.

## Metric program

Rank recommendations by decision value, definitional clarity, data readiness, explainable dimensions, and overlap with existing definitions. Default to the top five for readability, but honor a request for more. Include “not recommended” candidates only when the exclusion prevents a likely mistake.

## Audit

Lead with scope and coverage: assessed, partial, failed, and unassessed properties. Then show composite and per-definition scores, highest-severity findings, observations, and concrete UI/API-ready changes. A score is not a claim that the underlying data is correct.

## Optimization

Use columns for property, current, recommended, evidence, benefit/tradeoff, and change class (`required`, `optional`, `blocked`). Keep IDs internal unless needed for disambiguation or implementation.

## Final checks

- Every field reference is observed or labeled unverified.
- Aggregation, grain, time behavior, and favorable direction are explicit.
- No goal, cardinality, insight availability, entitlement, or metric value is invented.
- Existing overlap and audit coverage are represented honestly.
- No mutation is implied unless it actually ran after confirmation.


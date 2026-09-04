# State and comparison

Use only when the user asks to save, compare, resume, or monitor Pulse audits.

## Baseline contents

Store the minimum necessary: methodology version, scan timestamp/scope, stable definition IDs, normalized finding keys, scores, and coverage. Avoid raw definitions, owner details, datasource connection data, formulas, metric values, or sensitive row-level fields unless the user explicitly needs them.

Confirm the destination before writing. If no persistent capability exists, offer an exportable JSON baseline rather than claiming continuity.

## Delta

Re-inventory current definitions. Match stable IDs and normalized finding keys. Report new, resolved, persistent, added, removed, and inaccessible items. A removed item may be hidden by permissions; avoid declaring deletion without evidence. Do not calculate score deltas when methodology versions or assessed-property coverage differ materially.

## Recurring monitoring

Scheduling is a separate external mutation. Confirm scope/site, cadence, timezone, notification threshold, baseline destination, and authorization to create the task. Scheduled instructions must be portable and must not embed credentials, machine-specific paths, or assumed tool names. In unattended runs, report missing access rather than prompting or mutating Pulse.


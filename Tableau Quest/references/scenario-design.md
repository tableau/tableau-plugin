# Scenario design

## Intake settings

Use defaults rather than a long questionnaire when the player has not expressed preferences.

| Setting | Options | Default |
|---|---|---|
| Audience | executive, analyst, developer, mixed | mixed |
| Experience | beginner, intermediate, advanced, expert | intermediate |
| Focus | publishing/governance, metric conflict, performance/adoption, reliability, security, UX/trust, organizational politics, migration, executive demo, silent decay | performance/adoption |
| Tone | straightforward, political thriller, sci-fi, dark fantasy, noir, prestige office drama, office comedy | straightforward |
| Depth | Blitz, Quick, Standard, Deep | Blitz |

Tone changes prose, not Tableau mechanics, risk, evidence, or evaluation.

## Scenario DNA

Combine only as many incident families as the selected depth can sustain:

- **Publishing and governance:** wrong project, split sources of truth, ownership gaps, permission inheritance, certification conflict.
- **Metric conflict:** incompatible definitions, date logic, filter context, grain mismatch, schema changes.
- **Performance and adoption:** slow loading, scale changes, excessive complexity, abandoned workflows, mobile constraints.
- **Refresh and reliability:** credentials, late data, refresh collisions, incremental logic, upstream changes.
- **Security and compliance:** row-level security, unintended exposure, lineage requests, sensitive tooltips, takedown decisions.
- **UX and trust:** confusing filters, contradictory labels, misleading encoding, dense dashboards, oversimplification.
- **Organizational conflict:** leadership change, team rivalry, governance friction, budget pressure, ownership disputes.
- **Migration and platform change:** environment differences, unsupported assumptions, permission-model shifts.
- **Executive demo:** latency, challenged definitions, unreconciled KPIs, high-visibility failures.
- **Silent decay:** shrinking use, reorganization, missing ownership, documentation loss, metric drift.

Blitz uses one incident family. Quick uses one or two. Standard uses two or three. Deep may combine three to five, but each thread must remain traceable.

## Realism anchors

Every scenario establishes:

- a named fictional stakeholder and role;
- a named workbook, dashboard, or data source;
- at least one concrete volume, timing, usage, or performance number;
- a deadline and prior history;
- a constraint that rules out an easy universal answer.

For fictional scenarios, numbers are plausible story facts. For Field Quest, observed facts must retain their source semantics and timestamps. Do not invent data volumes from field counts or workbook metadata.

## Choice quality

Each option must represent a distinct strategy. Useful tensions include:

- diagnose first vs. stabilize first;
- narrow scope vs. protect completeness;
- communicate uncertainty vs. promise a date;
- local repair vs. systemic redesign;
- governance escalation vs. team autonomy;
- short-term performance vs. maintainability;
- restrict access vs. preserve availability.

Avoid “correct action / reckless action / joke action.” A risky choice may be rational under time pressure; a cautious choice may carry delivery or trust costs.

## Consequences

Track immediate effects and one to three deferred consequences. A deferred consequence should surface two to five decisions later, depending on depth. It must follow causally from a choice.

Escalation levels:

1. individual concern;
2. team visibility;
3. executive or cross-functional visibility;
4. formal incident or strategic consequence.

Hard failure is earned by a pattern or a clearly high-impact decision, never random chance. Recovery remains possible, although not every scar disappears.

## Experience calibration

- **Beginner:** visible signals, limited jargon, one or two stakeholders, one-layer Tableau constraints.
- **Intermediate:** technical and organizational interaction, two to four stakeholders.
- **Advanced:** incomplete evidence, competing incentives, cross-domain effects.
- **Expert:** complex cascades, minimal narration of implications, broad stakeholder ecosystem.

Do not equate difficulty with obscure syntax. Difficulty comes from ambiguous evidence and competing obligations.

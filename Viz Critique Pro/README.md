# Viz Critique Pro

Viz Critique Pro is a Codex skill for reviewing and scoring Tableau dashboards and views. It combines rendered-image evidence, optional Tableau MCP metadata, a seven-domain weighted rubric, deterministic score calculation, and prioritized design recommendations.

## What changed in the Codex edition

- Uses Tableau capabilities discovered in the active MCP runtime instead of assuming fixed tool names.
- Accepts direct screenshots without requiring Tableau access.
- Keeps review work read-only and separates critique from workbook editing.
- Corrects the original framework's 95% weight total to 100% by assigning Textual Elements a 10% weight.
- Calculates scores, caps, half-even rounding, and tiers with a tested local helper.
- Delivers useful findings immediately instead of forcing a second response and format selection.
- Labels static-image limits for interactivity and accessibility.

## When to use it

- Review or score a Tableau dashboard.
- Critique a workbook view from a Tableau URL, name, identifier, or screenshot.
- Compare the design quality of multiple views.
- Produce prioritized, evidence-based visualization recommendations.

Use a workbook-authoring skill when the requested deliverable is a modified `.twb` or `.twbx`. This skill does not validate source data or business performance.

## Requirements

- Codex with this skill installed or available.
- Python 3.10+ for deterministic scoring.
- Optional Tableau MCP access for content resolution, metadata, and view renders.

## Installation

Install the complete `viz-critique-pro` directory through your normal Codex skill or plugin workflow. Keep `SKILL.md`, `agents/`, `references/`, and `scripts/` together.

## Example prompts

```text
Use $viz-critique-pro to review this Tableau dashboard screenshot and give me the full seven-domain scorecard.
```

```text
Use $viz-critique-pro to find the “Executive Sales” view through Tableau MCP, score it, and prioritize the three highest-impact improvements.
```

```text
Compare these two Tableau views for an operations audience. Keep the review read-only.
```

## Scoring model

| Domain | Weight |
| --- | ---: |
| Audience Adaptation | 15% |
| Message Alignment | 10% |
| Optimal Chart Usage | 20% |
| Strategic Layout and Storytelling | 25% |
| Effective Color | 15% |
| Textual Elements | 10% |
| Typography and Readability | 5% |

The scoring helper validates all seven domains, bounded adjustments, domain caps, overall caps, decimal half-even rounding, safety status, and tier assignment. Run it from any directory by resolving the package path explicitly:

```bash
SKILL_DIR="/absolute/path/to/viz-critique-pro"
python3 "$SKILL_DIR/scripts/score_viz.py" "/absolute/path/to/assessment.json"
```

See `references/assessment-schema.md` for valid JSON examples.

## Evidence standard

Every score and material deduction must cite something visible in the render or explicitly supplied in metadata. Tooltip behavior, filter responsiveness, keyboard access, and screen-reader structure are not inferred from a static image.

## Development

Run tests and the active Codex skill validator before release:

```bash
python -m unittest discover -s scripts/tests -v
```

## License

No license has been assigned by this package. Add one before public redistribution.

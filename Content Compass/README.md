# Tableau Content Compass

Tableau Content Compass is a Codex skill for finding existing Tableau views, workbooks, datasources, projects, and Pulse metrics that match a business question. It uses Tableau MCP metadata plus a deterministic evidence-ranking helper to separate strong matches, partial coverage, and likely content gaps.

## Codex conversion highlights

- Discovers the active Tableau MCP capabilities and schemas instead of assuming Claude-era tool names.
- Supports scoped projects, project discovery, or bounded full-site search without always forcing an intake question.
- Removes automatic memory reads and writes.
- Keeps discovery read-only and separates it from workbook building, critique, documentation, and data querying.
- Ranks normalized candidates with executable, tested logic.
- Treats permission failures as unknown coverage rather than proof that content does not exist.
- Uses only canonical identifiers and links returned by Tableau.

## Installation

Install the complete `tableau-content-compass` directory through your normal Codex skill or plugin workflow. Keep `SKILL.md`, `agents/`, `references/`, and `scripts/` together.

## Requirements

- Codex with the skill available.
- A Tableau MCP server exposing one or more content-search or metadata capabilities.
- Python 3.10+ for deterministic relevance ranking.

## Example prompts

```text
Use $tableau-content-compass to find dashboards that show regional sales trends in the Commercial Analytics project.
```

```text
Do we already have Tableau content for customer churn? Search views, datasources, and Pulse metrics.
```

```text
Find the finance project first, then show me its strongest bookings and renewal content.
```

## Ranking helper

Normalize Tableau metadata using `references/ranking-schema.md`. From the cloned package root, run:

```bash
cd tableau-content-compass
python3 scripts/rank_content.py "/absolute/path/to/candidates.json"
```

The helper scores explicit metadata evidence, filters results below 15, groups matches into confidence tiers, and returns the two strongest signals for each explanation.

## Confidence tiers

| Score | Tier | Interpretation |
| ---: | --- | --- |
| 60–100 | High | Strong evidence that the content addresses the question |
| 35–59 | Medium | Partial or adjacent coverage |
| 15–34 | Low | Tangential but potentially useful |
| Below 15 | Hidden | Insufficient evidence to recommend |

## Development

Run tests and the active Codex skill validator before release:

```bash
python -m unittest discover -s scripts/tests -v
```

## License

No license has been assigned by this package. Add one before public redistribution.

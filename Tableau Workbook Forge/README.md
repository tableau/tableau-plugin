# Tableau Workbook Forge

Tableau Workbook Forge helps Codex inspect and safely modify Tableau `.twb` and `.twbx` workbooks. It uses declarative schema-aware XML changes, safe package extraction, exact diffs, deterministic repackaging, stronger structural validation, and an optional read-only Tableau MCP verification layer.

## When to use it

- Apply a deliberate visual restyle to an existing workbook.
- Update observed run text and styles, worksheet names, and existing dashboard zone geometry.
- Add other worksheet, dashboard-zone, or KPI structures only from compatible donor evidence.
- Implement issues from a supplied dashboard critique.
- Produce a validated `.twb` or `.twbx` deliverable.
- Apply the same bounded change across a user-authorized workbook batch.

Use a calculation-specific skill for isolated calculated fields and a critique skill when no workbook output is requested.

## Requirements

- Codex with this skill installed or available.
- Python 3.10+ and `lxml` for local workbook helpers.
- A compatible Tableau runtime for opening, rendering, or optional publication-based checks.

Local XML validation does not by itself prove Tableau rendering compatibility.

## Installation

Install the entire `tableau-workbook-forge` directory through your normal Codex skill or plugin workflow. Keep `SKILL.md`, `agents/`, `references/`, and `scripts/` together.

## Example prompts

```text
Use $tableau-workbook-forge to convert this packaged workbook to the supplied dark palette while preserving every datasource and embedded asset.
```

```text
Apply these dashboard critique findings to my workbook and return a validated .twbx plus a concise changelog.
```

```text
Add a KPI row using the attached compatible workbook as the structural donor. Do not publish anything.
```

## Local helpers

Safely extract a packaged workbook into a new run directory:

```bash
python scripts/workbook_tools.py extract input.twbx scratch/run-001
```

Validate a working `.twb`:

```bash
python scripts/workbook_tools.py validate scratch/run-001/working.forge.twb --json validation.json
```

Inventory a workbook, preview and apply a versioned edit plan, and save an exact diff:

```bash
python scripts/workbook_tools.py inspect scratch/run-001/working.forge.twb --json inventory.json
python scripts/workbook_tools.py apply-plan scratch/run-001/working.forge.twb edit-plan.json --dry-run --json preview.json
python scripts/workbook_tools.py apply-plan scratch/run-001/working.forge.twb edit-plan.json --json changes.json
python scripts/workbook_tools.py diff source.twb scratch/run-001/working.forge.twb --json diff.json
```

Package the complete extracted tree after replacing its original workbook member:

```bash
python scripts/workbook_tools.py package \
  scratch/run-001/extracted \
  scratch/run-001/working.forge.twb \
  Workbook/book.twb \
  outputs/result.twbx
python scripts/workbook_tools.py validate-package outputs/result.twbx --baseline input.twbx --json package-validation.json
```

The helpers reject unsafe archives, do not force-delete conflicting output, and verify that unrelated package members remain byte-for-byte unchanged.

## Safety model

- Source workbooks are never overwritten.
- Unknown XML structures require a compatible donor or verified schema evidence.
- Tableau MCP is read-only by default and grounds cloud identity or before-state evidence when relevant.
- Publishing is optional and requires explicit authorization, a collision-safe scratch target, and cleanup tracking.
- Validation claims distinguish local XML checks from actual Tableau opening or rendering.

## Development

Run helper tests and the active Codex skill validator before release:

```bash
python -m unittest discover -s scripts/tests -v
```

## License

No license has been assigned by this package. Add one before public redistribution.

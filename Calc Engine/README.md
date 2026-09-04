# Codex Calc Engine

Codex Calc Engine helps Codex create, debug, translate, and optimize Tableau calculated fields. It combines field discovery, grain analysis, safe authoring, stored-formula read-back, and behavioral checks so a successful API response is not mistaken for a correct calculation.

## When to use it

- Turn a business definition into a Tableau calculated field.
- Repair mixed-aggregation, LOD, null, or table-calculation problems.
- Translate supported SQL expressions into Tableau semantics.
- Review an expensive calculation without changing its meaning.
- Author a dependency-ordered batch of calculations.

Use a workbook-authoring skill for dashboard layout, visual styling, or broad `.twb`/`.twbx` changes.

## Requirements

- Codex with this skill installed or available.
- A Tableau Desktop agent or MCP runtime for live discovery, authoring, and behavioral verification.
- Python 3.10+ for the optional local formula checker.

Without Tableau access, the skill can still draft formulas, but it will label storage and behavior as unverified.

## Installation

Install the entire `codex-calc-engine` directory through your normal Codex skill or plugin workflow. Keep `SKILL.md`, `agents/`, `references/`, and `scripts/` together.

## Example prompts

```text
Use $codex-calc-engine to create a 90-day retention rate using [User ID], [Order Date], and [First Order Date].
```

```text
Debug this Tableau calculation. It returns “cannot mix aggregate and non-aggregate”: SUM([Sales]) / [Customer Target].
```

```text
Translate this SQL window calculation into Tableau and explain the required table-calculation addressing.
```

## Local formula checks

Normalize a candidate formula for comparison:

```bash
python scripts/calc_checks.py normalize --file formula.txt
```

Check a stored formula for common transport problems:

```bash
python scripts/calc_checks.py check --file stored-formula.txt --expect-operator '<'
```

The checker is intentionally side-effect free. Tableau remains the authority for formula validity and workbook behavior.

## Verification model

The skill distinguishes three outcomes:

1. **Drafted** — a formula was produced without live authoring.
2. **Stored** — Tableau's stored definition was read back and matched.
3. **Behaviorally verified** — representative workbook results were checked at the intended grain.

Blocked checks remain blocked; the skill does not infer success from missing runtime access.

## Development

Run the helper tests and active Codex skill validator before release:

```bash
python -m unittest discover -s scripts/tests -v
```

## License

No license has been assigned by this package. Add one before public redistribution.

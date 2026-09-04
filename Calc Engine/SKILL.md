---
name: codex-calc-engine
description: Author, debug, translate, or optimize Tableau calculated fields with field discovery, safe authoring, formula read-back, and behavioral verification. Use for one or more calculated fields; do not use for general dashboard construction or workbook-wide XML editing.
---

# Codex Calc Engine

Create correct Tableau calculated fields and verify what Tableau actually stored. Adapt the workflow to the available Tableau runtime; tool names vary across Desktop agent and MCP installations.

## Resolve the request

Identify the requested mode from the user's goal:

- **Create:** turn a business definition into one or more calculated fields.
- **Debug:** explain and repair an existing formula or observed result.
- **Translate:** express supported SQL logic as Tableau calculations.
- **Optimize:** reduce unnecessary row-level work, repeated expressions, or expensive nesting without changing meaning.
- **Batch:** handle an explicitly requested set of calculations in dependency order.

Route workbook layout, dashboard styling, or broad XML changes to a workbook-authoring skill when one is available. A request for both calculations and workbook changes may be split, but do not discard either part.

## Discover before authoring

Use the available Tableau capabilities to inspect fields, existing calculations, parameters, datasource identity, and workbook state. Resolve ambiguous captions before writing. If Tableau access is unavailable, provide a clearly labeled formula draft and state that storage and behavior remain unverified.

Classify each calculation as row-level, aggregate, LOD, or table calculation. Walk dependencies recursively and identify every boundary where row-level and aggregate expressions meet. Read [calculation-guide.md](references/calculation-guide.md) when the request involves LOD expressions, table calculations, SQL translation, mixed aggregation, or performance work.

For multiple dependent calculations, order them topologically. Ask a question only when grain, null behavior, tie handling, partitioning, or another unresolved choice would materially change the result.

## Author safely

Use the calculation-authoring capability exposed by the active Tableau runtime. Pass literal formula text; do not pre-escape XML entities. Use parameter references in the syntax accepted by the runtime and preserve explicit user naming.

Before creating a new field, compare the intended formula with existing calculations. The bundled helper can normalize formulas for comparison without changing bracketed field names:

```bash
python scripts/calc_checks.py normalize --file formula.txt
```

Do not overwrite or delete an existing calculation unless the user authorized that exact change and the runtime supports it. If an authoring API creates on caption collision, choose a collision-safe name and report the duplicate rather than pretending the original was replaced.

## Verify

After each write, read the stored formula back through the Tableau runtime. Compare the stored definition with the intended definition and check for double-escaped operators, doubled parameter qualification, truncation, or an unexpected caption collision:

```bash
python scripts/calc_checks.py check --file stored-formula.txt --expect-operator '<'
```

Then exercise the calculation in a disposable worksheet or equivalent query context using representative dimensions and measures. Verify the behavior that matters for the request: null handling, range, aggregation level, filter response, table-calculation addressing, and tie behavior. Do not treat successful creation as behavioral validation.

If the runtime cannot create a scratch view or query results, mark behavioral verification as blocked. Do not fabricate samples or infer success from the authoring response.

## Report

Return the calculation name and formula, whether it was created or only drafted, read-back status, behavioral status, and any assumptions that affect meaning. For batches, include dependency order and per-calculation results. Provide a manual paste block when authoring is unavailable or fails safely.

Do not claim a calculation is verified unless both the stored definition and requested behavior were checked. A blocked check remains blocked.

## Failure boundaries

- Missing or ambiguous fields: stop before mutation and resolve the field or ask the user.
- Datasource unavailable: provide a draft only if useful and label it unverified.
- Workbook validation blocks a write: report the blocker; do not edit cached worksheet XML to force acceptance.
- Transient worksheet application failure: make at most one retry when the runtime indicates a transient condition. A differently named disposable worksheet may be attempted once when naming is the suspected cause.
- Partial batch failure: preserve successful results, stop dependent calculations, and report the dependency break.

For implementation changes to this skill, run `python -m unittest discover -s scripts/tests -v` and the active skill validator.

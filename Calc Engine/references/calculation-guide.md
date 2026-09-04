# Tableau calculation guide

Read the sections relevant to the requested calculation. These are decision aids, not substitutes for inspecting the active workbook and Tableau version.

## Order of operations

The practical ordering that most often changes calculation behavior is:

1. extract and datasource filters;
2. context filters;
3. FIXED LOD expressions;
4. dimension filters;
5. INCLUDE and EXCLUDE LOD expressions;
6. measure filters;
7. table calculations.

Use this ordering to explain why a FIXED result may ignore an ordinary dimension filter or why a table calculation sees only marks remaining in the view. Verify version-specific behavior in the target workbook when a feature depends on Tableau release details.

## Grain and aggregation

- Row-level expressions operate per record and cannot be mixed directly with aggregate expressions.
- Aggregate calculations consume aggregates or expressions valid at the aggregate level.
- A FIXED, INCLUDE, or EXCLUDE expression returns a value at its declared grain but may still require aggregation when used beside another aggregate.
- Do not wrap an already aggregate calculation in another aggregate merely to silence an error; inspect its dependency chain first.
- Use `MIN` or `MAX` only when the value is invariant at the visible partition. Use `ATTR` only when `*` is an acceptable signal of multiple values.

Record why an aggregation boundary preserves business meaning. A syntactically valid formula can still be wrong at the requested grain.

## Choosing an LOD expression

- **FIXED:** use when the result must remain stable at a declared dimensional grain and should be computed before ordinary dimension filters.
- **INCLUDE:** use when a finer dimension is needed for calculation and the result must then aggregate to the view.
- **EXCLUDE:** use when a view dimension should be removed from the calculation grain.

Avoid nested FIXED expressions until the inner and outer grains have been written down explicitly. Context filters can change the records available to FIXED; sets and ordinary dimension filters may not interact the same way.

## Table calculations

Table calculations depend on the marks in the view. Define:

- addressing dimensions: the direction in which the calculation advances;
- partitioning dimensions: where the calculation restarts;
- sorting and tie behavior;
- what should happen at partition edges.

For ranking, choose deliberately among competition, modified competition, dense, unique, and percentile behavior. For `LOOKUP`, decide whether missing offsets should remain null or use a fallback. A correct formula with incorrect addressing is not a correct result.

## Null and boolean behavior

Tableau's three-valued logic can propagate nulls through boolean expressions. Decide whether null means unknown, false, or a separate category. Use explicit null handling only when it matches the business definition.

When testing a boolean or categorical LOD in a worksheet, ensure it is treated as a discrete field if the intended display is categorical. Inspect the actual pill and resulting values rather than assuming the runtime chose the correct role.

## SQL translation

Translate semantics, not syntax:

| SQL construct | Tableau direction |
| --- | --- |
| row expression or `CASE` | row-level calculated field |
| grouped aggregate | aggregate calculation or LOD at the intended grain |
| window function | table calculation when it depends on the visible partition |
| correlated grain lookup | LOD plus an explicit aggregation boundary |

SQL ordering, null rules, and window frames may not map one-to-one. State any mismatch and test it against representative data.

## Performance review

Prefer simpler work at the earliest sensible layer while preserving meaning:

- reuse a clear existing calculation instead of duplicating it;
- avoid repeated expensive string or date expressions;
- reduce unnecessary nested LODs;
- avoid converting a stable row-level condition into a table calculation;
- treat datasource-side changes as a separate recommendation unless the user authorized them.

Never claim an optimization improved runtime without measuring it in the target environment.

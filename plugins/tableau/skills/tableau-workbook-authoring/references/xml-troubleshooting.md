# TWB XML troubleshooting

Read only for an XML construct not represented in the workbook or after local
or remote validation fails.

The bundled validator auto-detects the workbook version and selects the matching
XSD under `resources/schemas/`. Its exit codes are:

- `0`: structurally valid
- `1`: structurally invalid; fix the reported line/element
- `2`: setup problem, missing file/dependency, or unsupported workbook version

Use `--json` only when machine-readable errors help automate a repair.

A clean XSD pass is necessary but not sufficient. It may not catch calculated
field formula errors, dangling datasource/worksheet references, or invalid
connection attributes. For a TWB, `publish-workbook` validates inline and
returns structured `errors`/`warnings` with line, column, element, and
message — use those to make a targeted repair. For a TWBX, Tableau validates
the packaged extract during publish itself, so a failure surfaces as a
publish error rather than a structured findings list; rely on the local XSD
validator and the package-completeness checks before publishing.

When schema inspection is required, select the schema matching the workbook's
declared version and search for the failing element. Do not read unrelated XSD
sections or upgrade the workbook version solely to use a newer schema.

### Filter-reference integrity

When adding or changing a filter, never infer the `groupfilter level` from
the raw field name.

1. Locate or create the target `<column-instance>` in the worksheet's
   `<datasource-dependencies>`.
2. Use that instance's exact `name` consistently:
   - the outer `<filter column='...'>` references the fully qualified instance;
   - `groupfilter level='...'` uses the exact unqualified instance name.
3. Copy the closest existing filter pattern from the same TWB whenever possible.
4. Before packaging, verify every categorical filter's `column`, `level`, and
   `<slices>` references resolve to declared datasource dependencies.
5. Treat XSD validation as structural only. A passing XSD check does not verify
   field, filter, datasource, or dashboard cross-references.

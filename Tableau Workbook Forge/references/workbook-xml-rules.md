# Tableau workbook XML rules

Apply only rules relevant to the user's request and the workbook's observed structure. Tableau XML varies by release and feature; use a compatible known-good donor for additions not covered here.

## General invariants

- Parse with external entity resolution and network access disabled.
- Preserve namespaces, unknown elements, embedded assets, datasource files, and unrelated ordering.
- Do not add elements merely because a remembered template contains them.
- Reopen and validate the final packaged workbook rather than only the pre-package working file.
- Never hand-edit a source `.xlsx` or other embedded datasource as an incidental workbook-style fix.

## Text and color

- Text color commonly belongs on a `<run fontcolor='…'>` element. Do not invent `<format attr='font-color'>` when the target content model does not allow it.
- Audit all existing values before a broad replacement. Stroke, border, background, and text colors serve different roles and should not be globally conflated.
- Preserve the existing palette unless the user requests a restyle. Explicit brand values override generic dark/light defaults.
- Transparent and opaque backgrounds that look equivalent on white can diverge after a theme change; verify worksheet and dashboard background parity.
- Accessibility claims require an actual contrast or render check. A hex substitution alone is not proof.

## Structural edits

- Remove an `<external>` container when its required child content is removed; do not leave a malformed empty block.
- Keep workbook child collections in the order demonstrated by a compatible workbook. In known structures, `<actions>` precedes `<worksheets>`.
- Avoid undocumented `<sort>` children inside `<column-instance>` and undocumented `<manual-sort>` elements unless a compatible donor proves the structure.
- For a single physical table, prefer the relation form already used by a compatible datasource rather than synthesizing federated structure.
- Preserve derivation and aggregation metadata from a donor with the same semantic role.

## KPI and dashboard additions

KPI cards combine worksheet-level mark and text styling with dashboard zone geometry. Do not create a zone from coordinates alone: copy and adapt a compatible zone subtree, update stable identifiers without collision, and validate every referenced worksheet.

For a requested dark theme, a partially transparent KPI tile may be a starting point only when the workbook has no design token or user value. Verify the result visually when rendering is available.

## From-scratch workbooks

A new workbook requires more than well-formed XML. Ground datasource relations, metadata records, worksheets, dashboards, windows, and repository locations in a compatible donor or a runtime-generated starter. If those inputs are unavailable, create a design plan or ask the user for a starter workbook instead of claiming an invented skeleton is Tableau-compatible.

## Validation expectations

Local checks should cover the properties touched by the edit, including:

- XML parses without recovery mode;
- exactly one intended workbook is packaged;
- required worksheet and dashboard references resolve;
- no malformed empty structures were introduced;
- changed style values appear at the intended targets;
- unrelated package members retain their bytes;
- packaged output reopens and yields the same validated workbook member.

Opening or rendering in Tableau is a separate compatibility gate. Publishing is optional and authorization-bound.

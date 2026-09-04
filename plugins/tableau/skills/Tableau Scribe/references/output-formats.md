# Output formats

## In chat and Markdown

Use ordinary headings, compact tables, and lists. Avoid ornamental separators. Keep evidence labels close to uncertain claims. For a standalone Markdown artifact, include title, scope, generated/verified timestamp, content sections, and coverage note.

## DOCX

Use the current document-authoring workflow. Apply semantic heading levels, accessible tables, repeating table headers where useful, page numbers, restrained typography, and a concise provenance/coverage section. Render and visually inspect the final document before delivery. A table of contents is useful only for a sufficiently long document.

## XLSX dictionary

Use the current spreadsheet workflow. One row per field/metric with filters and frozen headers. Suggested columns: display name, category, business definition, technical meaning, aggregation/grain, directionality, inputs, caveats, evidence status, and source reference. Validate formulas, column widths, wrapping, and sheet names.

## Existing-document update

Resolve the exact artifact and preserve its identity/version when supported. Retain established terminology and structure unless incorrect or the user requests redesign. Compare current evidence with existing claims, update only supported content, and include a short change summary.

## Final checks

- Target and coverage are explicit.
- Visible, metadata-confirmed, inferred, and unknown claims are distinguishable.
- Metrics retain aggregation, grain, units, denominator, and comparison caveats.
- Interactions and refresh cadence are not inferred as facts.
- No sensitive sample values or unnecessary IDs/owner details appear.
- Artifact rendering and file integrity were validated.


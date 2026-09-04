---
name: tableau-workbook-forge
description: Inspect, safely edit, diff, validate, and package Tableau .twb and .twbx workbooks with schema-aware XML operations and optional read-only Tableau MCP grounding or render verification. Use when the deliverable is a modified Tableau workbook; do not use for review-only requests or isolated calculated fields.
---

# Tableau Workbook Forge

Create or modify Tableau workbook artifacts while preserving package contents and validating the resulting XML. Treat existing workbook structure and a known-good donor from the same Tableau generation as stronger evidence than remembered XML patterns. Use Tableau MCP as a context and verification layer, not as evidence that an unavailable download, local-open, or publish operation succeeded.

## Resolve scope

Use this skill for a requested `.twb` or `.twbx` deliverable: restyling, adding supported workbook elements, applying a supplied critique, or building from a datasource and explicit requirements.

Route isolated calculated fields to a calculation skill and review-only requests to a critique skill when available. For mixed requests, preserve all requested work and sequence specialized parts when practical.

Ask one focused question only when a missing design, datasource, compatibility, or output-format choice would materially change the artifact. Do not interpret “improve this workbook” as permission to publish, replace the source file, change branding, or restructure unrelated views.

## Work on a safe copy

For `.twbx`, create a fresh run directory and use the bundled helper to reject traversal paths, links, excessive archive expansion, and ambiguous workbook members:

```bash
python scripts/workbook_tools.py extract input.twbx scratch/run-001
```

The helper requires Python 3 and `lxml`. If `lxml` is unavailable, use another installed XML parser only when it can disable external entity resolution and preserve the workbook faithfully; otherwise report the local-validation blocker.

For `.twb`, copy the source into the run directory before editing. Never write into the source archive or overwrite the user's original workbook. Inventory worksheets, dashboards, datasources, zones, and existing style values before planning changes:

```bash
python scripts/workbook_tools.py inspect working.twb --json inventory.json
```

## Plan from evidence

Describe each intended XML change by target, current state, desired state, and evidence. Read [workbook-xml-rules.md](references/workbook-xml-rules.md) for supported style and structure rules and [edit-plan-schema.md](references/edit-plan-schema.md) before using the declarative editor.

Use a known-good workbook or verified schema evidence for structural additions. If the required element is unsupported or version-specific and no reliable donor exists, stop that portion and explain the limitation. Do not invent Tableau XML from appearance alone.

Preserve unrelated elements, embedded assets, datasource files, custom shapes, extensions, and ordering. Apply the smallest change that satisfies the request. A prior changelog is context, not proof of current state.

## Apply and validate

Use an XML-aware parser for element or attribute changes. Plain text replacement is acceptable only for an exact, audited attribute value where structural ambiguity is impossible.

Prefer a versioned edit plan for supported changes. Preview its exact targets without changing the working file, then apply it atomically:

```bash
python scripts/workbook_tools.py apply-plan working.twb edit-plan.json --dry-run --json preview.json
python scripts/workbook_tools.py apply-plan working.twb edit-plan.json --json changes.json
```

The supported operations are scoped run-style replacement, exact run-text replacement, dashboard zone geometry updates, and worksheet rename with known-reference updates. The helper rejects unsupported attributes, zero or unexpected matches, ambiguous zone targets, invalid geometry, name collisions, and worksheet references it cannot safely rewrite. It also retains a narrow compatibility command for exact font-color substitutions on `<run>` elements:

```bash
python scripts/workbook_tools.py replace-run-color working.twb '#000000' '#E6E6E6'
```

After each logical edit group, validate the working workbook:

```bash
python scripts/workbook_tools.py validate working.twb --json validation.json
```

Validation must include well-formed XML, forbidden or malformed structures relevant to the applied rules, required workbook collections, and requested postconditions. Reopen packaged output and validate the exact `.twb` member that will be delivered. Local XML checks do not prove that Tableau will render the workbook correctly.

Capture the exact source-to-working difference and both file hashes:

```bash
python scripts/workbook_tools.py diff source.twb working.twb --json diff.json
```

For `.twbx`, repackage the complete extracted tree deterministically with the edited workbook replacing only the original member:

```bash
python scripts/workbook_tools.py package scratch/run-001/extracted working.twb path/in/archive.twb outputs/result.twbx
python scripts/workbook_tools.py validate-package outputs/result.twbx --baseline input.twbx --json package-validation.json
```

The baseline comparison must show that no unrelated package member was added, removed, or changed.

## Use Tableau MCP when relevant

Read [mcp-verification.md](references/mcp-verification.md) before using Tableau MCP. Use available read-only tools to resolve the canonical cloud object, confirm workbook/view metadata, and capture a before render when that evidence helps the requested change. A matching title or local filename is not a verified mapping; use canonical identifiers from the connector.

Open or render the edited local artifact only when the active runtime exposes that capability. If it does not, report local validation and the MCP before-state independently. Do not imply an after render was performed.

Publishing to Tableau Server or Cloud is an external mutation and always requires explicit user authorization, an exact user-approved scratch target, collision-safe temporary names, and tracked cleanup. Never overwrite an existing workbook as a verification shortcut. Do not download, query, or publish merely to perform a local style edit.

If publishing was not authorized, skip it without lowering a locally valid artifact to failure. If a temporary publication is used, record whether cleanup succeeded and leave unresolved cleanup as a visible blocker.

## Report

Return the workbook artifact, the edit plan or concise changelog, source/output hashes, the exact diff, and validation results. Separate:

- local XML and package checks;
- MCP-grounded source identity and before-state evidence;
- successful opening or after rendering in Tableau;
- any optional publication-based check;
- blocked or untested claims.

Do not claim visual parity, performance improvement, or Tableau compatibility unless that property was tested in the applicable runtime.

## Failure boundaries

- Unsafe or ambiguous archive: stop before extraction.
- Multiple `.twb` members: ask the user to identify the intended workbook.
- Unknown XML structure: require a compatible donor or omit that change.
- Validation failure: keep the failed working copy in scratch and do not replace a prior good output.
- Package conflict: choose a new output path; do not add a force-delete path.
- Partial batch failure: preserve validated outputs and report each failed workbook independently.

For implementation changes, run `python -m unittest discover -s scripts/tests -v` and the active skill validator.

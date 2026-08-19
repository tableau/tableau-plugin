---
name: tableau-workbook-authoring
description: Use when creating, modifying, templating, validating, or publishing Tableau .twb workbooks, including selecting visualization samples and mapping fields into Tableau bookmark templates.
---

# Tableau Workbook Authoring

## Overview

The plugin ships a resource catalog (chart templates, worked examples, a
reference corpus) and a CLI, `../../scripts/tableau_resources.py` —
relative to this skill's own directory, `skills/tableau-workbook-authoring/`
— that discovers, inspects, and safely transforms `.twb` workbooks. This
skill is the required entry point for any workbook build, edit, or publish
that touches those resources.

## Workflow

1. Inspect the existing workbook (or prepare a `<datasource>` definition
   file for a fresh one).
2. Run `list` before choosing a chart — never guess a resource id.
3. Run `inspect` before mapping fields — it returns the required field,
   parameter, and datasource contract for that resource. Each `--map` must
   point at a target field of the same datatype family; see the resource
   guide's *Datatype compatibility* section.
4. Transform: `inject` adds a resource into an existing workbook;
   `instantiate` builds a new workbook from the bundled starter.
5. Treat `tier: reference` resources (examples, corpus entries, schema docs)
   as inspiration only. Only `tier: executable` resources are accepted by
   `instantiate`/`inject`; the CLI rejects the rest.
6. Run `validate` on the transformed workbook — an absolute structural
   check of that whole file (exit 0 clean, 1 lists errors, 2 means the
   command itself could not read or validate it).
7. Run the `validate-workbook-package` skill — the pre-publish gate.
8. Publish only with the validation receipt that gate returns.

## Quick reference

```bash
python3 ../../scripts/tableau_resources.py list --tier executable --query "<intent>"
python3 ../../scripts/tableau_resources.py inspect <resource-id>
python3 ../../scripts/tableau_resources.py instantiate <resource-id> \
  --datasource-definition <file> --output <file> --worksheet-name <name> \
  --map SOURCE=TARGET --param NAME=VALUE
python3 ../../scripts/tableau_resources.py inject <resource-id> \
  --input <existing.twb> --output <file> --datasource <name> \
  --worksheet-name <name> --map SOURCE=TARGET --param NAME=VALUE
python3 ../../scripts/tableau_resources.py validate --input <file>
```

## Common mistakes

- Skipping `list`/`inspect` and guessing a resource id or field mapping —
  `inject`/`instantiate` fail closed on any unknown or missing mapping.
- Passing a `reference`-tier resource to `inject`/`instantiate` — it is not
  renderable; use it only as inspiration for a hand-authored viz.
- Treating local `validate` as sufficient for publishing — it is an
  **absolute** structural check on the file you pass it, not the
  pre-publish gate. (Delta tolerance — letting a workbook's pre-existing
  errors pass through — is internal to `inject`'s own pre-write check;
  `instantiate` checks its output against the clean bundled starter. The
  standalone `validate` command never tolerates anything.) Always run
  `validate-workbook-package` before `create-and-publish-workbook`.
- Assuming `inject`'s `--datasource` accepts a display caption — it is the
  target datasource's internal `name` attribute from the input workbook's
  own `<datasources>` container. A wrong value fails closed and lists
  every available name.
- Running a command after changing directories without first resolving
  `../../scripts/tableau_resources.py` to an absolute path — that path is
  relative to this skill's own directory, not to your current shell
  location.

Detailed CLI flags, mapping/parameter syntax, and failure recovery:
references/resource-guide.md.

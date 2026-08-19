---
name: validate-workbook-package
description: Pre-flight a data-app workspace into a .twbx receipt. Use after authoring workspace files and before create-and-publish-workbook.
---

# Validate Workbook Package

Call `validate-workbook-package` after `scaffold-data-app` / `upsert-data-app-files` and **before** `create-and-publish-workbook`. It packages in memory and does not publish.

**Prerequisite:** if the workbook was built or edited from the resource
catalog (see `tableau-workbook-authoring`), run the local
`../../scripts/tableau_resources.py validate --input <file>` check first and
resolve any reported errors. That command is an absolute structural check
on the whole file — unlike the delta check `inject` performs internally
before writing — and it does not replace this pre-publish gate.

## Invoke

- `appId` — workspace handle from scaffold
- `workbookName` — workbook display name

## Result

- `ok: true` + `validationId` — structurally valid and under 64 MB. Pass `validationId` unchanged to `create-and-publish-workbook`.
- `ok: true` does **not** mean the viz is good.
- `ok: false` — structure, missing asset refs, or size. Fix files and call again.
- Re-validate if the workspace changes after a receipt.
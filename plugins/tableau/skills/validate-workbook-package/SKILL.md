---
name: validate-workbook-package
description: Pre-flight a data-app workspace into a .twbx receipt. Use after authoring workspace files and before create-and-publish-workbook.
---

# Validate Workbook Package

Call `validate-workbook-package` after `scaffold-data-app` / `upsert-data-app-files` and **before** `create-and-publish-workbook`. It packages in memory and does not publish.

## Invoke

- `appId` — workspace handle from scaffold
- `workbookName` — workbook display name

## Result

- `ok: true` + `validationId` — structurally valid and under 64 MB. Pass `validationId` unchanged to `create-and-publish-workbook`.
- `ok: true` does **not** mean the viz is good.
- `ok: false` — structure, missing asset refs, or size. Fix files and call again.
- Re-validate if the workspace changes after a receipt.
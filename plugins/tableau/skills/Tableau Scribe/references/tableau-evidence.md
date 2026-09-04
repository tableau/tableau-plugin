# Tableau evidence

Use the capabilities exposed by the current Tableau MCP. Tableau's REST APIs can return workbook/view metadata, view images, and view data, while Metadata API coverage differs by object and permissions. The MCP may expose only a subset.

Official references:

- Workbooks and views methods: <https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_workbooks_and_views.htm>
- Tableau resource LUIDs: <https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_concepts_luid.htm>
- Metadata API datasource type: <https://help.tableau.com/current/api/metadata_api/en-us/reference/datasource.doc.html>

## Evidence classes

- **User-provided:** authoritative for intent/preferences, not automatically for current Tableau state.
- **View image:** visible title, labels, chart forms, displayed filters/values, annotations, and layout at the rendered state.
- **View/workbook metadata:** returned names, project, owner, timestamps, descriptions, tags, and usage only when present.
- **Datasource metadata:** returned fields, types, roles, formulas, parameters, logical tables, and lineage only when present.
- **Authorized value query/export:** returned values within the selected filters/grain; do not generalize beyond the query.

## Resolution

Treat all IDs and URLs as opaque until the active tool confirms their accepted form. Match by exact stable ID when available, otherwise exact name plus project/owner/site. Ask when ambiguity remains. Follow server pagination for the promised scope.

## Visual interpretation

Inspect the rendered image at sufficient detail. Do not infer hidden filters, actions, tooltips, accessibility conformance, axis truncation beyond visible bounds, or underlying field linkage. A blank render may reflect filters, loading, permissions, or data state—not necessarily a stale extract.

## Failure handling

- Inventory/authentication failure: explain that live target resolution could not complete.
- One inaccessible resource: continue with the remaining evidence and identify that coverage gap.
- Missing image: omit visual claims rather than recreating the layout from metadata.
- Missing datasource metadata: mark definitions as visual/user-language only.
- Partial metadata: treat omitted properties as `not assessed`, not empty.
- Transient/rate-limit response: follow retry guidance or retry once with bounded backoff.

Place uncertainty where readers use the affected information. Keep diagnostic details concise and sanitize raw errors.


# Evidence ledger contract

The validator accepts:

```json
{
  "artifact_type": "dashboard_documentation",
  "query_authorized": false,
  "target": {"id": "view-1", "name": "Sales Overview", "kind": "view"},
  "sources": [
    {"id": "image-1", "type": "view_image", "scope": "default rendered state"},
    {"id": "meta-1", "type": "view_metadata", "scope": "view metadata response"}
  ],
  "records": [
    {"id": "r1", "subject": "dashboard", "attribute": "title", "value": "Sales Overview", "status": "observed", "sources": ["image-1"]},
    {"id": "r2", "subject": "dashboard", "attribute": "audience", "value": "sales managers", "status": "inferred", "sources": ["image-1"], "note": "KPI and regional breakdown emphasis"},
    {"id": "r3", "subject": "dashboard", "attribute": "refresh cadence", "value": null, "status": "unknown", "sources": [], "note": "not exposed by available metadata"}
  ]
}
```

`artifact_type` is `dashboard_documentation` or `datasource_dictionary`. Target kind is `view`, `workbook`, or `datasource`. Source types are `user_provided`, `view_image`, `view_metadata`, `workbook_metadata`, `datasource_metadata`, `lineage`, or `queried_data`.

Observed records require at least one source. Inferred records require sources and a note explaining the inference. Unknown records require null value, no sources, and a note. A `queried_data` source is rejected unless `query_authorized` is true.

Record IDs and source IDs must be unique. A subject/attribute pair may appear only once; contradictory duplicates are rejected rather than silently merged. Unknown keys, unreferenced sources, and invalid types are rejected.

Output returns the normalized target, sources, records, and counts by evidence status/source type. It is an internal drafting aid, not a user-facing citation system.

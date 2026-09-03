# Tableau MCP and evidence mapping

## Capability discovery

Tableau MCP implementations differ. Inspect the live tool catalog and each relevant schema. Select read tools by described behavior, not guessed names. Record server identity when exposed, content types and stable identifiers, filters and page controls, field semantics, visibility limits, errors, and incomplete pages.

Never invoke a write-like tool during a governance scan. If the catalog is ambiguous, stop before calling it.

## Canonical internal fields

Normalize only observed properties:

| Internal field | Meaning |
|---|---|
| `id` | Stable Tableau identifier as returned |
| `type` | project, workbook, view, datasource, or other returned type |
| `name` | Display name |
| `project_id` | Stable containing-project identifier |
| `owner_id` | Stable owner identifier |
| `created_at` | Documented creation/publish timestamp |
| `modified_at` | Documented content modification timestamp |
| `usage` | Metric value plus metric name and exact time semantics |
| `certification` | Explicit returned certification status |
| `description` | Returned description; preserve absent versus empty |
| `tags` | Returned tags; preserve absent versus empty |
| `lineage` | Explicit upstream/downstream IDs and relation type |

Keep the raw source property name beside normalized fields when ambiguity is possible.

## Product-semantics guardrails

Current Tableau REST documentation exposes view/workbook modification timestamps and can optionally return a view's `totalViewCount`. The latter is a total count, not a recent time window. Tableau REST list methods can paginate, but limits differ by method; follow the live MCP schema and response rather than imposing one global page size.

Tableau Metadata API can support discovery and lineage analysis when exposed by the connected MCP server and permitted for the identity. Its existence in Tableau does not prove that a particular MCP server provides it.

Official references:

- [Workbooks and Views Methods](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_workbooks_and_views.htm)
- [Paginating Results](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_concepts_paging.htm)
- [Tableau Metadata API](https://help.tableau.com/current/api/metadata_api/en-us/index.html)

## Degradation

| Failure | Response |
|---|---|
| Core inventory unavailable | Stop; state connection/access blocker |
| One content type unavailable | Continue only if useful; mark its domains not assessed |
| One page or batch fails | Retry only if safe and likely transient; otherwise preserve partial coverage |
| Rate limit | Honor server guidance; avoid fixed sleep claims |
| Missing property | Do not synthesize it; mark the affected rule not assessed |
| Unresolved join | Keep both records and report the join gap |

Do not repeatedly retry authorization failures. Do not translate API visibility into a claim about total site inventory.

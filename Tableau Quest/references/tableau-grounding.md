# Tableau MCP grounding

## Consent and scope

Use live Tableau metadata only when the player chooses Field Quest and consents to connection use. Confirm:

- site or project scope;
- whether actual content names may appear;
- whether owner identities must be anonymized;
- whether the scenario may use metadata-derived risk signals.

The connected identity’s visibility bounds the evidence. Never imply a complete-site view unless the tools and permissions establish one.

## Capability discovery

Inspect the available Tableau MCP catalog and schemas. Prefer the smallest set of read operations that can find relevant workbooks, views, projects, published data sources, fields, relationships, tags, descriptions, modification timestamps, and documented usage signals.

Do not assume a fixed tool name, page size, response property, or enabled feature. Tableau MCP site settings can include or exclude tools and constrain result limits. Follow the current tool schema and continuation mechanism.

Never call tools that create or update MCP settings, content, permissions, tags, refreshes, publications, or other Tableau state for a quest.

## Evidence semantics

- Stable IDs are for internal joins and citations, not narrative texture.
- A content modification timestamp is not proof of source-data freshness.
- A total view count is cumulative unless an explicit window is documented.
- A missing response property means not observed, not false or empty.
- Workbook structure and connection type may suggest a performance investigation; they do not prove latency.
- Ownership metadata does not establish a person’s title, responsibility, performance, or intent.
- Metadata access does not authorize row-level data access.

Keep a private evidence ledger containing the source tool, observed property, value, timestamp, and whether it is used directly or fictionalized. The narrative should not expose raw responses.

## Narrative transformation

Safe transformations include:

- retaining a workbook name when the user approved real names;
- turning a technical field label into a generic business concept;
- using an observed workbook count as setting context with its observation time;
- converting a metadata risk signal into a fictional complication clearly separated from observed facts.

Do not place real owners into negative fictional roles. Use fictional names and roles. Do not reproduce sensitive field names, credentials, URLs, IDs, or data values.

## Failure behavior

If the connection, permission, tool, or field is unavailable, remain accurate. Offer:

1. continue using the player’s written context;
2. continue with a fully fictional scenario;
3. stop and troubleshoot the connection outside the quest.

Do not silently downgrade a requested live-grounded quest into one that appears live.

## Official references

- [Tableau MCP documentation](https://tableau.github.io/tableau-mcp/)
- [Tableau MCP REST methods](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_tableau_mcp.htm)
- [Workbooks and Views REST methods](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_workbooks_and_views.htm)
- [Tableau Metadata API](https://help.tableau.com/current/api/metadata_api/en-us/index.html)

Use the live MCP schema as the operational source of truth; product documentation does not guarantee that a particular server exposes every capability.

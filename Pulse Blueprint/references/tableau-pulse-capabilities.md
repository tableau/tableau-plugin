# Tableau Pulse capabilities

Tableau's product APIs and a connected Tableau MCP are different capability surfaces. Official Tableau REST documentation describes create, read, update, and delete operations for Pulse metric definitions and metrics, but a particular MCP may expose only a subset. Always inspect current tool schemas.

Official references:

- Pulse REST methods: <https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_pulse.htm>
- Create Pulse metrics in Tableau: <https://help.tableau.com/current/online/en-us/pulse_create_metrics.htm>

## Capability routing

- Inventory/list capability: resolve accessible definitions and coverage.
- Definition/metric detail capability: retrieve current configuration for audit or optimization.
- Datasource inventory/metadata capability: verify fields, types, roles, and datasource identity.
- Insight capability: use only when the user requests current insights; it is not required for a blueprint.
- Mutation capability: use only for an explicitly requested and immediately confirmed write.

Inspect schemas for pagination, IDs, supported view/detail modes, required access, product/server availability, and allowed values. Never copy tool names from examples into instructions as if universal.

## Enum handling

Use values declared by the active tool schema or returned configuration. Product enum sets evolve; for example, official Pulse documentation includes insight types beyond older fixed lists. If producing an offline blueprint without a live schema, show the user-facing setting plus `API value: verify in target environment` rather than inventing an exact enum.

## Errors and coverage

- Authentication failure on inventory: stop the live audit and explain the missing access.
- One inaccessible definition/datasource: continue and report it as failed coverage.
- Partial object: audit only observable properties and list unassessed checks.
- Transient/rate-limit response: follow server retry guidance or retry once with bounded backoff.
- A definition referencing an unseen datasource may reflect permissions rather than staleness; report both possibilities.


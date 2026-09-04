# Tableau MCP grounding and verification

Use Tableau MCP when it adds relevant source context or runtime evidence. Treat it as a read-only verification layer unless the user explicitly authorizes an available external mutation.

## Resolve identity

1. Search or list using the connector's available tools.
2. Resolve the workbook, project, and view by canonical IDs returned by Tableau.
3. Record the site/project path and canonical identifiers used.
4. Do not assume that a local filename or matching title identifies the same cloud object.

If no unambiguous mapping exists, say so and continue with local-only editing when the supplied artifact is sufficient.

## Before and after evidence

- Capture source metadata and a before render when useful and supported.
- Verify that a render is an actual visualization, not a sign-in page, error, placeholder, or stale unrelated view.
- Compare like with like: use the same view, viewport/aspect ratio, filter state, and parameter state when possible.
- An after render is valid only if the active runtime can open the local artifact or the user explicitly authorized a collision-safe temporary publication using an available tool.
- If no after-render path exists, report the gap. Do not claim visual parity from XML validation.

## Mutation boundary

Publishing, overwriting, deleting, changing permissions, or modifying content on Tableau is outside the read-only verification layer. It requires explicit user authorization, an exact scratch target, a new collision-safe name, and cleanup tracking. Never overwrite an existing workbook as a test shortcut.

Do not download, query, or publish solely to perform a local style edit when the user already supplied the workbook.

## Testing notes

Record connector calls, outcomes, and relevant errors separately from local helper results. When timing a skill test, keep connector latency in the dedicated latency section so transport behavior is not scored as skill quality.

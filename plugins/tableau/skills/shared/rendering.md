# Rendering published Tableau content in the Codex side panel

Shared by `tableau-workbook-authoring`, `tableau-workbook-templating`, and
`tableau-content-viewer` — all three end with "show the user this piece of
content," and this is that step. Update this file rather than duplicating it
if the rendering approach changes.

You need 1 thing going in: the content's **URL** to fall back to
(the same call usually also returns a `url`).

## URL Construction

Tableau content URLs follow the below structures:

### Pulse Metric: `https://HOST/pulse/site/SITE/metrics/METRIC_ID`

Leave the URL as is

### View:  `https://HOST/#/site/SITE/views/WORKBOOK/VIEW` - View

If we get a view URL, rewrite the URL to this pattern: `https://HOST/t/SITE/views/WORKBOOK/VIEW`
For example:

`https://prod-useast-a.online.tableau.com/#/site/example/views/Superstore/Overview`

becomes:

`https://prod-useast-a.online.tableau.com/t/example/views/Superstore/Overview`

Remove the `/#/site/` application-shell route. The final URL must not contain `#/site/`.

If Tableau already returns a direct URL containing either:

- `/t/SITE/views/WORKBOOK/VIEW`, or
- `/views/WORKBOOK/VIEW`

preserve that route.

Merge the following query parameters into the direct view URL:

- `:showVizHome=no`
- `:embed=yes`
- `:toolbar=no`

For a workbook request, also use:

- `:tabs=yes` when the workbook exposes tabs.
- `:tabs=no` when the workbook does not expose tabs OR if the request targets 1 specific view.

When the URL has no existing query string, the result should resemble:

`https://HOST/t/SITE/views/WORKBOOK/VIEW?:showVizHome=no&:embed=yes&:toolbar=no&:tabs=yes`

Do not append Tableau parameters after a URL fragment.

## Rendering

Tableau MCP's mcp-apps tool group (`render-interactive-viz`, `get-embed-token`) is feature-gated. 

### Option A
If the tool call comes back as unknown/disabled, 
1. Select the built-in in-app Browser (`iab`).
2. Do not substitute Chrome, an external browser, or web search.
3. Reuse a suitable existing in-app Browser tab when appropriate; otherwise
   create a new tab.
4. Navigate the tab to the re-constructed Tableau URL.
5. Inspect the visible page state to verify that Tableau started loading.
6. Keep the Browser open in the right-side panel for the user.

Do not merely print the URL or return it as a Markdown link when Browser
navigation is available.

### Option B
If the tool call comes back successfully, return as-is.

# Render published Tableau content

Render the published or target Tableau view using the least expensive path
that satisfies the user’s intent. Reuse workbook IDs, view IDs, and URLs
already resolved during the current task.

## Choose the render path

Rendering: try these in order. Move to the next step only if the current one
is unavailable or fails. Reuse workbook IDs, view IDs, and URLs already
resolved during the current task.

1. Built-in browser. Call `mcp__Tableau__get-view`
   for the URL, then open it (as a direct `/t/SITE/views/...` URL; see
   [Build a direct view URL](#build-a-direct-view-url)) with `open_in_codex`, or `mcp__node_repl__js` if that doesn’t work.
   If Tableau asks the user to sign in, tell them to sign in there; that
   still counts as success.
2. Static image (last resort). Use `mcp__Tableau__get-view-image` only if step 1 fails.
   Give the user the full direct `/t/SITE/views/...` URL as a Markdown
   hyperlink, e.g. `[<view name>](https://HOST/t/SITE/views/WORKBOOK/VIEW?...)`,
   then call `mcp__Tableau__get-view-image` once with `viewId` (the resolved
   view LUID) and `format: "PNG"` and handle the result as described in
   [Download the PNG immediately](#download-the-png-immediately).

Never use `mcp__Tableau__get-view-image` for a “show/open/render” request unless the
user asks for an image or the step above has failed.

## Download the PNG immediately

`mcp__Tableau__get-view-image` returns either an inline image or a
`resource_link` holding a short-lived presigned URL. The URL expires quickly,
so any delay between receiving it and fetching it can lose the render.

- **Before calling**, pick the output path, e.g.
  `<temp-dir>/<view-luid>.png`, so nothing is left to work out afterwards.
- **Inline image:** it's already in the chat; don't download it.
- **`resource_link`:** downloading it is the very next action. Don't call
  any other tool, read a reference file, write to the user, or reason about
  the result first. Download with a direct HTTP client, not a browser:

  ```bash
  curl -sSfL -o "<temp-dir>/<view-luid>.png" "<url>"
  ```

  If `curl` isn't available, use
  `python3 -c "import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" "<url>" "<temp-dir>/<view-luid>.png"`.
- **After downloading**, check the file is a non-empty image, then show it
  to the user: embed it in the reply with Markdown using its absolute path, e.g. `![<view name>](/absolute/path/to/render.png)`. Don't present it as a file attachment or open it in a side panel.
- **If the download fails because the URL expired**, call
  `mcp__Tableau__get-view-image` once more and download the new URL
  straight away. This is the only exception to calling it once. If that also
  fails, treat the PNG path as failed.

## Resolve the target view

Prefer IDs and URLs returned by the current task’s publish result.

When `mcp__Tableau__publish-workbook` returns a list of views:

1. Select the view whose name matches the worksheet or dashboard created or
   edited for the user.
2. Use that view’s LUID directly.
3. Do not search for the workbook or list its views again.

If the publish result contains only a workbook and default-view ID, use the
default view unless the user requested another named view.

Search or list views only when the current task has not already resolved the
target view.

## Build a direct view URL

Convert a Tableau application-shell URL:

`https://HOST/#/site/SITE/views/WORKBOOK/VIEW`

to:

`https://HOST/t/SITE/views/WORKBOOK/VIEW`

Preserve URLs already using `/t/SITE/views/...` or `/views/...`.

For Pulse metric URLs such as:

`https://HOST/pulse/site/SITE/metrics/METRIC_ID`

preserve the URL unchanged.

For a specific view, merge these query parameters before any fragment:

- `:showVizHome=no`
- `:embed=yes`
- `:toolbar=no`
- `:tabs=no`

Example:

`https://HOST/t/SITE/views/WORKBOOK/VIEW?:showVizHome=no&:embed=yes&:toolbar=no&:tabs=no`

Use `:tabs=yes` only when intentionally rendering a tabbed workbook rather
than one specific view.

## Open in the in-app browser

1. Call the first available in-app browser tool once with the direct view URL.
2. If it reports unknown, unavailable, or disabled, try the next one in the
   list; otherwise don't call another.
3. Treat a returned success as confirmation that the view opened; don't call
   the same tool again for the same URL within this task.
4. Don't substitute web search, a guessed URL, or a render surface not listed
   above.

## Failure handling

- Attempt each available render path at most once.
- Use this fallback order:
  in-app browser (`open_in_codex`, `mcp__node_repl__js`) → hyperlink plus `mcp__Tableau__get-view-image` PNG.
- Do not retry tools that report unknown, unavailable, or disabled.
- If the PNG also fails, still give the direct URL hyperlink and briefly
  identify which rendering capabilities were unavailable.
- Do not let rendering failure obscure a successful workbook publication.

## Success criteria

Rendering is complete when one of the following is true:

- the direct view URL is open in the in-app browser;
- the user has the direct URL as a hyperlink and a PNG of the view shown in
  the chat; or
- every render path failed and the user has the direct URL hyperlink with a
  concise explanation.

Report the rendered view’s name and preserve the workbook LUID, view LUID,
project LUID, and direct URL for follow-up edits.

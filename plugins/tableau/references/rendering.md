# Render published Tableau content

Render the published or target Tableau view using the least expensive path
that satisfies the user’s intent. Reuse workbook IDs, view IDs, and URLs
already resolved during the current task.

## Choose the render path

Use one render attempt per available path and reuse workbook IDs, view IDs,
and URLs already resolved during the current task.

1. If `render-interactive-viz` is callable, call it once:
   - use the resolved view LUID with `objectType: "view"` when a specific
     view is known;
   - use the workbook LUID with `objectType: "workbook"` only when no
     specific view can be resolved.
2. Return a successful interactive render as-is.
3. If the interactive-render tool is missing, unknown, disabled, or fails,
   call `open_in_codex` with the direct view URL (below).
4. If `open_in_codex` is unavailable or fails, call `get-view-image` once
   with:
   - `viewId`: the resolved view LUID;
   - `format: "PNG"`;
5. Display the returned PNG directly to the user.
6. Do not retry an unavailable rendering tool or repeat a failed path.

Use `open_in_codex` before `get-view-image` even for “render,” “show,” and
“preview” requests. The PNG route is the final fallback when interactive
rendering and `open_in_codex` are both unavailable.

## Resolve the target view

Prefer IDs and URLs returned by the current task’s publish result.

When `publish-workbook` returns a list of views:

1. Select the view whose name matches the worksheet or dashboard created or
   edited for the user.
2. Use that view’s LUID directly.
3. Do not search for the workbook or list its views again.

If the publish result contains only a workbook and default-view ID, use the
default view unless the user requested another named view.

Search or list views only when the current task has not already resolved the
target view.

## `open_in_codex` fallback

`open_in_codex` is the preferred fallback after `render-interactive-viz`. Use
it before attempting `get-view-image`.

### Build a direct view URL

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

### Call and verify

1. Call `open_in_codex` once with the direct view URL.
2. Treat its returned success as confirmation that the view opened; do not
   call it again for the same URL within this task.
3. Do not substitute web search, an external browser, or a guessed URL.

## Failure handling

- Attempt each available render path at most once.
- Use this fallback order:
  `render-interactive-viz` → `open_in_codex` → `get-view-image` with PNG.
- Do not retry tools that report unknown, unavailable, or disabled.
- If `open_in_codex` reports unavailable or blocked, do not try another
  render surface; continue to the PNG fallback.
- If all applicable render paths fail, return the direct Tableau URL and
  briefly identify which rendering capabilities were unavailable.
- Do not let rendering failure obscure a successful workbook publication.

## Success criteria

Rendering is complete when one of the following is true:

- the requested Tableau view is displayed interactively;
- a PNG render of the requested view is displayed to the user; or
- rendering capabilities are unavailable and the user receives the direct
  URL with a concise explanation.

Report the rendered view’s name and preserve the workbook LUID, view LUID,
project LUID, and direct URL for follow-up edits.

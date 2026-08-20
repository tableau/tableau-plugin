# Rendering published Tableau content in the Codex side panel

Shared by `tableau-workbook-authoring` and `tableau-content-viewer` — both
end with "show the user this piece of content," and this is that step.
Update this file rather than duplicating it if the rendering approach
changes.

You need two things going in: the content's **LUID** (`id` from whatever MCP
tool call surfaced it — a publish result, a search/list result, etc.) and its
**`objectType`** (`"workbook"` or `"view"`), plus a **URL** to fall back to
(the same call usually also returns a `url`).

This is gated by Tableau's `mcp-apps` tool group
(`render-interactive-viz`, `get-embed-token`) — feature-gated on Tableau's
side. If the tool call comes back as unknown/disabled, tell the user their
site likely doesn't have that feature enabled yet; this isn't something the
plugin can work around.


## Rendering priority

When the user asks to render, show, open, or preview Tableau content:

1. First call `render-interactive-viz` so Tableau can render directly in the
   Codex right-side panel.

2. If that tool is unavailable or does not render, use the
   `browser:control-in-app-browser` skill and open the Tableau view URL in
   Codex’s built-in browser.

   - Reuse an existing in-app-browser tab when appropriate.
   - Append Tableau embed parameters:
     `?:embed=yes&:toolbar=no&:tabs=no&:showVizHome=no`
   - Allow the user to authenticate inside the built-in browser if needed.
   - Follow the Browser skill’s setup and browser-selection instructions;
     do not hardcode its underlying control tools.

3. Do not invoke `open`, Safari, Chrome, `webbrowser.open`, or another
   operating-system browser unless the user explicitly requests an external
   browser.

4. If neither the Tableau panel renderer nor the built-in browser is
   available, provide the Tableau URL and clearly state that it could not be
   rendered in-app.

An explicit browser choice from the user always overrides this default.
# Tableau for Codex

A Codex plugin that connects Codex to Tableau's [hosted MCP server](https://tableau.github.io/tableau-mcp/docs/hosted-tableau-mcp)
(`https://mcp.tableau.com`), with skills for exploring existing Tableau
content, rendering a specific view/workbook so you can see it, and
**generating or modifying workbooks on the fly**.

There's no official Tableau plugin for Codex yet (Tableau's docs say one is
"coming soon"), so this fills that gap in the meantime.

## Layout

```
.agents/plugins/marketplace.json   # local marketplace catalog (for testing/dev)
plugins/tableau/
  .codex-plugin/plugin.json                    # plugin manifest
  .mcp.json                                    # bundles the hosted Tableau MCP server
  skills/tableau-analytics/                    # read-oriented: querying/exploring content
  skills/tableau-content-viewer/               # find a view/workbook and render it, no data querying or editing
  skills/tableau-workbook-authoring/           # generate/modify workbooks by editing TWB XML
  skills/shared/rendering.md                   # shared render-in-side-panel steps, used by both of the above
  schemas/<YYYY_R>/twb_<YYYY.R.0>.xsd           # per-Tableau-version TWB XSD schemas (2018.1-2026.2)
  scripts/validate_workbook.py                 # validates a .twb/.twbx against the matching XSD
  scripts/requirements.txt                     # lxml, needed by validate_workbook.py
  scripts/render_embed.py                      # builds an embeddable URL + local iframe fallback
```

`scripts/validate_workbook.py` needs `lxml`: `pip install -r
plugins/tableau/scripts/requirements.txt`.

## How it connects to Tableau

The hosted MCP server authenticates each user with their own Tableau Cloud/Server
OAuth login — there's no API key or token to configure here. `plugins/tableau/.mcp.json`
just points Codex at the server:

```json
{
  "mcp_servers": {
    "tableau": {
      "url": "https://mcp.tableau.com"
    }
  }
}
```

The first time you use it, Codex will prompt you to authenticate in the
Plugins UI (see below) — `codex mcp login <name>` does **not** work for
MCP servers bundled inside a plugin, only for servers added directly via
`codex mcp add`. Once signed in, every tool call runs with that user's own
Tableau permissions — the server doesn't store Tableau data itself.

## Install and authenticate in Codex Desktop

1. **Register this repo as a marketplace.** From inside this repo:

   ```bash
   codex plugin marketplace add .
   ```

   This adds a marketplace source named after the repo directory (e.g.
   `plugin-codex`) pointing at your local checkout. Run
   `codex plugin marketplace list` if you want to confirm the name it picked.

2. **Install the plugin from the Plugins tab.** Open Codex Desktop → **Plugins**,
   find the "Tableau MCP Skills" marketplace, and install the **tableau**
   plugin.

3. **Authenticate the MCP connector.** Still in the Plugins tab, find the
   Tableau plugin's entry and click **Authenticate**/**Connect**. This opens
   your browser to Tableau's OAuth login (Tableau Cloud or Server, whichever
   your site uses). Approve the request; Codex stores the resulting token and
   the plugin's entry should flip to a connected state.

4. **Start a new task.** MCP connections and plugin config are only
   (re)loaded when a task starts, so an already-open task won't pick up a
   fresh install or a new OAuth connection — start a new one before trying a
   Tableau request.

If a site admin has restricted tool groups via Tableau's `EXCLUDE_TOOLS` site
setting (e.g. disabling `admin-insights` or `pulse`), those tools simply won't
show up — that's expected, not a bug in this plugin.

### If you edit plugin files locally

Codex copies plugin files into its own cache at install time
(`~/.codex/plugins/cache/<marketplace>/<plugin>/`) rather than reading from
this repo live, so editing `.mcp.json` or a skill here has no effect until you
reinstall. `reload-plugin.sh` in the repo root automates the
remove/re-add cycle:

```bash
./reload-plugin.sh
```

Then start a new task (chat) in Codex Desktop as in step 4 above.

# Tableau for ChatGPT and Codex

Connects ChatGPT and Codex to Tableau's hosted MCP server
(`https://mcp.tableau.com`) so you can find and show views, create and publish
workbooks and data apps, and review dashboard design and datasource quality.
Each skill's `SKILL.md` describes what it covers.

This folder is a Codex marketplace: a built plugin under `dist/`, or a
checkout of the `dist/codex` branch. The Codex CLI and the ChatGPT/Codex
desktop apps share `~/.codex`, so one install covers all of them.

## What you can ask

- "Show me the Superstore sales dashboard."
- "Add a monthly profit trend to the Regional Sales workbook and republish it."
- "Build a data app that shows our top 10 accounts by pipeline."
- "Critique the Executive Overview dashboard."

## How it connects to Tableau

The hosted server authenticates each user with their own Tableau Cloud or
Server OAuth login. There is no API key to configure. Both MCP configs point
at the same server. The legacy manifest
(`plugins/tableau/.codex-plugin/plugin.json`) reads `.mcp.json`:

```json
{
  "mcpServers": {
    "Tableau": {
      "type": "http",
      "url": "https://mcp.tableau.com"
    }
  }
}
```

`plugins/tableau/mcp.json` is the portable config and uses
`"type": "streamable-http"` at the same URL. The server key is `Tableau`.

`codex mcp login` does not work for an MCP server bundled in a plugin. Sign
in from the Plugins UI (below). Once signed in, every tool call runs with
that user's Tableau permissions.

A test, stage, or dev build renames the plugin and the server
(`Tableau-test` / `TableauTest`, and the same pattern for stage and dev) and
repoints the URL. Dev runs a local tableau-mcp checkout over stdio instead of
`https://mcp.tableau.com`.

## Install

From a local prod build:

```bash
codex plugin marketplace add ./dist/openai
codex plugin add Tableau@tableau-plugin
```

A test build is `./dist/openai-test` and `Tableau-test@tableau-plugin-test`.
Stage and dev follow the same pattern.

From the published branch, without building:

```bash
codex plugin marketplace add tableau/tableau-plugin --ref dist/codex
codex plugin add Tableau@tableau-plugin
```

Then:

1. **Restart** the ChatGPT/Codex desktop app so it loads the new build.
2. **Connect Tableau.** Open **Plugins**, find **Tableau**, and click
   **Authenticate** / **Connect**. Sign in to Tableau Cloud or Server in the
   browser window that opens.
3. **Start a new task.** Plugins and MCP connections load when a task starts.

If you are in the source repository, `./reload-plugin.sh openai` builds the
test variant and runs the marketplace add and plugin add for you. See that
repo's README for variants.

Codex copies the plugin into its own cache
(`~/.codex/plugins/cache/<marketplace>/<plugin>/`). Editing files here has no
effect until you remove the plugin and add it again.

Creating or publishing workbooks and data apps needs a Creator or Explorer
(can publish) site role. If a site admin has turned off some Tableau MCP tool
groups, those tools do not appear.

## Layout

```
.agents/plugins/marketplace.json
plugins/tableau/
  plugin.json                  # portable manifest (extensions.com.openai)
  mcp.json                     # portable MCP config (streamable-http)
  .codex-plugin/plugin.json    # legacy manifest
  .mcp.json                    # legacy MCP config
  skills/                      # one folder per skill, each with SKILL.md
  references/                  # shared search and rendering notes
  scripts/run_python.py        # launches skill scripts with their dependencies
  requirements.txt             # lxml, installed by run_python.py
  assets/
```

Skills:

- `tableau-about` — what the plugin does, and which skill to use
- `tableau-content-viewer` — find a view, dashboard, or workbook and show it
- `tableau-workbook-authoring` — create, edit, copy, or republish a workbook
- `tableau-data-app-authoring` — scaffold, wire, package, and publish a data app
- `tableau-dashboard-advisor` — turn a question and a schema into a dashboard plan
- `tableau-viz-critique` — score an existing dashboard
- `tableau-data-quality-sentinel` — scan published datasource metadata

Workbook authoring keeps its chart catalog, examples, and Tableau workbook
schemas under `skills/tableau-workbook-authoring/resources/`. OpenAI-only
skill metadata is `skills/<skill>/agents/openai.yaml`.

The workbook validator needs `lxml`. The first time a skill launches it
through `scripts/run_python.py`, that script installs `requirements.txt` into
a shared per-user venv (`~/.cache/tableau-plugin/venv-<pyver>`, or
`%LOCALAPPDATA%\tableau-plugin\` on Windows). That needs network access once.
If the running Python already has `lxml`, no venv is created.

## Support

Source, issues, and license (Apache 2.0): https://github.com/tableau/tableau-plugin

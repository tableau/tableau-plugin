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

The first time you use it, Codex will need you to sign in via
`codex mcp login tableau` (or the in-product "Authenticate" prompt). Once
signed in, every tool call runs with that user's own Tableau permissions — the
server doesn't store Tableau data itself.

## Try it locally

From inside this repo:

```bash
codex plugin marketplace add .
```

Then in a Codex session, run `/plugins`, open the "Tableau MCP Skills"
marketplace, and install the **tableau** plugin. Start a new session, and its
skill and MCP tools will be available.

If a site admin has restricted tool groups via Tableau's `EXCLUDE_TOOLS` site
setting (e.g. disabling `admin-insights` or `pulse`), those tools simply won't
show up — that's expected, not a bug in this plugin.

## Generating/modifying workbooks

The `tableau-workbook-authoring` skill edits a workbook's `.twb` file (plain
XML) directly, then publishes it back through Tableau's MCP `authoring` tools
(`download-workbook`, `request-workbook-upload`,
`validate-upload-and-publish-workbook`). A few things worth knowing:

- **These tools are feature-gated on Tableau's side** (`authoring-tools` and
  `mcp-apps`). If they're missing/disabled, that's a site configuration issue,
  not something this plugin can fix.
- **Validation is two-stage.** `scripts/validate_workbook.py` checks the
  edited `.twb`/`.twbx` locally against the real per-version TWB XSD schema
  bundled under `schemas/` (auto-detecting the workbook's version). That
  catches structural mistakes fast, but the schemas intentionally leave some
  regions unchecked (e.g. calculated-field formulas), so it can't catch
  semantic problems. The authoritative check is still Tableau Server's own
  validation, run as part of `validate-upload-and-publish-workbook`.
- **Rendering the result as a live embed is best-effort.** Tableau's MCP
  server has a `render-interactive-viz` tool built for hosts that support the
  MCP Apps UI standard, but that iframe-rendering is documented as a ChatGPT
  capability, not confirmed for every Codex surface. `scripts/render_embed.py`
  is the guaranteed-to-work fallback: it builds a `:embed=yes` URL and opens a
  local HTML file with an `<iframe>` in the default browser. These steps are
  written once in `skills/shared/rendering.md` and reused by
  `tableau-workbook-authoring` and by `tableau-content-viewer` (which just
  finds and renders existing content, without touching any `.twb`).

## Publishing

Once pushed to GitHub, others can add this repo as a marketplace source:

```bash
codex plugin marketplace add tableau/plugin-codex
```

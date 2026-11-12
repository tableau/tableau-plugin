# Tableau for Grok Bot

This folder is a Cursor marketplace. Grok Bot 0.49 and newer installs plugins
from that catalog. Cursor does not list this plugin (`minClientVersions.cursor`
is `never`).

The plugin connects Grok to Tableau's hosted MCP server
(`https://mcp.tableau.com`): find and show views, create and publish workbooks
and data apps, and review dashboard design and datasource quality. Sign-in is
the user's Tableau Cloud OAuth login. There is no API key in this tree.

User-facing setup is `plugins/tableau/README.md`.

## Layout

```
.cursor-plugin/marketplace.json          # marketplace index
plugins/tableau/
  .cursor-plugin/plugin.json             # plugin manifest
  mcp.json                               # hosted MCP server, key Tableau
  skills/                                # one folder per skill
  references/
  scripts/run_python.py
  requirements.txt
  assets/logo.png
  README.md
```

`mcp.json` is one server, `Tableau`, `type` `http`, URL `https://mcp.tableau.com`.
No client id is set. Tableau's hosted authorization server
(`https://sso.online.tableau.com`) advertises client-id metadata documents and,
in the metadata fetched for this build, no dynamic-registration endpoint.
VERIFY that Grok Bot still completes the OAuth sign-in.
A test, stage, or dev build renames the marketplace and plugin
(`tableau-plugin-test`, `tableau-test`) and the server key (`TableauTest`,
`TableauStage`, `TableauDev`). Test and stage repoint the URL. Dev runs a
local tableau-mcp checkout over stdio.

## Submit

Host this tree at the root of a public git repository (the `dist/cursor`
branch of tableau/tableau-plugin once publish has run) and submit that
repository at <https://cursor.com/marketplace/publish>.

The review expects `.cursor-plugin/marketplace.json` at the repository root,
`plugins/tableau/.cursor-plugin/plugin.json`, a logo committed in the repo,
and a plugin README. Do not submit this source repository's default branch:
the manifests live under `platforms/cursor/overlay/` until the build copies
them here.

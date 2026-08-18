# Tableau Codex Plugin Manifest Design

## Goal

Turn this repository into an installable Codex plugin marketplace modeled on the
Sentry sample, with one Tableau plugin that bundles Tableau skills and connects
Codex to the hosted Tableau MCP server.

## Package structure

The repository root will be the marketplace root:

```text
.gitignore
.agents/plugins/marketplace.json
plugins/tableau/
  .codex-plugin/plugin.json
  .mcp.json
  skills/
    validate-workbook-package/
      SKILL.md
README.md
```

The existing untracked `skills/validate-twb/` stub will move into the plugin
package. Its destination directory will match its frontmatter name,
`validate-workbook-package`, and the plugin's relative `./skills/` path will
resolve correctly. Existing Cursor-specific guidance under `.cursor/` will not
be modified.

The local `sample-plugin/` reference checkout will be ignored so it cannot be
accidentally packaged as a second marketplace.

## Marketplace manifest

`.agents/plugins/marketplace.json` will define:

- Marketplace ID: `tableau-plugin-marketplace`
- Display name: `Tableau Plugins`
- Plugin ID: `tableau`
- Local source path: `./plugins/tableau`
- Installation policy: `AVAILABLE`
- Authentication policy: `ON_INSTALL`
- Category: `Productivity`

## Plugin manifest

`plugins/tableau/.codex-plugin/plugin.json` will define a versioned Tableau
plugin with:

- Stable package identity and concise Tableau authoring/analysis descriptions
- Tableau as the author
- Tableau homepage and the verified repository URL
- Search keywords relevant to Tableau, analytics, visualization, and workbooks
- Bundled skills at `./skills/`
- MCP configuration at `./.mcp.json`
- Store-facing interface metadata, capabilities, and starter prompts that do
  not depend on missing image assets or unconfirmed legal URLs

Optional apps, hooks, logos, screenshots, and legal metadata are out of scope
until those artifacts and decisions exist.

## MCP manifest

`plugins/tableau/.mcp.json` will use the sample's wrapped `mcpServers` shape and
declare one HTTP server named `tableau` at `https://mcp.tableau.com`.

## Documentation

The root README will describe what the plugin includes and show marketplace and
plugin installation commands using the verified GitHub repository:

```text
codex plugin marketplace add tableau/plugin-codex
codex plugin add tableau@tableau-plugin-marketplace
```

No license file or manifest license field will be invented; licensing can be
added once the project owner selects it.

## Validation

Implementation is complete when:

1. Every JSON manifest parses successfully.
2. Marketplace and plugin IDs agree.
3. Every relative manifest path resolves within the plugin package.
4. The packaged `validate-workbook-package` skill exists at the declared skills path.
5. Available repository checks pass without introducing linter diagnostics.


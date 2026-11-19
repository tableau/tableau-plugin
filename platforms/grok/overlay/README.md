# Tableau for Grok

This folder is a Grok plugin marketplace for the Grok CLI (`grok`) and Grok
Bot desktop. Both read `~/.grok`, so a plugin installed from either one shows
up in the other.

User-facing setup is `plugins/tableau/README.md`.

## Layout

```
.grok-plugin/marketplace.json            # marketplace index
plugins/tableau/
  .grok-plugin/plugin.json               # plugin manifest
  .mcp.json                              # hosted MCP server, key Tableau
  skills/                                # one folder per skill
  references/
  scripts/run_python.py
  requirements.txt
  assets/logo.png
  README.md
```

`.mcp.json` is one server, `Tableau`, `type` `http`, URL
`https://mcp.tableau.com`. No client id is set. A test, stage, or dev build
renames the marketplace and plugin (`tableau-plugin-test`, `tableau-test`)
and the server key (`TableauTest`, `TableauStage`, `TableauDev`). Test and
stage repoint the URL. Dev runs a local tableau-mcp checkout over stdio.

## Install

From a local build:

```bash
grok plugin install ./plugins/tableau --trust
```

Or add this tree as a marketplace and install from it:

```bash
grok plugin marketplace add <path or git URL of this tree>
grok plugin install tableau --trust
```

Grok Bot desktop installs a plugin from a git repository and branch. Host
this tree on a branch (`alpha/grok` in tableau/tableau-plugin once publish has
run) and add that repository and branch as a marketplace.

## Submit to the xAI marketplace

The official catalog is
[xai-org/plugin-marketplace](https://github.com/xai-org/plugin-marketplace).
A listing is an entry in its `.grok-plugin/marketplace.json` that points at
this repository by URL, a full commit `sha`, and `path`
(`plugins/tableau`). Its reviewers ask for brand-scoped `keywords` and
`domains`, a `homepage`, a README that lists the network endpoints the plugin
uses, and a source in the vendor's own GitHub organization. Do not point the
listing at this source repository's default branch: the manifests live under
`platforms/grok/overlay/` until the build copies them here.

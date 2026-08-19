# Tableau for Codex

The Tableau plugin teaches Codex how to analyze data and build, modify, and
validate Tableau workbooks. It also connects Codex to the hosted Tableau MCP
server.

## Install

```bash
codex plugin marketplace add tableau/plugin-codex
codex plugin add tableau@tableau-plugin-marketplace
```

## Included

- A resource catalog (`plugins/tableau/resources/catalog.json`) of chart
  templates, worked examples, and reference docs, each tagged `executable`
  (renderable into a workbook) or `reference` (inspiration only)
- A CLI, `plugins/tableau/scripts/tableau_resources.py`, to discover,
  inspect, and safely transform `.twb` workbooks against that catalog
- Skills covering the authoring flow — download-or-starter → transform
  (`instantiate`/`inject`) → validate → publish — general workbook
  authoring, Pulse Insights charts, and workbook package validation
- Hosted Tableau MCP server at <https://mcp.tableau.com>

See `plugins/tableau/README.md` for the full CLI reference and authoring
flow.

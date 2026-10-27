# Tableau

Explore Tableau content and create or modify Tableau workbooks and data apps
from Claude, through Tableau's hosted MCP server.

## What it does

This plugin connects Claude to your Tableau Cloud or Tableau Server site and
adds skills for common Tableau work: finding and showing existing views and
dashboards, creating and publishing workbooks and data apps, and reviewing
dashboard design and datasource quality. Each skill's `SKILL.md` describes
what it covers.

## How to use it

Ask Claude in plain language, for example:

- "Show me the Superstore sales dashboard."
- "Add a monthly profit trend to the Regional Sales workbook and republish it."
- "Build a data app that shows our top 10 accounts by pipeline."
- "Critique the Executive Overview dashboard."

Claude picks the matching skill and calls the Tableau MCP tools it needs.

## Setup

1. **Install the plugin** and enable its Tableau connector
   (`https://mcp.tableau.com`).
2. **Sign in to Tableau.** The first time Claude uses a Tableau tool, you're
   asked to sign in to your Tableau Cloud or Server site with OAuth. There's no
   API key or token to configure. Every request runs with your own Tableau
   permissions, and the server doesn't store your Tableau data.
3. **Check your site role for publishing.** Viewing and analysis work with any
   site role. Creating or publishing workbooks and data apps needs Creator or
   Explorer (can publish), plus permission to publish to the target project.
   Data apps also need the `scaffold-data-app` tool, which depends on your
   site's settings and Tableau version.

Some skills run bundled Python scripts, for example to validate workbook XML.
These need Python 3 and, the first time, network access to install the pinned
`lxml` package into a per-user cache.

If a site admin has turned off some Tableau MCP tool groups, those tools don't
appear, and the skills that need them say so.

## Support

Source, issues, and license (MIT): https://github.com/tableau/tableau-plugin

# Tableau

Explore Tableau content and create or modify Tableau workbooks and data apps
from Grok, through Tableau's hosted MCP server.

Grok Bot 0.49 and newer installs this plugin from the Cursor marketplace.
Cursor itself does not list it.

## What it does

This plugin connects Grok to your Tableau Cloud site and adds skills for
finding and showing existing views and dashboards, creating and publishing
workbooks and data apps, and reviewing dashboard design and datasource
quality. Each skill's `SKILL.md` describes what it covers.

## How to use it

Ask in plain language, for example:

- "Show me the Superstore sales dashboard."
- "Add a monthly profit trend to the Regional Sales workbook and republish it."
- "Build a data app that shows our top 10 accounts by pipeline."
- "Critique the Executive Overview dashboard."

Grok picks the matching skill and calls the Tableau MCP tools it needs.
Tool names in the skills are the server's own names (`search-content`). Call
the listed tool whose name ends in that, for example `Tableau__search-content`.
VERIFY the prefix Grok Bot assigns to this plugin's server.

## Setup

1. **Install the plugin** from the Cursor marketplace in Grok Bot.
   VERIFY the exact control. Other Grok Bot plugins install from
   **Connect apps**.
2. **Sign in to Tableau.** The server is `https://mcp.tableau.com`. The first
   time Grok uses a Tableau tool, sign in to Tableau Cloud with OAuth. There
   is no API key or token to configure. Every request runs with your own
   Tableau permissions, and the server does not store your Tableau data.
   VERIFY that Grok Bot opens that OAuth flow with no client id in this
   plugin.
3. **Check your site role for publishing.** Viewing and analysis work with any
   site role. Creating or publishing workbooks and data apps needs Creator or
   Explorer (can publish), plus permission to publish to the target project.
   Data apps also need the `scaffold-data-app` tool, which depends on your
   site's settings and Tableau version.

Some skills run bundled Python scripts, for example to validate workbook XML.
These need Python 3 and, the first time, network access to install the pinned
`lxml` package into a per-user cache. VERIFY that the Grok Bot session can
run those scripts.

A view image is usually a short-lived presigned URL. The skills download it
with `curl` or Python in a shell, then show the PNG. VERIFY that the session
has a shell and can reach the image host, and that a Markdown image of the
local path is actually displayed.

If a site admin has turned off some Tableau MCP tool groups, those tools don't
appear, and the skills that need them say so.

## Support

Source, issues, and license (Apache 2.0): https://github.com/tableau/tableau-plugin

Privacy policy: https://www.salesforce.com/company/legal/privacy/

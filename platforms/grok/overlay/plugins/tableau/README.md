# Tableau

Explore Tableau content and create or modify Tableau workbooks and data apps
from Grok, through Tableau's hosted MCP server.

## What it does

This plugin connects Grok to your Tableau Cloud site and adds skills for
common Tableau work: finding and showing existing views and dashboards,
creating and publishing workbooks and data apps, and reviewing dashboard
design and datasource quality. Each skill's `SKILL.md` describes what it
covers.

## How to use it

Ask Grok in plain language, for example:

- "Show me the Superstore sales dashboard."
- "Add a monthly profit trend to the Regional Sales workbook and republish it."
- "Build a data app that shows our top 10 accounts by pipeline."
- "Critique the Executive Overview dashboard."

Grok picks the matching skill and calls the Tableau MCP tools it needs. Grok
lists them as `Tableau__<tool>` (for example `Tableau__search-content`); the
skills name the tool by its base name.

## Setup

1. **Install the plugin.** The Grok CLI and Grok Bot desktop share `~/.grok`,
   so one install covers both:

   ```bash
   grok plugin install <source> --trust
   ```

   `<source>` is a local path to this folder, or a git source such as
   `tableau/tableau-plugin@<branch>#plugins/tableau`.
2. **Sign in to Tableau.** The server is `https://mcp.tableau.com`. Sign-in is
   your Tableau Cloud OAuth login; there is no API key or token to configure.
   Every request runs with your own Tableau permissions, and the server does
   not store your Tableau data.
   - **Grok Bot desktop:** connect the built-in **Tableau** app first. When
     the plugin's connectors are listed, choose **App** to reuse that
     connection.
   - **Grok CLI:** open `/mcps`, select `Tableau`, and press `i`. VERIFY:
     Tableau's sign-in registers clients only through Client ID Metadata
     Documents, not Dynamic Client Registration, and Grok CLI 1.0.89 fails
     before opening a browser.
3. **Check your site role for publishing.** Viewing and analysis work with any
   site role. Creating or publishing workbooks and data apps needs Creator or
   Explorer (can publish), plus permission to publish to the target project.
   Data apps also need the `scaffold-data-app` tool, which depends on your
   site's settings and Tableau version.

Some skills run bundled Python scripts, for example to validate workbook XML.
These need Python 3 and, the first time, network access to install the pinned
`lxml` package into a per-user cache.

A view image is usually a short-lived presigned URL. The skills download it
with `curl` or Python in a shell, then show the PNG. VERIFY that Grok Bot
displays a Markdown image of the local path.

If a site admin has turned off some Tableau MCP tool groups, those tools don't
appear, and the skills that need them say so.

## Network access

- `https://mcp.tableau.com`: the Tableau MCP server.
- `https://sso.online.tableau.com` and your site (`*.online.tableau.com`):
  Tableau sign-in and the view URLs the skills link to.
- `*.s3.*.amazonaws.com`: presigned view images returned by `get-view-image`.
  The bucket and region depend on your Tableau Cloud pod.
- `https://pypi.org` and `https://files.pythonhosted.org`: the one-time
  `lxml` install by `scripts/run_python.py`.

## Support

Source, issues, and license (Apache 2.0): https://github.com/tableau/tableau-plugin

Privacy policy: https://www.salesforce.com/company/legal/privacy/

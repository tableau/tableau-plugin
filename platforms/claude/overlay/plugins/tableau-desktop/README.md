# Tableau Desktop

Build and edit the workbook open in Tableau Desktop from Claude Code, through
the local Tableau Desktop MCP server.

## Where it works

- Claude Code on the computer where Tableau Desktop runs, including the Claude
  Desktop app's Code tab.
- Not Cowork, Chat, claude.ai, or Claude Code on the web. Those can't reach
  Tableau Desktop on your computer. Installing the plugin there does no harm,
  but its tools don't work.

For content on Tableau Cloud or Tableau Server, use the `tableau` plugin.

## What you can ask

- "Add a bar chart of sales by region to the workbook I have open."
- "Build a dashboard from the Sales and Profit sheets."
- "What were the top five products by profit in this view?"

## Setup

1. **Install Node.js 22.7.5 or later.** The plugin starts the server with
   `npx -y @tableau/mcp-server-desktop@latest`, so `npx` must be on the `PATH`
   Claude Code sees. On Windows, the Claude Desktop app doesn't read PowerShell
   profiles, so put Node on the user or system `PATH`.
2. **Turn on External API Access in Tableau Desktop.** Select Help > Settings
   and Performance > Enable External API Access (Requires Restart), then
   restart Tableau Desktop. If the setting is unavailable, contact your Tableau
   admin.
3. **Use the most recent public release of Tableau Desktop, or later.**
4. **Check the connection.** Run `/mcp` and confirm
   `plugin:tableau-desktop:TableauDesktop` is connected. If it failed, choose
   **Reconnect**. Claude Code waits 15 minutes before retrying a failed server
   on its own.

If you added a Tableau Desktop MCP server by hand before, remove it, so only
one server drives Desktop.

## Settings

- **Data app folder** (`data_app_dir`): the absolute path where
  `scaffold-data-app` writes Desktop data apps. Leave it empty if you don't
  build data apps.

The server sends product usage data to Tableau. It doesn't link that data to
you. To turn it off, set `PRODUCT_TELEMETRY_ENABLED` to `false` for the
TableauDesktop server.

## Support

Source, issues, and license (Apache 2.0): https://github.com/tableau/tableau-plugin

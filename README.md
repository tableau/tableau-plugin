# Tableau plugin — multi-platform source

This repository holds a single source of truth for the Tableau plugin and builds
it into platform-specific distributions with a small build script. Skills,
references, scripts, and assets are authored once; each platform contributes
only what is genuinely platform-specific.

| Platform | Serves | Plugin format |
|---|---|---|
| `openai` | ChatGPT and Codex (web, desktop, CLI) | root `plugin.json` + `extensions.com.openai`, with `.codex-plugin/plugin.json` as a fallback for current CLIs |
| `claude` | Claude apps (web, Desktop Chat, Cowork) and Claude Code | `.claude-plugin/plugin.json` |

## Layout

```
src/plugin/                 # shared payload authored once (skills, references, assets, hooks)
platforms/
  openai/
    overlay/
      .agents/plugins/marketplace.json          # OpenAI marketplace
      plugins/tableau/plugin.json               # portable manifest (OpenAI settings under extensions.com.openai)
      plugins/tableau/mcp.json                  # portable MCP config (streamable-http)
      plugins/tableau/.codex-plugin/plugin.json # legacy manifest; codex-cli <= 0.154 needs it
      plugins/tableau/.mcp.json                 # legacy MCP config, referenced by the legacy manifest
      README.md                                 # end-user install/auth docs
    vars.yaml
  claude/
    overlay/
      .claude-plugin/marketplace.json
      plugins/tableau/.claude-plugin/plugin.json
      plugins/tableau/.mcp.json
    vars.yaml
build/
  build.py                  # assembles a platform distribution
  requirements.txt          # Jinja2 + PyYAML
dist/                       # build output (git-ignored)
```

## Build

```bash
python3 build/build.py                 # build every platform
python3 build/build.py openai          # build one platform -> dist/openai/
python3 build/build.py --zip claude    # also write dist/claude-tableau.zip
python3 build/build.py --check         # CI: fail if dist/ is stale
```

The build copies `src/plugin/` into `dist/<platform>/plugins/tableau/`, then
merges `platforms/<platform>/overlay/` over the top (overlay wins on collision).
Files ending in `.j2` are rendered with Jinja2 using the platform's `vars.yaml`;
everything else is copied verbatim. A platform's `vars.yaml` can list
`exclude:` globs for payload files it doesn't ship (e.g. Claude drops
`skills/*/agents/openai.yaml`).

`--zip` packages the plugin folder itself (manifest at the zip root) for
uploading in the Claude apps or submitting to OpenAI.

## How platform differences are handled

- **Portable content** — skills, references, scripts, assets — lives in `src/plugin/`.
- **Structurally different files** — marketplace/plugin manifests, MCP config,
  install docs — are authored per platform under `platforms/<platform>/overlay/`.
- **Host-specific wording** — tool names, render/elicitation tools, env var
  names — comes from `vars.yaml`:
  - `mcp_prefix`: `mcp__Tableau__` on OpenAI. Empty on Claude, where the
    connector's tool prefix is host-assigned and unpredictable; skills there
    name tools by base name (`search-content`) and tell the model to match on
    the suffix.
  - `tools.render_native` / `tools.js_repl` / `tools.elicit`: host built-ins.
    Leave empty when a host has none; the prose falls back (PNG render,
    numbered list).
  - `plugin_root`: how hooks find the plugin's install directory.
- **Scripts** are Python (stdlib only, cross-platform). Third-party packages
  for any skill go in one list, `src/plugin/requirements.txt`, installed into a
  single shared venv (`~/.cache/tableau-plugin/venv-<pyver>`, keyed by a hash
  of that file). The session-start hook prepares it via
  `scripts/run_python.py --bootstrap`, so skills don't pay the install cost
  mid-task. A script that needs those packages is launched as
  `python3 <plugin>/scripts/run_python.py <script.py> [args]`; without the hook
  (Claude Chat, the web) the first such call installs the venv instead.

To add a platform: create `platforms/<name>/{overlay,vars.yaml}` with that
host's manifests and values, then run `python3 build/build.py <name>`.

## Install locally: Codex and ChatGPT desktop

The Codex CLI and the ChatGPT/Codex desktop apps share `~/.codex`, so one
install covers all of them. `reload-plugin.sh` builds the plugin and
(re)installs it:

```bash
./reload-plugin.sh openai
```

The script:

1. creates `.build-venv/` with the build dependencies (first run only);
2. builds `dist/openai/`;
3. removes any previous `Tableau@tableau-plugin` install and its marketplace;
4. registers `dist/openai/` as the `tableau-plugin` marketplace and installs
   the plugin.

Then:

1. **Restart** the ChatGPT/Codex desktop app so it loads the new build.
2. **Connect Tableau.** Open **Plugins**, find **Tableau**, and click
   **Authenticate**/**Connect**. Sign in to Tableau Cloud or Server in the
   browser window that opens. (`codex mcp login` doesn't work for MCP servers
   bundled in a plugin.)
3. **Start a new task.** Plugins and MCP connections load when a task starts,
   so an open task won't see the new install.

Codex copies the plugin into its own cache when installing it, so editing
files under `src/` or `platforms/` has no effect until you re-run the script.

## Install locally: Claude desktop

The Claude apps (Desktop, web, Cowork) have no command line for installing
plugins. `claude plugin install` reaches only Claude Code. You build a zip and
upload it in the app. The plugin is saved to your claude.ai account, so after
uploading it once it also appears on claude.ai and on your other machines.

1. **Build the zip:**
   ```bash
   ./reload-plugin.sh claude
   ```
   This writes `dist/claude-tableau.zip` and, on macOS, shows it in Finder
   and opens Claude.
2. **Upload it.** In Claude, open **Customize → Plugins**, choose
   **Add → Upload plugin**, and pick `dist/claude-tableau.zip`.
3. **Connect Tableau.** Open the installed **Tableau** plugin, go to its
   **Connectors** tab, and connect the Tableau connector. Sign in to Tableau
   Cloud or Server when prompted.
4. **Turn on code execution** in Claude's settings. The skills run scripts.
5. **Start a new chat** and try a request such as "show me the Superstore
   dashboard".

**To update,** repeat steps 1 and 2. If the old version is still listed
afterwards, **Remove** it under Customize → Plugins and upload again.

**What runs where:** skills and the Tableau connector work in Chat and Cowork.
Hooks and sub-agents run only in Cowork. Without the hook, the workbook
validator sets up its Python dependencies the first time it runs.

**Optional: update from a GitHub repo instead of uploading.** Create an empty
GitHub repo for the built plugin (not this source repo), then run:

```bash
CLAUDE_MARKETPLACE_REPO=git@github.com:you/tableau-plugin-claude.git ./reload-plugin.sh claude
```

This pushes `dist/claude/` to the repo's default branch. Add the repo once
under **Customize → Plugins → Add marketplace** and install **Tableau** from
it. After later runs, click **Check for updates** on the marketplace, or turn
on **Sync automatically**. Private repos need the Claude GitHub App.

## Other surfaces

**ChatGPT web:** test through developer mode. Sharing with a workspace needs a
workspace admin; listing in the public directory needs OpenAI review (OAuth,
domain verification).

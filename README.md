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
python3 build/build.py --variant dev openai   # local-development build
python3 build/build.py --slim --zip claude   # size-reduced build for the Claude plugin directory
```

### Variants

The published plugin and a local build can't share names. Codex keeps one MCP
server per name (it skips a second plugin's `Tableau` server), and both hosts
namespace skills and tools by plugin name. So `--variant` builds a renamed copy
that installs beside the marketplace plugin:

| Variant | MCP server | Output | Plugin / MCP server key |
|---|---|---|---|
| `prod` (default) | `https://mcp.tableau.com` | `dist/<platform>/` | `Tableau` / `Tableau` |
| `test` | `https://test.mcp.tableau.com` | `dist/<platform>-test/` | `Tableau-test` / `TableauTest` |
| `stage` | `https://stage.mcp.tableau.com` | `dist/<platform>-stage/` | `Tableau-stage` / `TableauStage` |
| `dev` | local [tableau-mcp](https://github.com/tableau/tableau-mcp) over stdio | `dist/<platform>-dev/` | `Tableau-dev` / `TableauDev` |

(Claude plugin names are lowercase: `tableau-test`, `tableau-stage`,
`tableau-dev`.) The skills' tool names follow the server key, e.g.
`mcp__TableauDev__search-content`.

`dev` runs `node --env-file=<checkout>/.env <checkout>/build/index.js` with
`TRANSPORT=stdio`. Point it at your checkout with `TABLEAU_MCP_DIR` in this
repo's `.env` (git-ignored; copy `.env.example`), and the build bakes that in
as the default. Hosts run the plugin from their own cache, not from this repo,
so rebuild after changing it. A `TABLEAU_MCP_DIR` in the host app's environment
still overrides the baked default. The checkout's own `.env` supplies `SERVER`,
`SITE_NAME` and auth. After changing tableau-mcp, run `npm run build` there and
start a new task; there's no need to reinstall the plugin.

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
./reload-plugin.sh openai          # test variant (default)
./reload-plugin.sh openai stage    # hosted stage.mcp.tableau.com
./reload-plugin.sh openai dev      # local tableau-mcp over stdio
```

The script:

1. creates `.build-venv/` with the build dependencies (first run only);
2. builds `dist/openai-<variant>/`;
3. removes any previous `Tableau-<variant>@tableau-plugin-<variant>` install
   and its marketplace;
4. registers `dist/openai-<variant>/` as the `tableau-plugin-<variant>`
   marketplace and installs the plugin.

Each variant has its own names, so test, stage, dev and the marketplace plugin
can be installed at once; disable the ones you aren't using to keep the tool
list unambiguous.

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
   ./reload-plugin.sh claude          # or: ./reload-plugin.sh claude dev
   ```
   This writes `dist/claude-test-tableau.zip` and, on macOS, shows it in Finder
   and opens Claude.
2. **Upload it.** In Claude, open **Customize → Plugins**, choose
   **Add → Upload plugin**, and pick `dist/claude-test-tableau.zip`.
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

## Network access for view images (Claude)

`get-view-image` usually returns a short-lived presigned S3 URL rather than
the image itself. On the `claude` platform the skills download it with `curl`
(or Python) in a shell, never with the host's web fetch tool: the URL is over
2,000 characters, and Cowork's fetch rejects it with
`cowork_web_fetch_url_too_long`. If the download can't run, the skills fall
back to a view link and ask for a screenshot.

The shell therefore needs outbound HTTPS to the image host. The host is in the
`resource_link` URL, e.g.
`prod-dataplane3-...-mcp-images-....s3.us-west-2.amazonaws.com`; the bucket
and region can differ by Tableau Cloud pod, so check the URL from your own
site.

**Claude Code.** Allow `curl` so it doesn't stop on a permission prompt, and,
if [sandboxing](https://code.claude.com/docs/en/sandboxing) is on, allow the
image host:

```json
{
  "permissions": { "allow": ["Bash(curl *)"] },
  "sandbox": {
    "network": { "allowedDomains": ["<image host from the URL>"] }
  }
}
```

See [permissions](https://code.claude.com/docs/en/permissions) and the
[settings reference](https://code.claude.com/docs/en/settings-reference).
Managed settings can override both: `sandbox.network.allowManagedDomainsOnly`
or `sandbox.network.strictAllowlist`, or a managed `permissions.deny` rule,
will block the download until an admin adds the host.

**Claude Chat (web, Desktop) — VERIFY.** Code execution must be on (install
step 4), and its sandbox needs network egress that allows the image host. We
haven't found Anthropic documentation for the exact egress setting or
confirmed that the sandbox can reach S3. On Team and Enterprise plans, an
admin may control this. If it can't, Chat always gets the link-and-screenshot
fallback.

**Cowork — VERIFY.** Cowork runs the shell in its own environment. We haven't
found documentation of its network settings. Test with a view-image request:
a downloaded image means it works; a curl connection error means the image
host is blocked there.

## Other surfaces

**ChatGPT web:** test through developer mode. Sharing with a workspace needs a
workspace admin; listing in the public directory needs OpenAI review (OAuth,
domain verification).

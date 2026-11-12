# Tableau plugin — multi-platform source

This repository holds a single source of truth for the Tableau plugin and builds
it into platform-specific distributions with a small build script. Skills,
references, scripts, and assets are authored once; each platform contributes
only what is genuinely platform-specific.

| Platform | Serves | Plugin format |
|---|---|---|
| `openai` | ChatGPT and Codex (web, desktop, CLI) | root `plugin.json` + `extensions.com.openai`, with `.codex-plugin/plugin.json` as a fallback for current CLIs |
| `claude` | Claude apps (web, Desktop Chat, Cowork) and Claude Code | `.claude-plugin/plugin.json` |
| `quick` | Amazon Quick (desktop) | none: standalone skill folders plus `tableau-skills.zip`, and `connector/mcp.json` for the MCP connector |

## Layout

```
src/plugin/                 # shared payload authored once (skills, references, scripts, assets)
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
      plugins/tableau/README.md                 # end-user docs; required by the Claude plugin directory
    vars.yaml
  quick/
    overlay/
      README.md.j2                              # setup: connector + skills
      connector/mcp.json                        # MCP server config to import as a connector
    vars.yaml                                   # skills_package: standalone skills + zip
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
python3 build/build.py --check         # compare dist/ to a fresh build; do not rewrite it
python3 build/build.py --variant dev openai   # local-development build
python3 build/build.py --slim --zip claude    # dist/claude-slim/ and dist/claude-slim-tableau.zip
python3 build/build.py quick           # Amazon Quick skills + connector -> dist/quick/
```

`--check` is a local stale-tree check. `dist/` is git-ignored, and CI does
not run it. CI publishes from a fresh prod build; see [Published builds](#published-builds).

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
`tableau-dev`.) On OpenAI, the skills' tool names follow the server key, e.g.
`mcp__TableauDev__search-content`. Claude and Quick leave the prefix empty.

`dev` writes a stdio MCP server. The command is `sh -c` running
`exec node --env-file="$dir/.env" "$dir/build/index.js"`, with `TRANSPORT=stdio`
in the server's `env`. `$dir` is `TABLEAU_MCP_DIR`. Point it at your checkout
in this repo's `.env` (git-ignored; copy `.env.example`); the build bakes that
path in as the default inside `${TABLEAU_MCP_DIR:-<baked>}`. On OpenAI,
`mcp_env_passthrough` also lists `TABLEAU_MCP_DIR` in the server's `env_vars`,
because Codex gives a plugin MCP server a minimal environment, so a value there
overrides the baked default. Claude and Quick do not set that passthrough; they
use the baked path unless the host already puts `TABLEAU_MCP_DIR` in the server
process environment. Rebuild the plugin after changing the baked path. The
checkout's own `.env` supplies `SERVER`, `SITE_NAME`, and auth. After changing
tableau-mcp, run `npm run build` there and start a new task; there's no need
to reinstall the plugin.

The build copies `src/plugin/` into `dist/<platform>/plugins/tableau/`, then
merges `platforms/<platform>/overlay/` over the top (overlay wins on collision).
Files ending in `.j2` are rendered with Jinja2 using the platform's `vars.yaml`;
everything else is copied verbatim. A platform's `vars.yaml` can list
`exclude:` globs for payload files it doesn't ship (Claude and Quick drop
`skills/*/agents/openai.yaml`).

`--zip` packages the plugin folder itself (manifest at the zip root) for
uploading in the Claude apps or submitting to OpenAI. The zip is named from
the output directory: `dist/claude-tableau.zip`, `dist/claude-test-tableau.zip`,
`dist/claude-slim-tableau.zip`, or `dist/claude-test-slim-tableau.zip`.

### Slim builds (Claude plugin directory)

`--slim` is a size-reduced Claude build for the plugin directory, which times
out validating the full package. It reads the `slim:` block in
`platforms/claude/vars.yaml` and writes `dist/claude-slim/`
(`dist/claude-<variant>-slim/` when `--variant` is not `prod`). Slim does not
rename the plugin; a non-prod `--variant` still does. The slim build drops
every `*.tbm` chart template,
`tableau-desktop-commands-reference.json`, and `twb-example-index.json`, keeps
the newest two workbook schema versions, strips XSD indentation, prunes
`catalog.json` entries whose files no longer ship, and fails if a non-image
file exceeds 256 KiB. Only Claude defines `slim:`.

### Standalone-skill builds (Amazon Quick)

Amazon Quick has no plugin format. The Tableau MCP server is added as a
connector, and each skill is installed on its own (**Customize > Skills**,
from a folder or a zip). So `platforms/quick/vars.yaml` has a
`skills_package:` block, and the build writes:

```
dist/quick/
  connector/mcp.json      # from the overlay; variants repoint it
  skills/<skill>/         # one self-contained folder per skill
  tableau-skills.zip      # the contents of skills/
  README.md               # setup guide
```

Follow `dist/quick/README.md` for connector and skill setup. `reload-plugin.sh`
does not build or install Quick.

A skill in the shared payload can link outside its folder, e.g. to
`../../references/search.md` or `<skill-dir>/../../scripts/run_python.py`.
The build copies each such file into the skill at the same relative path
(`references/search.md`) and rewrites the path to match.
`skills_package.companions` lists files a copied file needs that no link
names: `run_python.py` reads `requirements.txt` from two levels up, which is
now the skill folder. The build fails if a copy would overwrite a skill's own
file, or if a skill points into another skill.

`--variant test`/`stage` point the connector at that server. `dev` writes a
stdio config, which Quick on desktop runs as a local connector. `--zip` is
skipped, since the build always writes the skills zip.

## How platform differences are handled

- **Portable content** — skills, references, scripts, assets — lives in `src/plugin/`.
- **Structurally different files** — marketplace/plugin manifests, MCP config,
  install docs — are authored per platform under `platforms/<platform>/overlay/`.
- **Host-specific wording** comes from `vars.yaml`. Templates read:
  - `assistant_name`, `show_image`, and `elicit_max_options`.
  - `mcp_prefix`: `mcp__Tableau__` on OpenAI. Empty on Claude and Quick, where
    the connector's tool prefix is host-assigned or unknown; skills there name
    tools by base name (`search-content`) and tell the model to match on the
    suffix. A non-prod OpenAI variant rewrites this to the variant's server
    key (`mcp__TableauDev__`).
  - `tools.render_native`, `tools.site_access`, `tools.js_repl`, `tools.elicit`:
    host built-ins. Leave empty when a host has none; the prose falls back
    (PNG render, numbered list, no site-approval retry).
  - `capabilities.interactive_viz`, `native_render`, `native_render_guaranteed`,
    `js_repl`, `shell_download_only`, `browser_verify`: which render and
    download paths the prose includes. `shell_download_only` (Claude) tells
    the model to download presigned image URLs with `curl` or Python in a
    shell, never with the host's web fetch tool.
  - `exclude`: payload globs this platform does not ship.
  - `mcp_env_passthrough`: OpenAI only. The dev variant then lists
    `TABLEAU_MCP_DIR` in the stdio server's `env_vars`.
  - `slim`: Claude only. See [Slim builds](#slim-builds-claude-plugin-directory).
  - `shipped_skills` (set by the build, not `vars.yaml`): the skills that ship
    on the platform, so a template mentions a sibling skill only where it exists.
- **Scripts** are Python (stdlib only, cross-platform). Third-party packages
  for any skill go in one list, `src/plugin/requirements.txt` (currently
  `lxml`). A script that needs them is launched as
  `python3 <plugin>/scripts/run_python.py <script.py> [args]`. `run_python.py`
  uses the running interpreter when it already satisfies that file. Otherwise
  it installs a shared venv at `~/.cache/tableau-plugin/venv-<pyver>`
  (`%LOCALAPPDATA%\tableau-plugin\` on Windows) the first time a script needs
  it, and rebuilds that venv when `requirements.txt` changes. There is no
  session-start hook. `run_python.py --bootstrap` prepares the venv and exits,
  for example before going offline.

To add a platform: create `platforms/<name>/{overlay,vars.yaml}` with that
host's manifests and values, then run `python3 build/build.py <name>`.

## Published builds

`.github/workflows/publish-dist.yml` runs on every push to `main`. It builds
the prod plugin, copies `LICENSE.txt` into `plugins/tableau/` (the build script
does not), and commits the tree to a branch:

| Build | Directory | Branch |
|---|---|---|
| Claude prod | `dist/claude/` | `dist/claude` |
| Claude `--slim` | `dist/claude-slim/` | `dist-claude-slim` |
| OpenAI prod | `dist/openai/` | `dist/codex` |

Quick is not published. Install commands are in the sections below.

## Install locally: Codex and ChatGPT desktop

The Codex CLI and the ChatGPT/Codex desktop apps share `~/.codex`, so one
install covers all of them. `reload-plugin.sh` builds the plugin and
(re)installs it. The first argument is `openai` or `claude` (`codex`,
`chatgpt`, and `claude-desktop` are aliases). The second is `test` (the
default), `stage`, `dev`, or `prod`. The script does not build Quick.

```bash
./reload-plugin.sh openai          # test variant (default)
./reload-plugin.sh openai stage    # hosted stage.mcp.tableau.com
./reload-plugin.sh openai dev      # local tableau-mcp over stdio
./reload-plugin.sh openai prod     # published names, dist/openai/
```

The script:

1. creates `.build-venv/` with the build dependencies (first run only);
2. builds `dist/openai-<variant>/` (`dist/openai/` for `prod`);
3. removes any previous `Tableau-<variant>@tableau-plugin-<variant>` install
   (`Tableau@tableau-plugin` for `prod`) and its marketplace;
4. registers that directory as the `tableau-plugin-<variant>` marketplace
   (`tableau-plugin` for `prod`) and installs the plugin with `codex plugin add`.

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

**Install the published build instead.** The `dist/codex` branch is the prod
OpenAI tree:

```bash
codex plugin marketplace add tableau/tableau-plugin --ref dist/codex
codex plugin add Tableau@tableau-plugin
```

## Install locally: Claude desktop

The Claude apps (Desktop, web, Cowork) have no command line for installing
plugins. `claude plugin install` reaches only Claude Code. You build a zip and
upload it in the app. The plugin is saved to your claude.ai account, so after
uploading it once it also appears on claude.ai and on your other machines.

1. **Build the zip:**
   ```bash
   ./reload-plugin.sh claude          # or: ./reload-plugin.sh claude dev
   ```
   This writes `dist/claude-test-tableau.zip` (`dist/claude-tableau.zip` for
   `prod`) and, on macOS, shows it in Finder and opens Claude. For the plugin
   directory's size limit, build the slim zip instead:
   `python3 build/build.py --slim --zip claude` writes
   `dist/claude-slim-tableau.zip`.
2. **Upload it.** In Claude, open **Customize → Plugins**, choose
   **Add → Upload plugin**, and pick the zip.
3. **Connect Tableau.** Open the installed **Tableau** plugin, go to its
   **Connectors** tab, and connect the Tableau connector. Sign in to Tableau
   Cloud or Server when prompted.
4. **Turn on code execution** in Claude's settings. The skills run scripts.
5. **Start a new chat** and try a request such as "show me the Superstore
   dashboard".

**To update,** repeat steps 1 and 2. If the old version is still listed
afterwards, **Remove** it under Customize → Plugins and upload again.

**What runs where:** skills and the Tableau connector work in Chat and Cowork.
The workbook validator installs its Python dependencies the first time
`run_python.py` launches it.

**Optional: update from a GitHub repo instead of uploading.** Create an empty
GitHub repo for the built plugin (not this source repo), then run:

```bash
CLAUDE_MARKETPLACE_REPO=git@github.com:you/tableau-plugin-claude.git ./reload-plugin.sh claude
```

This pushes the built tree to that repo's default branch: `dist/claude-test/`
by default, or `dist/claude/` when the variant is `prod`. Add the repo once
under **Customize → Plugins → Add marketplace** and install **Tableau** from
it. After later runs, click **Check for updates** on the marketplace, or turn
on **Sync automatically**. Private repos need the Claude GitHub App.

The published Claude trees are the `dist/claude` branch (full) and the
`dist-claude-slim` branch (plugin directory). Clone the branch and upload a
zip of `plugins/tableau/`, or add the checkout as a marketplace the same way.

## Install locally: Claude Code

`./reload-plugin.sh claude` builds the zip for the Claude apps. It does not
install into Claude Code. Register the built directory as a marketplace:

```bash
python3 build/build.py --variant test claude
claude plugin marketplace add ./dist/claude-test
claude plugin install tableau-test@tableau-plugin-test
```

In a session, the equivalents are `/plugin marketplace add ./dist/claude-test`
and `/plugin install tableau-test@tableau-plugin-test`.

Prod is `dist/claude/`, plugin `tableau@tableau-plugin`, server
`https://mcp.tableau.com`. The slim tree is for the Claude plugin directory's
size limit, not the usual Claude Code install.

Claude Code copies the plugin into its cache. After editing `src/` or
`platforms/`, uninstall and reinstall:

```bash
claude plugin uninstall tableau-test@tableau-plugin-test
claude plugin marketplace remove tableau-plugin-test
# rebuild, then marketplace add + install again
```

Restart Claude Code or start a new session so the plugin and MCP server load.
Authenticate with `/mcp`, pick `Tableau` (`TableauTest` for the test variant),
and sign in to Tableau Cloud or Server. View images need `Bash(curl *)` and,
if sandboxing is on, the image host. See the next section.

**Published build.** The `dist/claude` branch is the prod tree, with the
marketplace at the branch root. Clone that branch and add the checkout:

```bash
git clone --branch dist/claude --single-branch https://github.com/tableau/tableau-plugin.git tableau-plugin-claude
claude plugin marketplace add ./tableau-plugin-claude
claude plugin install tableau@tableau-plugin
```

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

**Amazon Quick:** `python3 build/build.py quick`, then follow the setup guide
written to `dist/quick/README.md`.

## License

Licensed under the [Apache License 2.0](LICENSE.txt).

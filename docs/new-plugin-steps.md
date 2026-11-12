# Adding a platform

A platform is a host (Claude, ChatGPT/Codex, Amazon Quick, …) that gets its
own build of the Tableau plugin. Skills, references, scripts, and assets stay
in `src/plugin/`. The new platform adds only what that host requires: wording
in `platforms/<name>/vars.yaml`, and manifests, MCP config, and install docs
in `platforms/<name>/overlay/`.

`python3 build/build.py` discovers every directory under `platforms/` that
contains an `overlay/` directory. No registration list to edit for the build
itself.

Existing platforms to copy from:

| Platform | Shape | Start here |
|---|---|---|
| `claude` | One plugin directory the host installs | `platforms/claude/` |
| `openai` | One plugin directory, two manifest generations | `platforms/openai/` |
| `quick` | No plugin format: a connector config plus one folder per skill | `platforms/quick/` |

## 0. Confirm the host needs its own platform

Build and try an existing distribution before adding a directory. A host that
reads Claude marketplaces can use `dist/claude/` as-is. A host that reads
Codex marketplaces can use `dist/openai/`. Add `platforms/<name>/` when the
host's manifest paths, MCP config, tool names, or install steps differ.

Record, from the host's docs and one hands-on install:

- Where a plugin manifest and a marketplace manifest live, and their JSON shape.
- Where the MCP server is declared, and which transport it accepts
  (`http`, `streamable-http`, SSE, stdio).
- Whether sign-in is the user's Tableau OAuth login. The hosted server is
  `https://mcp.tableau.com`. A bearer-token-only client cannot use that server.
- The tool-name prefix the model sees (`mcp__Tableau__search-content`, a
  host-assigned prefix, or the bare name `search-content`).
- Built-in tools for rendering a URL, asking the user to pick an option, and
  running a shell. Presigned view-image URLs are long and short-lived; some
  hosts reject them in a web-fetch tool and need `curl` or Python instead.
- Any package size limit.

## 1. Pick the output shape

**Plugin** (Claude, OpenAI). The build copies `src/plugin/` to
`dist/<name>/plugins/tableau/`, then copies the overlay onto `dist/<name>/`.
Overlay files win on a name collision. `--zip` writes
`dist/<name>-tableau.zip` with the plugin folder at the zip root.

**Standalone skills** (Quick). Set `skills_package:` in `vars.yaml`. The build
does not write `plugins/tableau/`. It writes one self-contained skill folder
per skill, a zip of those folders, and the overlay (connector config and
setup guide) at `dist/<name>/`. `--zip` is skipped; the skills zip is always
written. A skill that links to `../../references/` or `../../scripts/` gets
those files copied inside it. `skills_package.companions` lists extra files a
copied script needs that no link names (`scripts/run_python.py` needs
`requirements.txt`). The build fails if a skill links into another skill, or
if a copied file would overwrite a file the skill already has.

## 2. Add `platforms/<name>/vars.yaml`

Templates are Jinja2 with `StrictUndefined`. A missing key fails the build.
`platform` is set by the build to the directory name. `shipped_skills` is set
by the build to the skill directory names whose `SKILL.md` survives `exclude`.
Do not put those two in the file.

```yaml
assistant_name: Host Name          # how skills refer to the assistant

# Tool-name prefix in skill prose. Use "mcp__Tableau__" when the host
# addresses tools by the MCP server key. Use "" when the prefix is
# host-assigned or unknown; skills then use the bare name (search-content)
# and tell the model to match on the suffix. A non-prod variant rewrites a
# non-empty prefix to the variant server key (mcp__TableauDev__, …).
mcp_prefix: ""

tools:
  render_native: []                # [{name, context}, …] in fallback order
  site_access: ""                  # approves a site, then retries the browser
  js_repl: ""                      # JS REPL fallback for rendering
  elicit: ""                       # ask the user to pick among options

elicit_max_options: 4              # required when tools.elicit is non-empty

show_image: >-
  one sentence telling the model how this host displays a local PNG

capabilities:
  interactive_viz: false           # offer render-interactive-viz first
  native_render: false             # tools.render_native is usable
  native_render_guaranteed: false  # render_native[0] is always present
  js_repl: false                   # tools.js_repl exists
  shell_download_only: false       # download images with curl/Python only
  browser_verify: false            # model can click through a published viz

exclude:
  - "skills/*/agents/openai.yaml"  # drop unless this host reads that file
```

`skills/*/agents/openai.yaml` is OpenAI skill metadata (display name, default
prompt). Every other platform excludes it.

Leave a tool name empty when the host has no equivalent. The templates fall
back: numbered list instead of elicitation, hyperlink plus PNG instead of an
in-app browser. `native_render: true` with an empty `render_native` list
breaks the render section, because the template indexes `render_native[0]`.
`native_render_guaranteed: true` has the same requirement.

These keys are read by `src/plugin/**/*.j2` today: `assistant_name`,
`mcp_prefix`, `show_image`, `elicit_max_options`, `tools.render_native`,
`tools.site_access`, `tools.js_repl`, `tools.elicit`, and the capability flags
above. Extra keys are ignored. A behavior the flags cannot express is a new
flag in every platform's `vars.yaml` plus a `{% if %}` in the shared template,
not a forked skill.

Optional blocks, copied from the platform that already uses them:

- `mcp_env_passthrough: true` — dev variant only. Lists `TABLEAU_MCP_DIR` in
  the stdio server's `env_vars`. Set this when the host gives a plugin MCP
  server a minimal environment (OpenAI). Leave it off when the host already
  passes the process environment through (Claude, Quick).
- `slim:` — size-reduced build via `build.py --slim`. See the `slim:` block
  in `platforms/claude/vars.yaml`. Only add it when the host rejects the full
  package.
- `skills_package:` — standalone-skill layout. See `platforms/quick/vars.yaml`.
  That layout also uses `mcp_url` (the connector URL the setup guide prints;
  `--variant` overwrites it) and, in overlay templates, `variant_label` and
  `server_key` (both set by the build when `skills_package` is present).

## 3. Add `platforms/<name>/overlay/`

Files are copied onto `dist/<name>/` verbatim. A file ending in `.j2` is
rendered with `vars.yaml` and the suffix is stripped, same as the payload.
Put the prod MCP URL in the overlay (`https://mcp.tableau.com`). Variants
repoint it; do not template the URL yourself.

### Plugin layout

Mirror the host's required paths. Claude's overlay is the smaller example:

```
platforms/claude/overlay/
  .claude-plugin/marketplace.json
  plugins/tableau/.claude-plugin/plugin.json
  plugins/tableau/.mcp.json
  plugins/tableau/README.md
```

The shared payload already lands in `plugins/tableau/`, so the overlay only
adds the manifest, `.mcp.json`, and the README the host shows to users.
OpenAI adds a marketplace at `.agents/plugins/marketplace.json`, a portable
`plugins/tableau/plugin.json` and `plugins/tableau/mcp.json`, plus the legacy
`.codex-plugin/plugin.json` and `.mcp.json` current CLIs still read.

Match the license and author fields already in those manifests: `Apache-2.0`,
author `Salesforce, Inc.`, repository `https://github.com/tableau/tableau-plugin`,
and the same privacy-policy URL. Use the same `version` as the other
platforms' `plugin.json` files unless you are cutting a release.

Two strings the variant rewrite depends on:

- `name` in the marketplace JSON and in the plugin manifest. `--variant test`
  appends `-test` (and `-stage`, `-dev`). Prod is unchanged. Claude uses a
  lowercase plugin name (`tableau` → `tableau-test`) and marketplace name
  `tableau-plugin`. Use the name the host's install command expects, not a
  display string.
- `displayName`, anywhere in those JSON files. The variant appends ` (Test)`,
  ` (Stage)`, or ` (Dev)`.

MCP config must be one JSON object whose `mcpServers` has exactly one entry.
Prod's server key is `Tableau`. A variant replaces that map with one entry
keyed `TableauTest`, `TableauStage`, or `TableauDev`, and either swaps in
`https://test.mcp.tableau.com` / `https://stage.mcp.tableau.com` or, for
`dev`, a stdio server that runs `node` against `TABLEAU_MCP_DIR`.

`--variant` only edits these paths. A manifest or MCP file anywhere else is
copied unchanged, so a test build would keep the prod name and the prod URL.

| File | What `--variant` does |
|---|---|
| `.agents/plugins/marketplace.json` | suffixes `name`, each plugin `name`, and every `displayName` |
| `.claude-plugin/marketplace.json` | same |
| `plugins/tableau/plugin.json` | suffixes `name` and every `displayName` |
| `plugins/tableau/.codex-plugin/plugin.json` | same |
| `plugins/tableau/.claude-plugin/plugin.json` | same |
| `plugins/tableau/.mcp.json` | repoints the single `mcpServers` entry |
| `plugins/tableau/mcp.json` | same |
| `connector/mcp.json` | same (standalone-skill layout) |

If the host requires a different path, add it to `apply_variant` or
`MCP_CONFIG_PATHS` in `build/build.py` before relying on `--variant`.

### Standalone-skill layout

```
platforms/quick/overlay/
  README.md.j2                 # setup guide; uses variant_label, mcp_url, server_key, shipped_skills
  connector/mcp.json           # prod URL; variants repoint this path
```

There is no plugin manifest. The README is the install doc.

### README

Ship end-user install and auth steps in the overlay (OpenAI's
`overlay/README.md`, Claude's `plugins/tableau/README.md`, Quick's
`README.md.j2`). Cover where to install, how the user signs in to Tableau,
and that there is no API key. Tag anything you have not confirmed on the host
with `VERIFY`.

## 4. Build

From the repo root, with Jinja2 and PyYAML installed
(`pip install -r build/requirements.txt`, or use `.build-venv/` after one
`./reload-plugin.sh` run):

```bash
python3 build/build.py <name>
python3 build/build.py --variant test <name>
python3 build/build.py --zip <name>          # plugin layout only
```

Then check `dist/<name>/`:

- `.j2` sources are gone; the rendered file has the host's `assistant_name`
  and tool prefix.
- Prod MCP config points at `https://mcp.tableau.com` with server key
  `Tableau`. The test build points at `https://test.mcp.tableau.com` with
  key `TableauTest`, and the plugin and marketplace names end in `-test`.
- `skills/*/agents/openai.yaml` is absent unless this platform is OpenAI.
- For a plugin layout, the manifest sits inside `plugins/tableau/` at the
  path the host reads. For standalone skills, each `skills/<skill>/` folder
  contains the references and scripts it links to, and `tableau-skills.zip`
  (or the name in `skills_package.zip`) is next to them.

`python3 build/build.py --check <name>` compares `dist/<name>/` to a fresh
build without rewriting it. `dist/` is git-ignored.

## 5. Install on the host and confirm one skill

Use the test or dev variant so it can sit beside a published Tableau plugin.
Dev needs `TABLEAU_MCP_DIR` in this repo's `.env`, pointing at a
[tableau-mcp](https://github.com/tableau/tableau-mcp) checkout that has been
built with `npm run build`.

Confirm all of these before calling the platform done:

1. The host lists the skills and the MCP server.
2. Sign-in opens the Tableau OAuth flow and later tool calls run as that user.
3. The model sees tool names that match `mcp_prefix` (or the bare name, when
   the prefix is empty).
4. A content-viewer request ("show me \<a dashboard you know\>") finds the
   view and shows it the way `show_image` describes.
5. A workbook-authoring request can run `scripts/run_python.py` if you set
   `shell` capability flags that promise a shell.

Write the install steps that worked into the overlay README, and a short
"Install locally: \<host\>" section in the repo `README.md`.

## 6. Local reload and publishing

Optional, and only after step 5 works.

`reload-plugin.sh` builds with `--zip` and defaults to the test variant. It
only knows `openai` and `claude`: the OpenAI branch reinstalls into Codex,
and the Claude branch writes the upload zip. A new plugin-layout host needs
a case in that script if you want the same one-command loop. Standalone-skill
hosts stay a manual install; the script does not build Quick.

`.github/workflows/publish-dist.yml` builds prod on every push to `main` and
pushes the tree to a dist branch. Add a matrix row (`name`, `platform`,
`flags`, `branch`) to publish this platform. The workflow copies `LICENSE.txt`
into `plugins/tableau/`, which assumes the plugin layout. Quick is not
published. The branch name does not have to match the platform directory
(`openai` publishes to `dist/codex`).

Name the branch `dist/<name>` or `dist-<name>`. The active `dist` ruleset
([rules/26991979](https://github.com/tableau/tableau-plugin/rules/26991979))
already includes `refs/heads/dist/*` and `refs/heads/dist-*`, so a new branch
in that shape is covered without editing the ruleset. It blocks deletion,
force-pushes, and every other push. There is no bypass actor, so the publish
workflow's `GITHUB_TOKEN` push is rejected too. Before the first publish of
this platform (and for the existing `dist/claude`, `dist/codex`, and
`dist-claude-slim` branches), add the GitHub Actions app as a bypass actor on
that ruleset. Leave deletion and non-fast-forward in place.

The `main` ruleset is pull-request only (one approving review, code-owner
review, resolved threads, squash merges). It does not name platforms. There
are no GitHub environments and no other rulesets. `CODEOWNERS` is ECCN and
GUS metadata, not a list of owners.

## Checklist

- [ ] Host does not already load `dist/claude/` or `dist/openai/` unchanged
- [ ] `platforms/<name>/vars.yaml` with the keys in step 2
- [ ] `platforms/<name>/overlay/` with manifests (or connector config), MCP
      config at a path `--variant` rewrites, and an install README
- [ ] `build.py` updated if the manifest or MCP path is new
- [ ] `python3 build/build.py <name>` and `--variant test` succeed
- [ ] Installed on the host: OAuth, tool names, one content-viewer request
- [ ] Repo `README.md` has the install steps
- [ ] `reload-plugin.sh` and `publish-dist.yml` updated if this host should
      have them
- [ ] Published branch is `dist/<name>` or `dist-<name>` (already covered by
      the `dist` ruleset)
- [ ] GitHub Actions is a bypass actor on the `dist` ruleset, so the workflow
      can push

# Tableau Codex Plugin Manifests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make this repository an installable Codex marketplace containing one Tableau plugin with bundled skills and the hosted Tableau MCP server.

**Architecture:** The repository root is the marketplace root, while all distributable plugin resources live under `plugins/tableau/`. The marketplace manifest points to that package; the plugin manifest points only to resources inside the package.

**Tech Stack:** JSON manifests, Markdown skill/documentation files, Python 3 standard library for structural validation.

## Global Constraints

- Marketplace ID is exactly `tableau-plugin-marketplace`.
- Plugin ID is exactly `tableau`.
- Hosted MCP URL is exactly `https://mcp.tableau.com`.
- Installation policy is `AVAILABLE`; authentication policy is `ON_INSTALL`.
- Component paths start with `./` and remain inside `plugins/tableau/`.
- Do not add apps, hooks, logos, screenshots, license metadata, or unverified legal URLs.
- Do not modify `.cursor/agent.md`.
- Do not create a git commit unless the user explicitly requests one.

## File map

- `.gitignore`: excludes the local Sentry reference checkout from the Tableau marketplace.
- `.agents/plugins/marketplace.json`: repository-level marketplace catalog and install policy.
- `plugins/tableau/.codex-plugin/plugin.json`: plugin identity, bundled components, and install-surface copy.
- `plugins/tableau/.mcp.json`: hosted Tableau MCP server declaration.
- `plugins/tableau/skills/validate-workbook-package/SKILL.md`: packaged copy of the existing workbook validation skill, in a directory matching its frontmatter name.
- `README.md`: repository purpose, contents, and Codex installation commands.

---

### Task 1: Build the installable marketplace package

**Files:**
- Create: `.gitignore`
- Create: `.agents/plugins/marketplace.json`
- Create: `plugins/tableau/.codex-plugin/plugin.json`
- Create: `plugins/tableau/.mcp.json`
- Move: `skills/validate-twb/SKILL.md` to `plugins/tableau/skills/validate-workbook-package/SKILL.md`

**Interfaces:**
- Produces marketplace reference `tableau@tableau-plugin-marketplace`.
- Produces plugin component paths `./skills/` and `./.mcp.json`.
- Produces MCP server key `tableau` with an HTTP transport URL.

- [ ] **Step 1: Run the structural check before creating the manifests**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

required = [
    Path(".agents/plugins/marketplace.json"),
    Path("plugins/tableau/.codex-plugin/plugin.json"),
    Path("plugins/tableau/.mcp.json"),
    Path("plugins/tableau/skills/validate-workbook-package/SKILL.md"),
]
missing = [str(path) for path in required if not path.is_file()]
assert not missing, f"missing package files: {missing}"
PY
```

Expected: FAIL with all four package files listed as missing.

- [ ] **Step 2: Create the marketplace manifest**

Create `.agents/plugins/marketplace.json` with:

```json
{
  "name": "tableau-plugin-marketplace",
  "interface": {
    "displayName": "Tableau Plugins"
  },
  "plugins": [
    {
      "name": "tableau",
      "source": {
        "source": "local",
        "path": "./plugins/tableau"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

- [ ] **Step 3: Create the plugin manifest**

Create `plugins/tableau/.codex-plugin/plugin.json` with:

```json
{
  "name": "tableau",
  "version": "0.1.0",
  "description": "Tableau plugin for Codex with workbook authoring, visual analysis, and MCP capabilities.",
  "author": {
    "name": "Tableau",
    "url": "https://www.tableau.com"
  },
  "homepage": "https://www.tableau.com",
  "repository": "https://github.com/tableau/plugin-codex",
  "keywords": [
    "tableau",
    "analytics",
    "data-visualization",
    "workbooks"
  ],
  "skills": "./skills/",
  "mcpServers": "./.mcp.json",
  "interface": {
    "displayName": "Tableau",
    "shortDescription": "Analyze data and build or modify Tableau workbooks.",
    "longDescription": "Teach Codex to analyze data, build and modify Tableau workbooks, validate workbook packages, and use the hosted Tableau MCP server.",
    "developerName": "Tableau",
    "category": "Productivity",
    "capabilities": [
      "Read",
      "Write"
    ],
    "websiteURL": "https://www.tableau.com",
    "defaultPrompt": [
      "Analyze this data with Tableau",
      "Help me build a Tableau visualization",
      "Validate this Tableau workbook package"
    ]
  }
}
```

- [ ] **Step 4: Create the MCP manifest**

Create `plugins/tableau/.mcp.json` with:

```json
{
  "mcpServers": {
    "tableau": {
      "type": "http",
      "url": "https://mcp.tableau.com"
    }
  }
}
```

- [ ] **Step 5: Move the existing skill into the plugin package**

Run:

```bash
mkdir -p "plugins/tableau/skills/validate-workbook-package"
mv "skills/validate-twb/SKILL.md" "plugins/tableau/skills/validate-workbook-package/SKILL.md"
if [ -d "skills/validate-twb/scripts" ]; then
  mv "skills/validate-twb/scripts" "plugins/tableau/skills/validate-workbook-package/scripts"
fi
rmdir "skills/validate-twb" "skills"
```

Do not change the skill body in this task.

- [ ] **Step 6: Exclude the local sample marketplace**

Create `.gitignore` with:

```gitignore
# Local reference checkout used to model this plugin.
sample-plugin/
```

Run `git check-ignore -q sample-plugin`.

Expected: PASS so the Sentry reference checkout cannot be added to the Tableau
marketplace accidentally.

- [ ] **Step 7: Validate JSON, identities, component paths, and the MCP declaration**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
marketplace_path = root / ".agents/plugins/marketplace.json"
plugin_root = root / "plugins/tableau"
plugin_path = plugin_root / ".codex-plugin/plugin.json"
mcp_path = plugin_root / ".mcp.json"
skill_path = plugin_root / "skills/validate-workbook-package/SKILL.md"

marketplace = json.loads(marketplace_path.read_text())
plugin = json.loads(plugin_path.read_text())
mcp = json.loads(mcp_path.read_text())

entry = marketplace["plugins"][0]
assert marketplace["name"] == "tableau-plugin-marketplace"
assert entry["name"] == plugin["name"] == "tableau"
assert entry["source"] == {"source": "local", "path": "./plugins/tableau"}
assert entry["policy"] == {
    "installation": "AVAILABLE",
    "authentication": "ON_INSTALL",
}
assert plugin["skills"] == "./skills/"
assert plugin["mcpServers"] == "./.mcp.json"
assert skill_path.is_file()
frontmatter_name = next(
    line.split(":", 1)[1].strip()
    for line in skill_path.read_text().splitlines()
    if line.startswith("name:")
)
assert skill_path.parent.name == frontmatter_name
assert mcp["mcpServers"]["tableau"] == {
    "type": "http",
    "url": "https://mcp.tableau.com",
}

for key in ("skills", "mcpServers"):
    relative = plugin[key]
    assert relative.startswith("./")
    resolved = (plugin_root / relative).resolve()
    assert resolved.is_relative_to(plugin_root.resolve())
    assert resolved.exists()

print("Tableau plugin manifests are structurally valid.")
PY
```

Expected: PASS and print `Tableau plugin manifests are structurally valid.`

### Task 2: Document installation and package contents

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes marketplace reference `tableau@tableau-plugin-marketplace`.
- Documents GitHub marketplace source `tableau/plugin-codex`.

- [ ] **Step 1: Verify the README does not yet describe installation**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

text = Path("README.md").read_text()
assert "codex plugin marketplace add tableau/plugin-codex" in text
assert "codex plugin add tableau@tableau-plugin-marketplace" in text
PY
```

Expected: FAIL because the current README contains only a heading and `TO-DO`.

- [ ] **Step 2: Replace the README with the installable plugin documentation**

Write `README.md` as:

````markdown
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

- Tableau workbook package validation skill
- Hosted Tableau MCP server at <https://mcp.tableau.com>
````

- [ ] **Step 3: Validate the README and all JSON manifests**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

readme = Path("README.md").read_text()
assert "codex plugin marketplace add tableau/plugin-codex" in readme
assert "codex plugin add tableau@tableau-plugin-marketplace" in readme

for path in (
    Path(".agents/plugins/marketplace.json"),
    Path("plugins/tableau/.codex-plugin/plugin.json"),
    Path("plugins/tableau/.mcp.json"),
):
    json.loads(path.read_text())
    print(f"valid JSON: {path}")
PY
```

Expected: PASS and print one `valid JSON` line for each manifest.

- [ ] **Step 4: Check diagnostics for every created or modified file**

Read IDE diagnostics for:

```text
.agents/plugins/marketplace.json
plugins/tableau/.codex-plugin/plugin.json
plugins/tableau/.mcp.json
plugins/tableau/skills/validate-workbook-package/SKILL.md
README.md
```

Expected: no new diagnostics.


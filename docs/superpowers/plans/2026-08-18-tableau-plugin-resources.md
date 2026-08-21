# Tableau Plugin Resources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Tableau workbook resources through Codex skills and provide a deterministic local CLI that can discover, inspect, instantiate, inject, and validate a safe subset of Tableau bookmark templates.

**Architecture:** All resources are indexed in one generated catalog. Skills provide Codex discovery entry points, while a Python standard-library CLI performs explicit field mapping and bounded XML transformations against starter or existing `.twb` files; publishing remains in the existing Tableau API workflow.

**Tech Stack:** Python 3.11+ standard library (`argparse`, `dataclasses`, `hashlib`, `json`, `pathlib`, `re`, `tempfile`, `unittest`, `uuid`, `xml.etree.ElementTree`), Markdown Agent Skills, Tableau `.tbm`/`.twb` XML, JSON.

## Global Constraints

- Do not depend on Tableau Desktop or its external client API.
- Do not add third-party Python packages.
- Never modify an input `.twb` unless the caller passes `--overwrite`.
- Never classify a template as executable solely from its filename or naming cohort.
- Never fabricate Tableau datasource connection metadata.
- Reference resources are readable but must fail closed if passed to `instantiate` or `inject`.
- Every generated catalog entry records a SHA-256 integrity hash.
- Pin imported Pulse resources to `tableau/tableau-mcp` commit `3e77dd40997a2ffcb89fb25fa40c9abc1ac59a71`.
- Keep authentication, package validation, and publishing outside the resource CLI.
- Do not create a git commit unless the user explicitly requests one.

## File map

- `plugins/tableau/resources/catalog.json`: generated resource index consumed at runtime.
- `plugins/tableau/resources/catalog-overrides.json`: reviewed metadata for parameter types and stricter classification.
- `plugins/tableau/resources/provenance.json`: pinned upstream source and import paths.
- `plugins/tableau/resources/templates/{executable,reference}/`: classified Tableau bookmarks.
- `plugins/tableau/resources/examples/`: XML-authoring examples.
- `plugins/tableau/resources/references/`: schema, command, snippet, and diff corpora.
- `plugins/tableau/resources/starters/minimal-workbook.twb`: datasource-free workbook shell.
- `plugins/tableau/scripts/generate_resource_catalog.py`: deterministic catalog generator and eligibility classifier.
- `plugins/tableau/scripts/tableau_resources.py`: discovery and workbook-transformation CLI.
- `plugins/tableau/tests/`: standard-library unit and golden-fixture tests.
- `plugins/tableau/skills/tableau-workbook-authoring/SKILL.md`: primary Codex workflow.
- `plugins/tableau/skills/tableau-pulse-insights/SKILL.md`: focused Pulse Insights entry point.
- `plugins/tableau/README.md`: resource CLI reference for maintainers.
- `plugins/tableau/.codex-plugin/plugin.json`: plugin descriptions and starter prompts.

---

### Task 1: Normalize and pin the resource corpus

**Files:**
- Move: `plugins/tableau/data/templates/*.tbm` to temporary classified resource directories.
- Move: `plugins/tableau/data/examples/*.json` to `plugins/tableau/resources/examples/`.
- Move: `plugins/tableau/data/{corpus,twb-example-index,workbook-schema-reference,tableau-desktop-commands-reference}.json` to `plugins/tableau/resources/references/`.
- Create: `plugins/tableau/resources/provenance.json`
- Create: `plugins/tableau/resources/catalog-overrides.json`
- Create: `plugins/tableau/resources/starters/minimal-workbook.twb`
- Test: `plugins/tableau/tests/test_resource_layout.py`

**Interfaces:**
- Produces canonical resource root `plugins/tableau/resources`.
- Produces provenance schema `{schemaVersion, sources[]}`.
- Produces overrides keyed by resource ID.

- [ ] **Step 1: Write the failing resource-layout test**

```python
# plugins/tableau/tests/test_resource_layout.py
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

PLUGIN = Path(__file__).resolve().parents[1]
RESOURCES = PLUGIN / "resources"


class ResourceLayoutTest(unittest.TestCase):
    def test_required_layout_and_pinned_pulse_resources(self) -> None:
        provenance = json.loads((RESOURCES / "provenance.json").read_text())
        self.assertEqual(provenance["schemaVersion"], 1)
        self.assertEqual(
            provenance["sources"][0]["commit"],
            "3e77dd40997a2ffcb89fb25fa40c9abc1ac59a71",
        )
        for name in ("insights__bar_chart.tbm", "insights__line_chart.tbm"):
            matches = list((RESOURCES / "templates").glob(f"*/{name}"))
            self.assertEqual(len(matches), 1, name)
            self.assertEqual(ET.parse(matches[0]).getroot().tag, "bookmark")

    def test_every_declared_import_hash_matches(self) -> None:
        provenance = json.loads((RESOURCES / "provenance.json").read_text())
        for source in provenance["sources"]:
            for imported in source["imports"]:
                matches = list((RESOURCES / "templates").glob(f"*/{imported['filename']}"))
                self.assertEqual(len(matches), 1, imported["filename"])
                path = matches[0]
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(digest, imported["sha256"], path)

    def test_starter_is_datasource_free_workbook(self) -> None:
        root = ET.parse(RESOURCES / "starters/minimal-workbook.twb").getroot()
        self.assertEqual(root.tag, "workbook")
        datasources = root.find("datasources")
        self.assertIsNotNone(datasources)
        self.assertEqual(len(list(datasources)), 0)
        self.assertIsNotNone(root.find("worksheets"))
        self.assertIsNotNone(root.find("windows"))
```

- [ ] **Step 2: Run the layout test and verify it fails**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_resource_layout.py -v
```

Expected: FAIL because `resources/provenance.json` and the normalized layout do not exist.

- [ ] **Step 3: Create the normalized directories and move the current corpus**

Run:

```bash
mkdir -p \
  "plugins/tableau/resources/templates/unclassified" \
  "plugins/tableau/resources/examples" \
  "plugins/tableau/resources/references" \
  "plugins/tableau/resources/starters"
mv plugins/tableau/data/templates/*.tbm "plugins/tableau/resources/templates/unclassified/"
mv plugins/tableau/data/examples/*.json "plugins/tableau/resources/examples/"
mv plugins/tableau/data/corpus.json "plugins/tableau/resources/references/"
mv plugins/tableau/data/twb-example-index.json "plugins/tableau/resources/references/"
mv plugins/tableau/data/workbook-schema-reference.json "plugins/tableau/resources/references/"
mv plugins/tableau/data/tableau-desktop-commands-reference.json "plugins/tableau/resources/references/"
rmdir "plugins/tableau/data/examples" "plugins/tableau/data/templates" "plugins/tableau/data"
```

- [ ] **Step 4: Import the two pinned Pulse Insights bookmarks**

Run both commands at the pinned commit:

```bash
gh api "repos/tableau/tableau-mcp/contents/src/desktop/data/templates/insights__bar_chart.tbm?ref=3e77dd40997a2ffcb89fb25fa40c9abc1ac59a71" \
  --jq '.content' | base64 --decode \
  > "plugins/tableau/resources/templates/unclassified/insights__bar_chart.tbm"
gh api "repos/tableau/tableau-mcp/contents/src/desktop/data/templates/insights__line_chart.tbm?ref=3e77dd40997a2ffcb89fb25fa40c9abc1ac59a71" \
  --jq '.content' | base64 --decode \
  > "plugins/tableau/resources/templates/unclassified/insights__line_chart.tbm"
```

- [ ] **Step 5: Create provenance and reviewed overrides**

Create `provenance.json` with source repository, commit, and an `imports`
array. Each import contains `filename`, `upstreamPath`, and `sha256`; omitting
the tier directory keeps provenance stable when classification moves a file.
Generate hashes from local bytes; do not hand-copy them.

Create `catalog-overrides.json`:

```json
{
  "schemaVersion": 1,
  "resources": {
    "insights__bar_chart": {
      "family": "pulse-insights",
      "intent": "Rank products by ARR within a date range",
      "parameters": {
        "DATE_MIN": {"type": "date", "required": true},
        "DATE_MAX": {"type": "date", "required": true},
        "DIRECTION": {
          "type": "enum",
          "required": true,
          "allowed": ["ASC", "DESC"]
        }
      }
    },
    "insights__line_chart": {
      "family": "pulse-insights",
      "intent": "Show ARR over close date with a trend line",
      "parameters": {}
    }
  }
}
```

- [ ] **Step 6: Create the minimal workbook starter**

```xml
<?xml version='1.0' encoding='utf-8' ?>
<workbook original-version='18.1' source-build='plugin-codex' source-platform='mac' version='18.1'>
  <document-format-change-manifest>
    <WindowsPersistSimpleIdentifiers />
  </document-format-change-manifest>
  <preferences />
  <datasources />
  <worksheets />
  <windows />
</workbook>
```

- [ ] **Step 7: Generate provenance hashes and rerun the test**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_resource_layout.py -v
```

Expected: PASS with 3 tests.

### Task 2: Generate the searchable resource catalog

**Files:**
- Create: `plugins/tableau/scripts/generate_resource_catalog.py`
- Create: `plugins/tableau/resources/catalog.json`
- Create: `plugins/tableau/tests/test_generate_resource_catalog.py`

**Interfaces:**
- Produces `generate_catalog(plugin_root: Path) -> dict[str, object]`.
- Produces one entry per resource with `id`, `type`, `family`, `intent`, `path`, `tier`, `classificationReasons`, `datasources`, `fields`, `parameters`, `keywords`, and `sha256`.
- Moves each `.tbm` from `templates/unclassified` into `templates/executable` or `templates/reference`.

- [ ] **Step 1: Write failing catalog tests**

```python
# plugins/tableau/tests/test_generate_resource_catalog.py
import json
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))
from generate_resource_catalog import generate_catalog


class CatalogGenerationTest(unittest.TestCase):
    def test_catalog_is_deterministic_and_complete(self) -> None:
        first = generate_catalog(PLUGIN)
        second = generate_catalog(PLUGIN)
        self.assertEqual(first, second)
        ids = [item["id"] for item in first["resources"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("insights__bar_chart", ids)
        self.assertIn("insights__line_chart", ids)

    def test_pulse_bar_contract_is_inferred_and_overridden(self) -> None:
        catalog = generate_catalog(PLUGIN)
        item = next(r for r in catalog["resources"] if r["id"] == "insights__bar_chart")
        self.assertEqual(item["family"], "pulse-insights")
        self.assertEqual(item["tier"], "executable")
        self.assertEqual(
            sorted(item["parameters"]),
            ["DATE_MAX", "DATE_MIN", "DIRECTION"],
        )
        self.assertEqual(
            {field["sourceField"] for field in item["fields"]},
            {"ARR", "Close Date", "Product"},
        )

    def test_inline_datasource_template_is_reference_only(self) -> None:
        catalog = generate_catalog(PLUGIN)
        item = next(
            r for r in catalog["resources"]
            if r["id"] == "magnitude__horizontal-bar__compare-discrete-categories-from-zero"
        )
        self.assertEqual(item["tier"], "reference")
        self.assertIn("inline-datasource", item["classificationReasons"])

    def test_checked_in_catalog_matches_generation(self) -> None:
        expected = generate_catalog(PLUGIN)
        actual = json.loads((PLUGIN / "resources/catalog.json").read_text())
        self.assertEqual(actual, expected)
```

- [ ] **Step 2: Run the catalog tests and verify they fail**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_generate_resource_catalog.py -v
```

Expected: FAIL because `generate_resource_catalog` does not exist.

- [ ] **Step 3: Implement bookmark metadata extraction**

Implement these typed functions in `generate_resource_catalog.py`:

- `sha256(path: Path) -> str`
- `strip_brackets(value: str) -> str`
- `extract_parameters(text: str) -> list[str]`
- `extract_bookmark(path: Path) -> dict[str, object]`
- `classify_bookmark(metadata: dict[str, object]) -> tuple[str, list[str]]`
- `generate_catalog(plugin_root: Path) -> dict[str, object]`

`extract_bookmark` must:

1. Parse the bookmark with `ElementTree`.
2. Collect unique donor datasource names from `datasource@name`,
   `datasource-dependencies@datasource`, and qualified field references.
3. Build a column dictionary from each `<column>` and a column-instance map
   from each `<column-instance>`.
4. Walk rows, columns, marks encodings, filters, slices, titles, and reference
   lines for placed field references.
5. Resolve every placed column instance to a base source field, datatype,
   role, derivation, and shelf.
6. Extract uppercase `{{PARAMETER}}` names without treating
   `{{DATASOURCE}}` or `{{field_base_N}}` as explicit parameters.
7. Detect inline datasources, connections, viz extensions, unresolved field
   references, missing column metadata, and calculation dependencies.

`classify_bookmark` returns `reference` with stable sorted reason IDs whenever
any blocker exists:

```python
BLOCKERS = {
    "multiple-datasources",
    "inline-datasource",
    "connection-dependency",
    "viz-extension",
    "missing-column-metadata",
    "unresolved-field-reference",
    "external-calculation-dependency",
    "invalid-bookmark-shape",
}
```

Overrides may provide family, intent, and parameter validation, but may not
remove a blocker or promote a failed resource to executable.

- [ ] **Step 4: Implement deterministic output and classification moves**

Scan all three template directories (`unclassified`, `executable`, and
`reference`) and compute each entry's canonical tier path from classification,
not its current location. Sort catalog entries by `id`, sort all string arrays,
serialize with `indent=2`, and end with a newline. In `--write` mode, move
bookmarks into their tier directory only after all entries are generated
successfully; preserve file bytes. In `--check` mode, perform no writes and
exit 1 if catalog content or physical tier paths differ from generation.

The top-level shape is:

```json
{
  "schemaVersion": 1,
  "generatedFrom": {
    "provenance": "./provenance.json",
    "overrides": "./catalog-overrides.json"
  },
  "resources": []
}
```

- [ ] **Step 5: Generate the catalog and run the tests**

Run:

```bash
python3 plugins/tableau/scripts/generate_resource_catalog.py \
  --plugin-root plugins/tableau \
  --write
python3 -m unittest plugins/tableau/tests/test_generate_resource_catalog.py -v
```

Expected: PASS with 4 tests and a checked-in `resources/catalog.json`.

### Task 3: Add catalog discovery and inspection commands

**Files:**
- Create: `plugins/tableau/scripts/tableau_resources.py`
- Create: `plugins/tableau/tests/test_tableau_resources_discovery.py`

**Interfaces:**
- Produces `load_catalog(plugin_root: Path) -> dict[str, object]`.
- Produces `search_resources(catalog, query, family, resource_type, tier) -> list[dict[str, object]]`.
- CLI commands: `list` and `inspect`.
- JSON output is the default; `--format text` produces concise human-readable output.

- [ ] **Step 1: Write failing discovery tests**

```python
# plugins/tableau/tests/test_tableau_resources_discovery.py
import json
from pathlib import Path
import subprocess
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
CLI = PLUGIN / "scripts/tableau_resources.py"


class ResourceDiscoveryTest(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_list_filters_pulse_executable_resources(self) -> None:
        result = self.run_cli("list", "--family", "pulse-insights", "--tier", "executable")
        self.assertEqual(result.returncode, 0, result.stderr)
        ids = [item["id"] for item in json.loads(result.stdout)]
        self.assertEqual(ids, ["insights__bar_chart", "insights__line_chart"])

    def test_list_searches_intent_and_keywords(self) -> None:
        result = self.run_cli("list", "--query", "trend ARR")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("insights__line_chart", result.stdout)

    def test_inspect_returns_mapping_contract(self) -> None:
        result = self.run_cli("inspect", "insights__bar_chart")
        self.assertEqual(result.returncode, 0, result.stderr)
        item = json.loads(result.stdout)
        self.assertEqual(item["tier"], "executable")
        self.assertTrue(item["fields"])

    def test_unknown_resource_fails_closed(self) -> None:
        result = self.run_cli("inspect", "does-not-exist")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown resource", result.stderr)
```

- [ ] **Step 2: Run the discovery tests and verify they fail**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_tableau_resources_discovery.py -v
```

Expected: FAIL because the CLI does not exist.

- [ ] **Step 3: Implement catalog loading, search scoring, and command parsing**

Implement these typed functions:

- `load_catalog(plugin_root: Path) -> dict[str, object]`
- `find_resource(catalog: dict[str, object], resource_id: str) -> dict[str, object]`
- `search_resources(catalog: dict[str, object], *, query: str | None, family: str | None, resource_type: str | None, tier: str | None) -> list[dict[str, object]]`
- `build_parser() -> argparse.ArgumentParser`
- `main(argv: list[str] | None = None) -> int`

Search splits the query into lowercase alphanumeric terms. An entry matches
only when every term appears in its ID, intent, family, or keywords. Sort exact
ID matches first, then entries with terms in intent, then by ID.

The CLI discovers its plugin root from
`Path(__file__).resolve().parents[1]`; it must not depend on the current working
directory.

- [ ] **Step 4: Run discovery tests**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_tableau_resources_discovery.py -v
```

Expected: PASS with 4 tests.

### Task 4: Render executable bookmarks with explicit mappings

**Files:**
- Modify: `plugins/tableau/scripts/tableau_resources.py`
- Create: `plugins/tableau/tests/fixtures/target-datasource.xml`
- Create: `plugins/tableau/tests/test_tableau_resources_render.py`

**Interfaces:**
- Produces `parse_assignments(values: list[str]) -> dict[str, str]`.
- Produces `render_bookmark(plugin_root, resource_id, worksheet_name, datasource_name, field_mappings, parameters) -> tuple[str, str]` for worksheet and window fragments.
- Consumes catalog field/parameter contracts.

- [ ] **Step 1: Add failing mapping and rendering tests**

Use a fixture datasource named `Sales Data` with fields `Revenue`,
`Transaction Date`, and `Offering`.

```python
def test_render_pulse_bar_rewrites_all_donor_references(self) -> None:
    worksheet, window = render_bookmark(
        plugin_root=PLUGIN,
        resource_id="insights__bar_chart",
        worksheet_name="ARR by Offering",
        datasource_name="Sales Data",
        field_mappings={
            "ARR": "Revenue",
            "Close Date": "Transaction Date",
            "Product": "Offering",
        },
        parameters={
            "DATE_MIN": "2026-01-01",
            "DATE_MAX": "2026-06-30",
            "DIRECTION": "DESC",
        },
    )
    combined = worksheet + window
    self.assertNotIn("Sample - Superstore", combined)
    self.assertNotIn("{{", combined)
    self.assertIn("[Sales Data].[sum:Revenue:qk]", combined)
    self.assertIn("[Sales Data].[none:Offering:nk]", combined)
    self.assertIn("#2026-01-01#", combined)
    self.assertIn("name='ARR by Offering'", combined)

def test_missing_required_mapping_fails(self) -> None:
    with self.assertRaisesRegex(ResourceError, "Missing field mappings: Product"):
        render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name="Incomplete",
            datasource_name="Sales Data",
            field_mappings={"ARR": "Revenue", "Close Date": "Transaction Date"},
            parameters={
                "DATE_MIN": "2026-01-01",
                "DATE_MAX": "2026-06-30",
                "DIRECTION": "DESC",
            },
        )

def test_reference_resource_fails_closed(self) -> None:
    with self.assertRaisesRegex(ResourceError, "reference-only"):
        render_bookmark(
            plugin_root=PLUGIN,
            resource_id="magnitude__horizontal-bar__compare-discrete-categories-from-zero",
            worksheet_name="Blocked",
            datasource_name="Sales Data",
            field_mappings={},
            parameters={},
        )
```

- [ ] **Step 2: Run rendering tests and verify they fail**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_tableau_resources_render.py -v
```

Expected: FAIL because `render_bookmark` does not exist.

- [ ] **Step 3: Implement assignment and contract validation**

Implement `ResourceError(ValueError)` and:

```python
def parse_assignments(values: list[str]) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ResourceError(f"Expected NAME=VALUE, got: {value}")
        name, mapped = value.split("=", 1)
        if not name.strip() or not mapped.strip() or name in assignments:
            raise ResourceError(f"Invalid or duplicate assignment: {value}")
        assignments[name.strip()] = mapped.strip()
    return assignments
```

Validate dates with `datetime.date.fromisoformat`, enums against
`allowed`, required parameters exactly once, and reject assignments not
declared by the resource contract.

- [ ] **Step 4: Implement bounded bookmark conversion**

`render_bookmark` must:

1. Reject any resource whose tier is not `executable`.
2. Read and hash the `.tbm`; reject drift from the catalog hash.
3. Extract exactly one `<table>` and one `<window>` using parser-confirmed
   offsets; hoist root-level `<cards>` into the window when needed.
4. Remove `<highlight>` blocks because they are transient donor state.
5. Replace donor datasource names in attributes and qualified references.
6. Replace source field names only in bracketed base fields and
   `derivation:field:role` segments, longest field name first.
7. Replace validated explicit parameters.
8. Wrap the table in a `<worksheet>` whose escaped `name` is the supplied
   `worksheet_name`.
9. Set the window class and name to the output worksheet name.
10. Replace fragment `simple-id` values with UUID5 values derived from
    `resource_id + worksheet_name + fragment_kind`.
11. Reject output containing donor-qualified references, any source field
    whose mapping target differs, text matching `\{\{[^}]+\}\}`, or
    `federated.XXXX`. Identity field mappings remain valid.
12. Parse both fragments inside temporary XML wrapper roots before returning.

Use Tableau bracket escaping (`]` becomes `]]`) and XML-escape attribute
values. Do not serialize the source bookmark through `ElementTree`.

- [ ] **Step 5: Run rendering tests**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_tableau_resources_render.py -v
```

Expected: PASS, including golden output for both Pulse templates and one
portable non-Pulse bar template.

### Task 5: Instantiate and inject workbook files safely

**Files:**
- Modify: `plugins/tableau/scripts/tableau_resources.py`
- Create: `plugins/tableau/tests/fixtures/existing-workbook.twb`
- Create: `plugins/tableau/tests/fixtures/target-datasource.xml`
- Create: `plugins/tableau/tests/test_tableau_resources_workbook.py`

**Interfaces:**
- Produces `inspect_datasources(twb_text: str) -> dict[str, set[str]]`.
- Produces `inject_fragments(twb_text, worksheet, window) -> str`.
- Produces `instantiate_resource` and `inject_resource`, each returning the
  complete transformed workbook text before atomic write.
- Produces `atomic_write(path: Path, content: str, overwrite: bool) -> None`.
- CLI commands: `instantiate` and `inject`.

- [ ] **Step 1: Write failing workbook transformation tests**

```python
def test_inject_preserves_unrelated_bytes(self) -> None:
    original = (FIXTURES / "existing-workbook.twb").read_text()
    marker = "<!-- preserve-this-byte-for-byte -->"
    output = inject_resource(
        input_path=FIXTURES / "existing-workbook.twb",
        output_path=self.tmp / "output.twb",
        resource_id="insights__line_chart",
        worksheet_name="ARR Trend",
        datasource_name="Sales Data",
        field_mappings={"ARR": "Revenue", "Close Date": "Transaction Date"},
        parameters={},
    )
    self.assertIn(marker, output)
    self.assertEqual(
        original[: original.index("</worksheets>")],
        output[: output.index("<worksheet name='ARR Trend'>")],
    )

def test_instantiate_inserts_one_datasource_and_sheet(self) -> None:
    output = instantiate_resource(
        datasource_definition_path=FIXTURES / "target-datasource.xml",
        output_path=self.tmp / "starter-output.twb",
        resource_id="insights__bar_chart",
        worksheet_name="ARR by Offering",
        field_mappings={
            "ARR": "Revenue",
            "Close Date": "Transaction Date",
            "Product": "Offering",
        },
        parameters={
            "DATE_MIN": "2026-01-01",
            "DATE_MAX": "2026-06-30",
            "DIRECTION": "DESC",
        },
    )
    root = ET.fromstring(output)
    self.assertEqual(len(root.find("datasources")), 1)
    self.assertEqual(len(root.find("worksheets")), 1)
    self.assertEqual(len(root.find("windows")), 1)

def test_existing_output_requires_overwrite(self) -> None:
    output = self.tmp / "existing.twb"
    output.write_text("do not replace")
    with self.assertRaisesRegex(ResourceError, "--overwrite"):
        atomic_write(output, "new", overwrite=False)
    self.assertEqual(output.read_text(), "do not replace")
```

- [ ] **Step 2: Run workbook tests and verify they fail**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_tableau_resources_workbook.py -v
```

Expected: FAIL because workbook transformation functions do not exist.

- [ ] **Step 3: Implement datasource inspection and validation**

`inspect_datasources` parses global workbook `<datasources>` and returns each
datasource internal name with column names from descendant `<column>` nodes.
Before rendering, verify the chosen datasource exists and every target field
mapping exists in it.

For `instantiate`, require `--datasource-definition` to parse as exactly one
`<datasource>` element with a nonempty `name`; reject documents with a
`<workbook>` root or multiple datasource elements.

- [ ] **Step 4: Implement bounded insertion**

`inject_fragments` verifies exactly one closing `</worksheets>` and one closing
`</windows>`, rejects duplicate worksheet/window names, inserts the worksheet
and window immediately before those closing tags, and leaves all preceding and
following bytes unchanged.

For `instantiate`, insert the caller-supplied datasource immediately before
the starter's `</datasources>`, then use the same fragment injection path.

- [ ] **Step 5: Implement atomic output and CLI commands**

Write output to `tempfile.NamedTemporaryFile` in the destination directory,
flush and `os.fsync`, then use `os.replace`. Remove the temporary file on every
exception. Refuse an existing destination unless `--overwrite` is present.
Require input and output paths to differ unless `--overwrite` is present.

CLI examples:

```bash
python3 plugins/tableau/scripts/tableau_resources.py inject \
  insights__line_chart \
  --input workbook.twb \
  --output workbook-with-trend.twb \
  --worksheet-name "ARR Trend" \
  --datasource "Sales Data" \
  --map "ARR=Revenue" \
  --map "Close Date=Transaction Date"

python3 plugins/tableau/scripts/tableau_resources.py instantiate \
  insights__bar_chart \
  --datasource-definition datasource.xml \
  --output starter-bar.twb \
  --worksheet-name "ARR by Offering" \
  --map "ARR=Revenue" \
  --map "Close Date=Transaction Date" \
  --map "Product=Offering" \
  --param "DATE_MIN=2026-01-01" \
  --param "DATE_MAX=2026-06-30" \
  --param "DIRECTION=DESC"
```

- [ ] **Step 6: Run workbook tests**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_tableau_resources_workbook.py -v
```

Expected: PASS with input-preservation, starter, and overwrite tests.

### Task 6: Add fail-closed workbook validation

**Files:**
- Modify: `plugins/tableau/scripts/tableau_resources.py`
- Create: `plugins/tableau/tests/test_tableau_resources_validation.py`

**Interfaces:**
- Produces `validate_workbook_text(text: str) -> list[str]`.
- Produces `validate_workbook(path: Path) -> list[str]`.
- CLI command `validate --input <path>` exits 0 for no errors and 1 with JSON errors otherwise.

- [ ] **Step 1: Write failing validation and failure-atomicity tests**

```python
def test_validate_rejects_unresolved_tokens(self) -> None:
    path = self.tmp / "tokens.twb"
    path.write_text("<workbook><datasources/><worksheets>{{field_base_1}}</worksheets><windows/></workbook>")
    self.assertIn("unresolved-template-token", validate_workbook(path))

def test_validate_rejects_missing_datasource_reference(self) -> None:
    path = self.tmp / "missing-ds.twb"
    path.write_text(
        "<workbook><datasources/><worksheets><worksheet name='X'><table>"
        "<rows>[Missing].[none:Category:nk]</rows></table></worksheet>"
        "</worksheets><windows><window class='worksheet' name='X'/></windows></workbook>"
    )
    self.assertIn("unknown-datasource-reference: Missing", validate_workbook(path))

def test_failed_injection_creates_no_partial_output(self) -> None:
    output = self.tmp / "partial.twb"
    with self.assertRaises(ResourceError):
        inject_resource(
            input_path=FIXTURES / "existing-workbook.twb",
            output_path=output,
            resource_id="insights__bar_chart",
            worksheet_name="Broken",
            datasource_name="Sales Data",
            field_mappings={},
            parameters={},
        )
    self.assertFalse(output.exists())
```

- [ ] **Step 2: Run validation tests and verify they fail**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_tableau_resources_validation.py -v
```

Expected: FAIL because `validate_workbook` does not exist.

- [ ] **Step 3: Implement ordered validation rules**

Return stable, deduplicated error strings in this order:

1. `malformed-xml`
2. `not-tableau-workbook`
3. `missing-datasources-container`
4. `missing-worksheets-container`
5. `missing-windows-container`
6. `unresolved-template-token`
7. `unresolved-federated-placeholder`
8. `duplicate-worksheet-name: <name>`
9. `duplicate-window-name: <name>`
10. `worksheet-window-name-mismatch: <name>`
11. `unknown-datasource-reference: <name>`
12. `unknown-field-reference: <datasource>.<field>`

Datasource and field validation uses definitions from global datasources and
worksheet-local datasource dependencies. Ignore Tableau pseudo-fields that
start with `:` and generated Latitude/Longitude fields.

- [ ] **Step 4: Make instantiate and inject validate before atomic write**

If `validate_workbook_text(output)` returns errors, raise:

```text
Generated workbook failed validation: <comma-separated errors>
```

Do not create or replace the destination.

- [ ] **Step 5: Run all CLI tests**

Run:

```bash
python3 -m unittest discover -s plugins/tableau/tests -p "test_*.py" -v
```

Expected: all tests pass with zero failures.

### Task 7: Expose resources through Codex skills

**REQUIRED SUB-SKILL:** Use superpowers:writing-skills for the two new skills
and the validation-skill edit.

**Files:**
- Create: `plugins/tableau/skills/tableau-workbook-authoring/SKILL.md`
- Create: `plugins/tableau/skills/tableau-workbook-authoring/references/resource-guide.md`
- Create: `plugins/tableau/skills/tableau-pulse-insights/SKILL.md`
- Modify: `plugins/tableau/skills/validate-workbook-package/SKILL.md`
- Modify: `plugins/tableau/.codex-plugin/plugin.json`
- Create: `plugins/tableau/README.md`
- Modify: `README.md`
- Test: `plugins/tableau/tests/test_skill_resource_contract.py`

**Interfaces:**
- Main skill invokes CLI by path relative to its own directory:
  `../../scripts/tableau_resources.py`.
- Pulse skill uses catalog family `pulse-insights`.
- Validation skill remains the pre-publish gate.

- [ ] **Step 1: Write the failing skill contract test**

```python
class SkillResourceContractTest(unittest.TestCase):
    def test_skill_entry_points_and_cli_references_exist(self) -> None:
        for skill_name in ("tableau-workbook-authoring", "tableau-pulse-insights"):
            path = PLUGIN / "skills" / skill_name / "SKILL.md"
            text = path.read_text()
            self.assertIn(f"name: {skill_name}", text)
            self.assertIn("../../scripts/tableau_resources.py", text)
        authoring = (
            PLUGIN / "skills/tableau-workbook-authoring/SKILL.md"
        ).read_text()
        for command in ("list", "inspect", "instantiate", "inject", "validate"):
            self.assertIn(f" {command}", authoring)

    def test_plugin_prompts_surface_template_authoring(self) -> None:
        plugin = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        prompts = plugin["interface"]["defaultPrompt"]
        self.assertIn("Build a Tableau workbook from a template", prompts)
```

- [ ] **Step 2: Run the skill contract test and verify it fails**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_skill_resource_contract.py -v
```

Expected: FAIL because the two entry-point skills do not exist.

- [ ] **Step 3: Author the workbook skill**

Frontmatter:

```yaml
---
name: tableau-workbook-authoring
description: Use when creating, modifying, templating, validating, or publishing Tableau .twb workbooks, including selecting visualization samples and mapping fields into Tableau bookmark templates.
---
```

The workflow must require:

1. Inspect an existing workbook or prepare a datasource definition.
2. Run `list` before choosing a chart.
3. Run `inspect` before mapping fields.
4. Use `inject` for existing workbooks and `instantiate` for the starter.
5. Treat reference-only resources as inspiration, never executable input.
6. Run local `validate`.
7. Run `validate-workbook-package`.
8. Publish only with the returned validation receipt.

Put detailed CLI examples, mapping syntax, and failure recovery in
`references/resource-guide.md`, not in the always-loaded skill body.

- [ ] **Step 4: Author the Pulse Insights skill**

Frontmatter:

```yaml
---
name: tableau-pulse-insights
description: Use when building Tableau Pulse Insights bar or line visualizations in a .twb workbook, including ARR trends, ranked products, date ranges, and field mapping.
---
```

The skill must begin discovery with:

```bash
python3 ../../scripts/tableau_resources.py list \
  --family pulse-insights \
  --tier executable
```

It must delegate transformation and validation rules to the workbook
authoring skill and shared CLI rather than duplicating them.

- [ ] **Step 5: Connect validation and plugin install-surface copy**

Add a short prerequisite to `validate-workbook-package` explaining that local
resource validation occurs before packaging.

Update plugin prompts to:

```json
[
  "Build a Tableau workbook from a template",
  "Create a Tableau Pulse Insights visualization",
  "Validate and publish this Tableau workbook"
]
```

Update plugin and root READMEs with resource tiers, CLI location, and the
download-or-starter → transform → validate → publish flow.

- [ ] **Step 6: Run skill and full tests**

Run:

```bash
python3 -m unittest discover -s plugins/tableau/tests -p "test_*.py" -v
python3 plugins/tableau/scripts/generate_resource_catalog.py \
  --plugin-root plugins/tableau \
  --check
python3 plugins/tableau/scripts/tableau_resources.py list \
  --family pulse-insights \
  --tier executable
```

Expected:

- All unit tests pass.
- Catalog check exits 0 without rewriting files.
- Discovery returns exactly `insights__bar_chart` and
  `insights__line_chart`.

### Task 8: Run end-to-end golden workflows

**Files:**
- Create: `plugins/tableau/tests/test_end_to_end_resources.py`
- Create: `plugins/tableau/tests/golden/insights-bar.twb`
- Create: `plugins/tableau/tests/golden/insights-line-injected.twb`

**Interfaces:**
- Verifies the public CLI only; does not import private implementation helpers.

- [ ] **Step 1: Write end-to-end subprocess tests**

The tests execute:

1. `instantiate insights__bar_chart` against `target-datasource.xml`.
2. `validate` the generated workbook.
3. `inject insights__line_chart` into `existing-workbook.twb`.
4. `validate` the injected workbook.
5. Compare normalized line endings to checked-in golden files.
6. Assert input fixture hashes are unchanged.

- [ ] **Step 2: Run end-to-end tests and verify they fail before golden files**

Run:

```bash
python3 -m unittest plugins/tableau/tests/test_end_to_end_resources.py -v
```

Expected: FAIL because golden files do not exist.

- [ ] **Step 3: Generate and review golden files**

Generate golden files only through the public CLI commands from Task 5.
Manually verify:

- Correct datasource and target field names.
- No donor names or unresolved tokens.
- One worksheet and matching window per generated resource.
- Existing workbook marker and unrelated bytes remain unchanged.

- [ ] **Step 4: Run final verification**

Run:

```bash
python3 -m unittest discover -s plugins/tableau/tests -p "test_*.py" -v
python3 plugins/tableau/scripts/generate_resource_catalog.py \
  --plugin-root plugins/tableau \
  --check
python3 plugins/tableau/scripts/tableau_resources.py validate \
  --input plugins/tableau/tests/golden/insights-bar.twb
python3 plugins/tableau/scripts/tableau_resources.py validate \
  --input plugins/tableau/tests/golden/insights-line-injected.twb
git diff --check
```

Expected: every command exits 0, the test suite reports zero failures, both
golden workbooks validate, and `git diff --check` reports no whitespace errors.


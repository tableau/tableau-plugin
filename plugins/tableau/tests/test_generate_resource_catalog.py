import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))
from generate_resource_catalog import (
    classify_bookmark,
    extract_bookmark,
    generate_catalog,
    main,
    sha256,
)


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
            item["parameters"],
            [
                {"name": "DATE_MAX", "type": "date", "required": True},
                {"name": "DATE_MIN", "type": "date", "required": True},
                {
                    "name": "DIRECTION",
                    "type": "enum",
                    "required": True,
                    "allowed": ["ASC", "DESC"],
                },
            ],
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


# ---------------------------------------------------------------------------
# Fix Round 1 fixtures
# ---------------------------------------------------------------------------

_MINIMAL_EXECUTABLE_BOOKMARK = """<?xml version='1.0' encoding='utf-8' ?>
<bookmark version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user' source-platform='mac'>
<window class='worksheet' name='sample'>
  <simple-id uuid='{00000000-0000-0000-0000-000000000001}' />
</window>
<table>
    <view>
      <datasources>
        <datasource name='Sample DS' />
      </datasources>
      <datasource-dependencies datasource='Sample DS'>
        <column datatype='string' name='[Category]' role='dimension' type='nominal' />
        <column datatype='real' name='[Sales]' role='measure' type='quantitative' />
        <column-instance column='[Category]' derivation='None' name='[none:Category:nk]' pivot='key' type='nominal' />
        <column-instance column='[Sales]' derivation='Sum' name='[sum:Sales:qk]' pivot='key' type='quantitative' />
      </datasource-dependencies>
    </view>
    <panes>
      <pane>
        <encodings>
          <color column='[Sample DS].[none:Category:nk]' />
        </encodings>
      </pane>
    </panes>
    <rows>[Sample DS].[none:Category:nk]</rows>
    <cols>[Sample DS].[sum:Sales:qk]</cols>
</table>
</bookmark>
"""

# Finding 3: two column-instances of the same base field, with different
# derivations, both placed on the "marks" shelf (color and size encodings).
_DERIVATION_COLLISION_BOOKMARK = """<?xml version='1.0' encoding='utf-8' ?>
<bookmark version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user' source-platform='mac'>
<window class='worksheet' name='sample'>
  <simple-id uuid='{00000000-0000-0000-0000-000000000002}' />
</window>
<table>
    <view>
      <datasources>
        <datasource name='Sample DS' />
      </datasources>
      <datasource-dependencies datasource='Sample DS'>
        <column datatype='real' name='[Sales]' role='measure' type='quantitative' />
        <column-instance column='[Sales]' derivation='Sum' name='[sum:Sales:qk]' pivot='key' type='quantitative' />
        <column-instance column='[Sales]' derivation='Avg' name='[avg:Sales:qk]' pivot='key' type='quantitative' />
      </datasource-dependencies>
    </view>
    <panes>
      <pane>
        <encodings>
          <color column='[Sample DS].[sum:Sales:qk]' />
          <size column='[Sample DS].[avg:Sales:qk]' />
        </encodings>
      </pane>
    </panes>
</table>
</bookmark>
"""

# Finding 4a: a "Parameters" pseudo-datasource alongside one real donor. The
# parameter column deliberately has no <calculation> child so the only
# blocker under test (multiple-datasources) is isolated.
_PARAMETERS_PSEUDO_DATASOURCE_BOOKMARK = """<?xml version='1.0' encoding='utf-8' ?>
<bookmark version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user' source-platform='mac'>
<window class='worksheet' name='sample'>
  <simple-id uuid='{00000000-0000-0000-0000-000000000003}' />
</window>
<table>
    <view>
      <datasources>
        <datasource name='Sample DS' />
        <datasource name='Parameters' />
      </datasources>
      <datasource-dependencies datasource='Parameters'>
        <column caption='Threshold' datatype='real' name='[Parameter 1]' param-domain-type='any' role='measure' type='quantitative' value='0.5' />
      </datasource-dependencies>
      <datasource-dependencies datasource='Sample DS'>
        <column datatype='string' name='[Category]' role='dimension' type='nominal' />
        <column-instance column='[Category]' derivation='None' name='[none:Category:nk]' pivot='key' type='nominal' />
      </datasource-dependencies>
      <reference-line axis-column='[Sample DS].[none:Category:nk]' value-column='[Parameters].[Parameter 1]' />
    </view>
    <panes>
      <pane />
    </panes>
    <rows>[Sample DS].[none:Category:nk]</rows>
</table>
</bookmark>
"""

# Finding 4b: an inline-relational-style hidden internal-object-id namespace
# column-instance, as seen in real multi-table inline datasources.
_INTERNAL_OBJECT_ID_BOOKMARK = """<?xml version='1.0' encoding='utf-8' ?>
<bookmark version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user' source-platform='mac'>
<window class='worksheet' name='sample'>
  <simple-id uuid='{00000000-0000-0000-0000-000000000004}' />
</window>
<table>
    <view>
      <datasources>
        <datasource name='Sample DS' />
      </datasources>
      <datasource-dependencies datasource='Sample DS'>
        <column datatype='string' name='[Category]' role='dimension' type='nominal' />
        <column-instance column='[Category]' derivation='None' name='[none:Category:nk]' pivot='key' type='nominal' />
        <column caption='Orders' datatype='table' hidden='true' name='[__tableau_internal_object_id__].[Orders_ABC]' role='measure' type='quantitative' />
        <column-instance column='[__tableau_internal_object_id__].[Orders_ABC]' derivation='Count' name='[__tableau_internal_object_id__].[cnt:Orders_ABC:qk]' pivot='key' type='quantitative' />
      </datasource-dependencies>
    </view>
    <panes>
      <pane />
    </panes>
    <rows>[Sample DS].[none:Category:nk]</rows>
</table>
</bookmark>
"""

# Finding 5: a bookmark with one explicit {{THRESHOLD}} parameter token, used
# to exercise override-parameter-mismatch rejection end to end via main().
_PARAMETER_TOKEN_BOOKMARK = """<?xml version='1.0' encoding='utf-8' ?>
<bookmark version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user' source-platform='mac'>
<window class='worksheet' name='sample'>
  <simple-id uuid='{00000000-0000-0000-0000-000000000005}' />
</window>
<table>
    <view>
      <datasources>
        <datasource name='Sample DS' />
      </datasources>
      <datasource-dependencies datasource='Sample DS'>
        <column datatype='real' name='[Sales]' role='measure' type='quantitative' />
        <column-instance column='[Sales]' derivation='Sum' name='[sum:Sales:qk]' pivot='key' type='quantitative' />
      </datasource-dependencies>
      <filter class='quantitative' column='[Sample DS].[sum:Sales:qk]'>
        <min>#{{THRESHOLD}}#</min>
      </filter>
    </view>
    <panes>
      <pane />
    </panes>
    <rows>[Sample DS].[sum:Sales:qk]</rows>
</table>
</bookmark>
"""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_plugin_root(root: Path) -> None:
    """Create the minimal resources/ layout generate_resource_catalog.py needs."""
    for tier in ("unclassified", "executable", "reference"):
        (root / "resources" / "templates" / tier).mkdir(parents=True, exist_ok=True)


class HiddenFileHandlingTest(unittest.TestCase):
    """Finding 1: dotfiles (and cache dirs) must never become catalog entries."""

    def test_dot_files_are_skipped_in_plain_resource_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_plugin_root(root)
            examples_dir = root / "resources" / "examples"
            _write(examples_dir / ".DS_Store", "junk")
            _write(examples_dir / "real-example.json", "{}")
            pycache = examples_dir / "__pycache__"
            pycache.mkdir(parents=True, exist_ok=True)
            _write(pycache / "mod.cpython-312.pyc", "junk")

            catalog = generate_catalog(root)
            ids = [item["id"] for item in catalog["resources"]]

            self.assertIn("real-example", ids)
            self.assertNotIn(".DS_Store", ids)
            for item in catalog["resources"]:
                self.assertFalse(item["id"].startswith("."))
                self.assertNotIn("__pycache__", item["path"])
                self.assertNotIn(".DS_Store", item["path"])
            # Only the one legitimate example resource should be catalogued.
            self.assertEqual(len(catalog["resources"]), 1)

    def test_hidden_template_files_are_not_globbed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_plugin_root(root)
            _write(
                root / "resources" / "templates" / "unclassified" / ".hidden.tbm",
                _MINIMAL_EXECUTABLE_BOOKMARK,
            )

            catalog = generate_catalog(root)

            self.assertEqual(catalog["resources"], [])


class ResourceIdUniquenessTest(unittest.TestCase):
    """Finding 2: resource ids must be globally unique across resource kinds."""

    def test_duplicate_ids_across_resource_kinds_raise_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_plugin_root(root)
            _write(
                root / "resources" / "templates" / "unclassified" / "sample.tbm",
                _MINIMAL_EXECUTABLE_BOOKMARK,
            )
            _write(root / "resources" / "examples" / "sample.json", "{}")

            with self.assertRaises(ValueError) as ctx:
                generate_catalog(root)
            self.assertIn("sample", str(ctx.exception))

    def test_unique_ids_across_resource_kinds_do_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_plugin_root(root)
            _write(
                root / "resources" / "templates" / "unclassified" / "sample.tbm",
                _MINIMAL_EXECUTABLE_BOOKMARK,
            )
            _write(root / "resources" / "examples" / "other-example.json", "{}")

            catalog = generate_catalog(root)

            self.assertEqual(len(catalog["resources"]), 2)


class FieldDerivationDedupTest(unittest.TestCase):
    """Finding 3: distinct derivations of the same field/shelf must both survive."""

    def test_distinct_derivations_on_same_shelf_are_both_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.tbm"
            path.write_text(_DERIVATION_COLLISION_BOOKMARK, encoding="utf-8")

            metadata = extract_bookmark(path)
            marks_fields = [
                field
                for field in metadata["fields"]
                if field["shelf"] == "marks" and field["sourceField"] == "Sales"
            ]

            self.assertEqual(len(marks_fields), 2)
            self.assertEqual(
                sorted(field["derivation"] for field in marks_fields),
                ["Avg", "Sum"],
            )


class PseudoDatasourceExclusionTest(unittest.TestCase):
    """Finding 4: 'Parameters' and internal-object-id namespaces are not donors."""

    def test_parameters_pseudo_datasource_is_excluded_but_field_detail_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.tbm"
            path.write_text(_PARAMETERS_PSEUDO_DATASOURCE_BOOKMARK, encoding="utf-8")

            metadata = extract_bookmark(path)

            self.assertNotIn("Parameters", metadata["datasources"])
            self.assertEqual(metadata["datasources"], ["Sample DS"])
            self.assertNotIn("multiple-datasources", metadata["blockers"])

            tier, reasons = classify_bookmark(metadata)
            self.assertEqual(tier, "executable")
            self.assertEqual(reasons, [])

            # The real donor is retained; the pseudo-datasource is excluded
            # from donor inference but its field detail is still captured.
            parameter_fields = [
                field for field in metadata["fields"] if field["datasource"] == "Parameters"
            ]
            self.assertEqual(len(parameter_fields), 1)
            self.assertEqual(parameter_fields[0]["sourceField"], "Parameter 1")

    def test_internal_object_id_namespace_is_excluded_from_donors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.tbm"
            path.write_text(_INTERNAL_OBJECT_ID_BOOKMARK, encoding="utf-8")

            metadata = extract_bookmark(path)

            self.assertNotIn("__tableau_internal_object_id__", metadata["datasources"])
            self.assertEqual(metadata["datasources"], ["Sample DS"])
            self.assertNotIn("multiple-datasources", metadata["blockers"])

    def test_pareto_chart_excludes_parameters_from_real_corpus(self) -> None:
        # Integration check against the real corpus: pareto-chart.tbm uses a
        # 'Parameters' datasource for a reference-line threshold. It must
        # stay reference-tier (it has a genuine calculated field), but no
        # longer via a bogus multiple-datasources reason.
        catalog = generate_catalog(PLUGIN)
        item = next(r for r in catalog["resources"] if r["id"] == "pareto-chart")

        self.assertNotIn("Parameters", item["datasources"])
        self.assertNotIn("multiple-datasources", item["classificationReasons"])
        self.assertEqual(item["tier"], "reference")
        self.assertIn("external-calculation-dependency", item["classificationReasons"])


class CliWriteAndCheckTest(unittest.TestCase):
    """Finding 5: automated direct-main coverage for --write/--check behavior."""

    def _make_root_with_sample(self, tmp: str) -> Path:
        root = Path(tmp)
        _make_plugin_root(root)
        _write(
            root / "resources" / "templates" / "unclassified" / "sample.tbm",
            _MINIMAL_EXECUTABLE_BOOKMARK,
        )
        return root

    def test_write_creates_catalog_and_moves_template_preserving_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root_with_sample(tmp)
            unclassified_path = root / "resources/templates/unclassified/sample.tbm"
            original_bytes = unclassified_path.read_bytes()
            original_digest = sha256(unclassified_path)

            exit_code = main(["--plugin-root", str(root), "--write"])

            self.assertEqual(exit_code, 0)
            moved = root / "resources/templates/executable/sample.tbm"
            self.assertTrue(moved.exists())
            self.assertFalse(unclassified_path.exists())
            self.assertEqual(moved.read_bytes(), original_bytes)
            self.assertEqual(sha256(moved), original_digest)

            catalog_path = root / "resources/catalog.json"
            self.assertTrue(catalog_path.exists())
            catalog = json.loads(catalog_path.read_text())
            item = next(r for r in catalog["resources"] if r["id"] == "sample")
            self.assertEqual(item["tier"], "executable")
            self.assertEqual(item["path"], "./templates/executable/sample.tbm")

    def test_check_passes_and_writes_nothing_on_clean_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root_with_sample(tmp)
            self.assertEqual(main(["--plugin-root", str(root), "--write"]), 0)

            catalog_path = root / "resources/catalog.json"
            template_path = root / "resources/templates/executable/sample.tbm"
            before_catalog_mtime = catalog_path.stat().st_mtime_ns
            before_catalog_bytes = catalog_path.read_bytes()
            before_template_mtime = template_path.stat().st_mtime_ns
            before_template_bytes = template_path.read_bytes()

            exit_code = main(["--plugin-root", str(root), "--check"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(catalog_path.stat().st_mtime_ns, before_catalog_mtime)
            self.assertEqual(catalog_path.read_bytes(), before_catalog_bytes)
            self.assertEqual(template_path.stat().st_mtime_ns, before_template_mtime)
            self.assertEqual(template_path.read_bytes(), before_template_bytes)

    def test_check_fails_on_stale_catalog_content_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root_with_sample(tmp)
            self.assertEqual(main(["--plugin-root", str(root), "--write"]), 0)

            catalog_path = root / "resources/catalog.json"
            stale = catalog_path.read_text().replace('"schemaVersion": 1', '"schemaVersion": 2')
            catalog_path.write_text(stale, encoding="utf-8")
            before_mtime = catalog_path.stat().st_mtime_ns

            exit_code = main(["--plugin-root", str(root), "--check"])

            self.assertEqual(exit_code, 1)
            # --check must not repair, rewrite, or touch the stale file.
            self.assertEqual(catalog_path.read_text(), stale)
            self.assertEqual(catalog_path.stat().st_mtime_ns, before_mtime)

    def test_check_fails_on_physical_tier_drift_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root_with_sample(tmp)
            self.assertEqual(main(["--plugin-root", str(root), "--write"]), 0)

            catalog_path = root / "resources/catalog.json"
            before_catalog_bytes = catalog_path.read_bytes()

            # Manually relocate the template away from its catalogued tier,
            # simulating drift between catalog.json and the filesystem.
            executable_path = root / "resources/templates/executable/sample.tbm"
            drifted_path = root / "resources/templates/reference/sample.tbm"
            shutil.move(str(executable_path), str(drifted_path))
            drifted_bytes = drifted_path.read_bytes()

            exit_code = main(["--plugin-root", str(root), "--check"])

            self.assertEqual(exit_code, 1)
            # --check must not move the file back or touch the catalog.
            self.assertFalse(executable_path.exists())
            self.assertTrue(drifted_path.exists())
            self.assertEqual(drifted_path.read_bytes(), drifted_bytes)
            self.assertEqual(catalog_path.read_bytes(), before_catalog_bytes)

    def test_write_rejects_mismatched_override_parameters_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_plugin_root(root)
            template_path = root / "resources/templates/unclassified/param-sample.tbm"
            _write(template_path, _PARAMETER_TOKEN_BOOKMARK)
            _write(
                root / "resources/catalog-overrides.json",
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "resources": {
                            "param-sample": {
                                "parameters": {
                                    "WRONG_NAME": {"type": "date", "required": True}
                                },
                            }
                        },
                    }
                ),
            )

            exit_code = main(["--plugin-root", str(root), "--write"])

            self.assertEqual(exit_code, 1)
            self.assertFalse((root / "resources/catalog.json").exists())
            # Nothing should have moved since generation failed up front.
            self.assertTrue(template_path.exists())

    def test_check_rejects_mismatched_override_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_plugin_root(root)
            _write(
                root / "resources/templates/unclassified/param-sample.tbm",
                _PARAMETER_TOKEN_BOOKMARK,
            )
            _write(
                root / "resources/catalog-overrides.json",
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "resources": {
                            "param-sample": {
                                "parameters": {
                                    "WRONG_NAME": {"type": "date", "required": True}
                                },
                            }
                        },
                    }
                ),
            )

            exit_code = main(["--plugin-root", str(root), "--check"])

            self.assertEqual(exit_code, 1)
            self.assertFalse((root / "resources/catalog.json").exists())


class TypedParameterContractTest(unittest.TestCase):
    """Fix round 1, finding 2: every token needs a reviewed typed contract.

    The contract is copied into the generated catalog, so a token that reaches
    the catalog untyped would let runtime validation fall open later. Catch it
    at generation instead.
    """

    def generate_with_override(self, override: object | None) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_plugin_root(root)
            _write(
                root / "resources/templates/unclassified/param-sample.tbm",
                _PARAMETER_TOKEN_BOOKMARK,
            )
            if override is not None:
                _write(
                    root / "resources/catalog-overrides.json",
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "resources": {"param-sample": {"parameters": override}},
                        }
                    ),
                )
            return generate_catalog(root)

    def test_token_without_any_override_contract_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not match inferred parameters"):
            self.generate_with_override(None)

    def test_contract_without_a_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must declare a type"):
            self.generate_with_override({"THRESHOLD": {"required": True}})

    def test_contract_with_an_unknown_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must declare a type"):
            self.generate_with_override({"THRESHOLD": {"type": "money"}})

    def test_enum_contract_without_allowed_values_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty 'allowed' list"):
            self.generate_with_override({"THRESHOLD": {"type": "enum"}})

    def test_reviewed_contract_is_copied_into_the_catalog(self) -> None:
        catalog = self.generate_with_override(
            {"THRESHOLD": {"type": "number", "required": False}}
        )
        item = next(
            r for r in catalog["resources"] if r["id"] == "param-sample"
        )
        self.assertEqual(
            item["parameters"],
            [{"name": "THRESHOLD", "type": "number", "required": False}],
        )


if __name__ == "__main__":
    unittest.main()

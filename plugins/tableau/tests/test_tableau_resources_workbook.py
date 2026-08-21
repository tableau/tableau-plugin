"""Workbook instantiation and injection tests.

Covers datasource inspection, target-field validation, bounded fragment
insertion, duplicate-name rejection, atomic output, and the ``instantiate``
and ``inject`` CLI commands.

``existing-workbook.twb`` mirrors a real Tableau workbook: its datasource
carries the human caption ``Sales Data`` and the internal name
``federated.0fixture1sales2data``. The CLI addresses datasources by internal
name, so every call here passes the federated name rather than the caption.
"""

import difflib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

PLUGIN = Path(__file__).resolve().parents[1]
FIXTURES = PLUGIN / "tests/fixtures"
CLI = PLUGIN / "scripts/tableau_resources.py"
STARTER = PLUGIN / "resources/starters/minimal-workbook.twb"
sys.path.insert(0, str(PLUGIN / "scripts"))

from tableau_resources import (  # noqa: E402
    ResourceError,
    atomic_write,
    inject_fragments,
    inject_resource,
    inspect_datasources,
    instantiate_resource,
)

FIXTURE_DATASOURCE = "federated.0fixture1sales2data"
LINE_MAPPINGS = {"ARR": "Revenue", "Close Date": "Transaction Date"}
BAR_MAPPINGS = {
    "ARR": "Revenue",
    "Close Date": "Transaction Date",
    "Product": "Offering",
}
BAR_PARAMETERS = {
    "DATE_MIN": "2026-01-01",
    "DATE_MAX": "2026-06-30",
    "DIRECTION": "DESC",
}
PAIRED_MAPPINGS = {
    "Customer Name": "Offering",
    "Order Date": "Transaction Date",
    "Profit": "Revenue",
}
REFERENCE_ONLY_ID = (
    "magnitude__horizontal-bar__compare-discrete-categories-from-zero"
)


class WorkbookTransformTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def inject_line_chart(self, **overrides: object) -> str:
        arguments: dict[str, object] = {
            "input_path": FIXTURES / "existing-workbook.twb",
            "output_path": self.tmp / "output.twb",
            "resource_id": "insights__line_chart",
            "worksheet_name": "ARR Trend",
            "datasource_name": FIXTURE_DATASOURCE,
            "field_mappings": dict(LINE_MAPPINGS),
            "parameters": {},
        }
        arguments.update(overrides)
        return inject_resource(**arguments)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    # --- required behaviors -------------------------------------------------

    def test_inject_preserves_unrelated_bytes(self) -> None:
        original = (FIXTURES / "existing-workbook.twb").read_text()
        marker = "<!-- preserve-this-byte-for-byte -->"
        output = inject_resource(
            input_path=FIXTURES / "existing-workbook.twb",
            output_path=self.tmp / "output.twb",
            resource_id="insights__line_chart",
            worksheet_name="ARR Trend",
            datasource_name=FIXTURE_DATASOURCE,
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

    # --- datasource inspection and validation -------------------------------

    def test_inspect_datasources_reports_only_global_datasource_columns(self) -> None:
        text = (FIXTURES / "existing-workbook.twb").read_text()
        self.assertEqual(
            inspect_datasources(text),
            {FIXTURE_DATASOURCE: {"Revenue", "Transaction Date", "Offering"}},
        )

    def test_inspect_datasources_keys_on_internal_name_not_caption(self) -> None:
        text = (FIXTURES / "existing-workbook.twb").read_text()
        self.assertIn("caption='Sales Data'", text)
        self.assertNotIn("Sales Data", inspect_datasources(text))

    def test_inject_accepts_a_federated_target_datasource(self) -> None:
        output = self.inject_line_chart()
        self.assertIn(f"[{FIXTURE_DATASOURCE}].[sum:Revenue:qk]", output)
        self.assertIn(f"datasource='{FIXTURE_DATASOURCE}'", output)
        self.assertNotIn("Sample - Superstore", output)

    def test_inspect_datasources_rejects_a_non_workbook_document(self) -> None:
        with self.assertRaisesRegex(ResourceError, "<workbook>"):
            inspect_datasources((FIXTURES / "target-datasource.xml").read_text())

    def test_inject_rejects_a_datasource_the_workbook_does_not_have(self) -> None:
        with self.assertRaisesRegex(ResourceError, "no datasource named Missing DS"):
            self.inject_line_chart(datasource_name="Missing DS")
        self.assertFalse((self.tmp / "output.twb").exists())

    def test_inject_rejects_a_target_field_the_datasource_does_not_have(self) -> None:
        with self.assertRaisesRegex(ResourceError, "Nonexistent Column"):
            self.inject_line_chart(
                field_mappings={
                    "ARR": "Nonexistent Column",
                    "Close Date": "Transaction Date",
                }
            )
        self.assertFalse((self.tmp / "output.twb").exists())

    def test_inject_rejects_a_reference_only_resource(self) -> None:
        with self.assertRaisesRegex(ResourceError, "reference-only"):
            self.inject_line_chart(resource_id=REFERENCE_ONLY_ID)
        self.assertFalse((self.tmp / "output.twb").exists())

    # --- bounded insertion --------------------------------------------------

    def test_inject_places_the_window_beside_the_existing_window(self) -> None:
        output = self.inject_line_chart()
        root = ET.fromstring(output)
        worksheets = [item.get("name") for item in root.findall("worksheets/worksheet")]
        windows = [item.get("name") for item in root.findall("windows/window")]
        self.assertEqual(worksheets, ["Existing Sheet", "ARR Trend"])
        self.assertEqual(windows, ["Existing Sheet", "ARR Trend"])
        self.assertEqual(
            root.findall("windows/window")[1].get("class"), "worksheet"
        )

    def test_inject_preserves_every_byte_after_the_window_container(self) -> None:
        original = (FIXTURES / "existing-workbook.twb").read_text()
        output = self.inject_line_chart()
        tail = original[original.index("</windows>") :]
        self.assertTrue(output.endswith(tail))

    def test_inject_preserves_crlf_bytes_outside_the_fragments(self) -> None:
        source = self.tmp / "crlf-input.twb"
        original = (
            (FIXTURES / "existing-workbook.twb").read_bytes().replace(b"\n", b"\r\n")
        )
        source.write_bytes(original)
        destination = self.tmp / "crlf-output.twb"

        self.inject_line_chart(input_path=source, output_path=destination)

        produced = destination.read_bytes()
        self.assertEqual(source.read_bytes(), original)
        self.assertIn(b"\r\n", produced)
        opcodes = difflib.SequenceMatcher(
            None, original, produced, autojunk=False
        ).get_opcodes()
        self.assertEqual(sorted({tag for tag, *_ in opcodes}), ["equal", "insert"])
        preserved = b"".join(
            produced[start:end]
            for tag, _i1, _i2, start, end in opcodes
            if tag == "equal"
        )
        self.assertEqual(preserved, original)

    def test_inject_rejects_a_duplicate_worksheet_name(self) -> None:
        with self.assertRaisesRegex(ResourceError, "worksheet named Existing Sheet"):
            self.inject_line_chart(worksheet_name="Existing Sheet")

    def test_inject_rejects_a_duplicate_window_name(self) -> None:
        original = (FIXTURES / "existing-workbook.twb").read_text()
        clashing = original.replace(
            "<window class='worksheet' maximized='true' name='Existing Sheet'>",
            "<window class='worksheet' maximized='true' name='ARR Trend'>",
        )
        with self.assertRaisesRegex(ResourceError, "window named ARR Trend"):
            inject_fragments(
                clashing,
                "<worksheet name='ARR Trend'>\n<table />\n</worksheet>",
                "<window class='worksheet' name='ARR Trend' />",
            )

    def test_inject_requires_exactly_one_worksheets_container(self) -> None:
        original = (FIXTURES / "existing-workbook.twb").read_text()
        doubled = original.replace(
            "</worksheets>", "</worksheets>\n  <!-- </worksheets> -->", 1
        )
        with self.assertRaisesRegex(ResourceError, "</worksheets>"):
            inject_fragments(
                doubled,
                "<worksheet name='ARR Trend'>\n<table />\n</worksheet>",
                "<window class='worksheet' name='ARR Trend' />",
            )

    def test_inject_requires_a_windows_container(self) -> None:
        original = (FIXTURES / "existing-workbook.twb").read_text()
        start = original.index("<windows source-height='30'>")
        end = original.index("</windows>") + len("</windows>")
        without_windows = original[:start] + "<windows />" + original[end:]
        with self.assertRaisesRegex(ResourceError, "</windows>"):
            inject_fragments(
                without_windows,
                "<worksheet name='ARR Trend'>\n<table />\n</worksheet>",
                "<window class='worksheet' name='ARR Trend' />",
            )

    # --- starter instantiation ----------------------------------------------

    def test_instantiate_preserves_the_starter_prefix(self) -> None:
        starter = STARTER.read_text()
        output = instantiate_resource(
            datasource_definition_path=FIXTURES / "target-datasource.xml",
            output_path=self.tmp / "starter-output.twb",
            resource_id="insights__bar_chart",
            worksheet_name="ARR by Offering",
            field_mappings=dict(BAR_MAPPINGS),
            parameters=dict(BAR_PARAMETERS),
        )
        self.assertTrue(output.startswith(starter[: starter.index("<datasources />")]))
        self.assertIn("  <datasources>\n", output)
        self.assertNotIn("<?xml", output[output.index("<workbook") :])
        self.assertEqual(
            ET.fromstring(output).find("datasources/datasource").get("name"),
            "Sales Data",
        )
        self.assertEqual((self.tmp / "starter-output.twb").read_text(), output)

    def test_instantiate_renders_templates_that_use_the_user_namespace(self) -> None:
        for resource_id in ("magnitude-paired-bar", "magnitude-paired-column-chart"):
            with self.subTest(resource_id=resource_id):
                output_path = self.tmp / f"{resource_id}.twb"
                output = instantiate_resource(
                    datasource_definition_path=FIXTURES / "target-datasource.xml",
                    output_path=output_path,
                    resource_id=resource_id,
                    worksheet_name="Profit by Offering",
                    field_mappings=dict(PAIRED_MAPPINGS),
                    parameters={},
                )
                self.assertIn("user:", output)
                root = ET.fromstring(output)
                self.assertEqual(
                    [item.get("name") for item in root.findall("worksheets/worksheet")],
                    ["Profit by Offering"],
                )
                self.assertTrue(output_path.exists())

    def test_starter_declares_the_tableau_user_namespace(self) -> None:
        self.assertIn(
            "xmlns:user='http://www.tableausoftware.com/xml/user'",
            STARTER.read_text(),
        )

    def test_instantiate_rejects_a_workbook_definition(self) -> None:
        definition = self.tmp / "workbook-definition.xml"
        definition.write_text((FIXTURES / "existing-workbook.twb").read_text())
        with self.assertRaisesRegex(ResourceError, "<datasource> element"):
            instantiate_resource(
                datasource_definition_path=definition,
                output_path=self.tmp / "starter-output.twb",
                resource_id="insights__bar_chart",
                worksheet_name="ARR by Offering",
                field_mappings=dict(BAR_MAPPINGS),
                parameters=dict(BAR_PARAMETERS),
            )
        self.assertFalse((self.tmp / "starter-output.twb").exists())

    def test_instantiate_rejects_a_nested_datasource_definition(self) -> None:
        definition = self.tmp / "nested-definition.xml"
        definition.write_text(
            "<datasource name='Outer'>\n"
            "  <datasource name='Inner' />\n"
            "</datasource>\n"
        )
        with self.assertRaisesRegex(ResourceError, "exactly one"):
            instantiate_resource(
                datasource_definition_path=definition,
                output_path=self.tmp / "starter-output.twb",
                resource_id="insights__bar_chart",
                worksheet_name="ARR by Offering",
                field_mappings=dict(BAR_MAPPINGS),
                parameters=dict(BAR_PARAMETERS),
            )

    def test_instantiate_rejects_an_unnamed_datasource_definition(self) -> None:
        definition = self.tmp / "unnamed-definition.xml"
        definition.write_text("<datasource caption='Sales Data' name='' />\n")
        with self.assertRaisesRegex(ResourceError, "name"):
            instantiate_resource(
                datasource_definition_path=definition,
                output_path=self.tmp / "starter-output.twb",
                resource_id="insights__bar_chart",
                worksheet_name="ARR by Offering",
                field_mappings=dict(BAR_MAPPINGS),
                parameters=dict(BAR_PARAMETERS),
            )

    # --- atomic output ------------------------------------------------------

    def test_atomic_write_replaces_the_destination_with_overwrite(self) -> None:
        output = self.tmp / "existing.twb"
        output.write_text("stale")
        atomic_write(output, "fresh", overwrite=True)
        self.assertEqual(output.read_text(), "fresh")
        self.assertEqual([item.name for item in self.tmp.iterdir()], ["existing.twb"])

    def test_atomic_write_keeps_the_destination_file_mode(self) -> None:
        output = self.tmp / "existing.twb"
        output.write_text("stale")
        output.chmod(0o640)
        atomic_write(output, "fresh", overwrite=True)
        self.assertEqual(output.stat().st_mode & 0o777, 0o640)

    def test_inject_rejects_a_workbook_that_is_not_utf8(self) -> None:
        source = self.tmp / "latin1.twb"
        source.write_bytes(
            (FIXTURES / "existing-workbook.twb")
            .read_text()
            .replace("Sales Data", "Ventas Espa\u00f1a")
            .encode("latin-1")
        )
        with self.assertRaisesRegex(ResourceError, "Cannot read workbook"):
            self.inject_line_chart(input_path=source)

    def test_instantiate_refuses_to_replace_its_datasource_definition(self) -> None:
        definition = self.tmp / "datasource.xml"
        definition.write_text((FIXTURES / "target-datasource.xml").read_text())
        with self.assertRaisesRegex(ResourceError, "--overwrite"):
            instantiate_resource(
                datasource_definition_path=definition,
                output_path=definition,
                resource_id="insights__bar_chart",
                worksheet_name="ARR by Offering",
                field_mappings=dict(BAR_MAPPINGS),
                parameters=dict(BAR_PARAMETERS),
            )
        self.assertIn("<datasource", definition.read_text())

    def test_failed_injection_writes_no_output_and_leaves_input_unchanged(self) -> None:
        source = self.tmp / "input.twb"
        source.write_text((FIXTURES / "existing-workbook.twb").read_text())
        before = source.read_bytes()
        with self.assertRaises(ResourceError):
            self.inject_line_chart(input_path=source, field_mappings={"ARR": "Revenue"})
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual([item.name for item in self.tmp.iterdir()], ["input.twb"])

    def test_inject_refuses_to_replace_its_own_input(self) -> None:
        source = self.tmp / "input.twb"
        source.write_text((FIXTURES / "existing-workbook.twb").read_text())
        before = source.read_bytes()
        with self.assertRaisesRegex(ResourceError, "--overwrite"):
            self.inject_line_chart(input_path=source, output_path=source)
        self.assertEqual(source.read_bytes(), before)

    def test_inject_can_replace_its_own_input_with_overwrite(self) -> None:
        source = self.tmp / "input.twb"
        source.write_text((FIXTURES / "existing-workbook.twb").read_text())
        output = self.inject_line_chart(
            input_path=source, output_path=source, overwrite=True
        )
        self.assertEqual(source.read_text(), output)
        self.assertIn("<worksheet name='ARR Trend'>", source.read_text())

    # --- CLI ----------------------------------------------------------------

    def test_cli_inject_writes_the_transformed_workbook(self) -> None:
        output = self.tmp / "workbook-with-trend.twb"
        result = self.run_cli(
            "inject",
            "insights__line_chart",
            "--input",
            str(FIXTURES / "existing-workbook.twb"),
            "--output",
            str(output),
            "--worksheet-name",
            "ARR Trend",
            "--datasource",
            FIXTURE_DATASOURCE,
            "--map",
            "ARR=Revenue",
            "--map",
            "Close Date=Transaction Date",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        root = ET.fromstring(output.read_text())
        self.assertEqual(
            [item.get("name") for item in root.findall("worksheets/worksheet")],
            ["Existing Sheet", "ARR Trend"],
        )

    def test_cli_instantiate_writes_the_starter_workbook(self) -> None:
        output = self.tmp / "starter-bar.twb"
        result = self.run_cli(
            "instantiate",
            "insights__bar_chart",
            "--datasource-definition",
            str(FIXTURES / "target-datasource.xml"),
            "--output",
            str(output),
            "--worksheet-name",
            "ARR by Offering",
            "--map",
            "ARR=Revenue",
            "--map",
            "Close Date=Transaction Date",
            "--map",
            "Product=Offering",
            "--param",
            "DATE_MIN=2026-01-01",
            "--param",
            "DATE_MAX=2026-06-30",
            "--param",
            "DIRECTION=DESC",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        root = ET.fromstring(output.read_text())
        self.assertEqual(len(root.find("datasources")), 1)
        self.assertEqual(
            [item.get("name") for item in root.findall("worksheets/worksheet")],
            ["ARR by Offering"],
        )

    def test_cli_reports_a_missing_mapping_without_a_traceback(self) -> None:
        output = self.tmp / "workbook-with-trend.twb"
        result = self.run_cli(
            "inject",
            "insights__line_chart",
            "--input",
            str(FIXTURES / "existing-workbook.twb"),
            "--output",
            str(output),
            "--worksheet-name",
            "ARR Trend",
            "--datasource",
            FIXTURE_DATASOURCE,
            "--map",
            "ARR=Revenue",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing field mappings: Close Date", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(output.exists())

    def test_cli_refuses_an_existing_output_without_overwrite(self) -> None:
        output = self.tmp / "workbook-with-trend.twb"
        output.write_text("do not replace")
        result = self.run_cli(
            "inject",
            "insights__line_chart",
            "--input",
            str(FIXTURES / "existing-workbook.twb"),
            "--output",
            str(output),
            "--worksheet-name",
            "ARR Trend",
            "--datasource",
            FIXTURE_DATASOURCE,
            "--map",
            "ARR=Revenue",
            "--map",
            "Close Date=Transaction Date",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--overwrite", result.stderr)
        self.assertEqual(output.read_text(), "do not replace")


if __name__ == "__main__":
    unittest.main()

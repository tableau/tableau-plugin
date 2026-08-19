"""Fail-closed workbook validation tests.

Covers the ordered structural rules of :func:`validate_workbook_text`, the
path-based :func:`validate_workbook`, the ``validate`` CLI command, and the
guarantee that a workbook failing validation is never written to disk.

The workbooks built here are deliberately minimal rather than realistic: each
one isolates a single rule so an ordering or dedup regression cannot hide
behind an unrelated error.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

PLUGIN = Path(__file__).resolve().parents[1]
FIXTURES = PLUGIN / "tests/fixtures"
CLI = PLUGIN / "scripts/tableau_resources.py"
STARTER = PLUGIN / "resources/starters/minimal-workbook.twb"
sys.path.insert(0, str(PLUGIN / "scripts"))

import tableau_resources  # noqa: E402
from tableau_resources import (  # noqa: E402
    ResourceError,
    inject_resource,
    instantiate_resource,
    validate_workbook,
    validate_workbook_text,
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
BROKEN_WORKBOOK = (
    "<workbook><datasources /><worksheets>{{field_base_1}}</worksheets>"
    "<windows /></workbook>"
)
HIDDEN_SHEET_ERROR = "worksheet-window-name-mismatch: Hidden Sheet"


def workbook(datasources: str = "", worksheets: str = "", windows: str = "") -> str:
    """Build a minimal workbook with the three required containers."""
    return (
        "<workbook>"
        f"<datasources>{datasources}</datasources>"
        f"<worksheets>{worksheets}</worksheets>"
        f"<windows>{windows}</windows>"
        "</workbook>"
    )


def sheet(name: str, body: str) -> str:
    return f"<worksheet name='{name}'><table>{body}</table></worksheet>"


def window(name: str) -> str:
    return f"<window class='worksheet' name='{name}' />"


class ValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    # --- documents that must validate ---------------------------------------

    def test_validate_accepts_the_fixture_workbook(self) -> None:
        self.assertEqual(validate_workbook(FIXTURES / "existing-workbook.twb"), [])

    def test_validate_accepts_an_injected_workbook(self) -> None:
        output = inject_resource(
            input_path=FIXTURES / "existing-workbook.twb",
            output_path=self.tmp / "output.twb",
            resource_id="insights__line_chart",
            worksheet_name="ARR Trend",
            datasource_name=FIXTURE_DATASOURCE,
            field_mappings=dict(LINE_MAPPINGS),
            parameters={},
        )
        self.assertEqual(validate_workbook_text(output), [])
        self.assertEqual(validate_workbook(self.tmp / "output.twb"), [])

    def test_validate_accepts_an_instantiated_workbook(self) -> None:
        output = instantiate_resource(
            datasource_definition_path=FIXTURES / "target-datasource.xml",
            output_path=self.tmp / "starter-output.twb",
            resource_id="insights__bar_chart",
            worksheet_name="ARR by Offering",
            field_mappings=dict(BAR_MAPPINGS),
            parameters=dict(BAR_PARAMETERS),
        )
        self.assertEqual(validate_workbook_text(output), [])

    # --- document shape -----------------------------------------------------

    def test_validate_rejects_malformed_xml(self) -> None:
        self.assertEqual(
            validate_workbook_text("<workbook><worksheets></workbook>"),
            ["malformed-xml"],
        )

    def test_validate_rejects_a_non_workbook_root(self) -> None:
        self.assertEqual(
            validate_workbook_text((FIXTURES / "target-datasource.xml").read_text()),
            ["not-tableau-workbook"],
        )

    def test_validate_reports_every_missing_container(self) -> None:
        self.assertEqual(
            validate_workbook_text("<workbook />"),
            [
                "missing-datasources-container",
                "missing-worksheets-container",
                "missing-windows-container",
            ],
        )

    def test_validate_rejects_unresolved_tokens(self) -> None:
        path = self.tmp / "tokens.twb"
        path.write_text(BROKEN_WORKBOOK)
        self.assertIn("unresolved-template-token", validate_workbook(path))

    def test_validate_rejects_an_unresolved_federated_placeholder(self) -> None:
        text = workbook(
            worksheets=sheet("A", "<rows>[federated.XXXX].[none:Offering:nk]</rows>"),
            windows=window("A"),
        )
        self.assertIn("unresolved-federated-placeholder", validate_workbook_text(text))

    def test_validate_accepts_a_declared_federated_datasource_name(self) -> None:
        text = workbook(
            datasources=(
                f"<datasource name='{FIXTURE_DATASOURCE}'>"
                "<column datatype='real' name='[Revenue]' />"
                "</datasource>"
            ),
            worksheets=sheet(
                "A", f"<rows>[{FIXTURE_DATASOURCE}].[sum:Revenue:qk]</rows>"
            ),
            windows=window("A"),
        )
        self.assertEqual(validate_workbook_text(text), [])

    # --- worksheet and window names -----------------------------------------

    def test_validate_rejects_a_duplicate_worksheet_name(self) -> None:
        text = workbook(
            worksheets=sheet("A", "") + sheet("A", ""),
            windows=window("A"),
        )
        self.assertIn("duplicate-worksheet-name: A", validate_workbook_text(text))

    def test_validate_rejects_a_duplicate_window_name(self) -> None:
        text = workbook(
            worksheets=sheet("A", ""),
            windows=window("A") + window("A"),
        )
        self.assertIn("duplicate-window-name: A", validate_workbook_text(text))

    def test_validate_rejects_a_worksheet_without_a_window(self) -> None:
        text = workbook(worksheets=sheet("A", ""), windows="")
        self.assertIn("worksheet-window-name-mismatch: A", validate_workbook_text(text))

    def test_validate_rejects_a_worksheet_window_without_a_worksheet(self) -> None:
        text = workbook(worksheets="", windows=window("A"))
        self.assertIn("worksheet-window-name-mismatch: A", validate_workbook_text(text))

    def test_validate_ignores_non_worksheet_windows(self) -> None:
        text = workbook(
            worksheets=sheet("A", ""),
            windows=window("A") + "<window class='dashboard' name='Overview' />",
        )
        self.assertEqual(validate_workbook_text(text), [])

    # --- datasource and field references ------------------------------------

    def test_validate_rejects_missing_datasource_reference(self) -> None:
        path = self.tmp / "missing-ds.twb"
        path.write_text(
            "<workbook><datasources/><worksheets><worksheet name='X'><table>"
            "<rows>[Missing].[none:Category:nk]</rows></table></worksheet>"
            "</worksheets><windows><window class='worksheet' name='X'/></windows>"
            "</workbook>"
        )
        self.assertIn("unknown-datasource-reference: Missing", validate_workbook(path))

    def test_validate_rejects_an_unknown_field_reference(self) -> None:
        text = workbook(
            datasources=(
                "<datasource name='Sales'>"
                "<column datatype='real' name='[Revenue]' />"
                "</datasource>"
            ),
            worksheets=sheet("A", "<rows>[Sales].[sum:Nope:qk]</rows>"),
            windows=window("A"),
        )
        self.assertEqual(
            validate_workbook_text(text), ["unknown-field-reference: Sales.Nope"]
        )

    def test_validate_resolves_worksheet_local_field_definitions(self) -> None:
        text = workbook(
            datasources="<datasource name='Sales' />",
            worksheets=sheet(
                "A",
                "<view><datasource-dependencies datasource='Sales'>"
                "<column datatype='string' name='[Offering]' />"
                "<column-instance column='[Offering]' name='[none:Offering:nk]' />"
                "</datasource-dependencies></view>"
                "<rows>[Sales].[none:Offering:nk]</rows>",
            ),
            windows=window("A"),
        )
        self.assertEqual(validate_workbook_text(text), [])

    def test_validate_ignores_pseudo_and_generated_fields(self) -> None:
        text = workbook(
            datasources="<datasource name='Sales' />",
            worksheets=sheet(
                "A",
                "<rows>[Sales].[:Measure Names]</rows>"
                "<cols>[Sales].[Latitude (generated)]</cols>"
                "<pages>[Sales].[Longitude (generated)]</pages>",
            ),
            windows=window("A"),
        )
        self.assertEqual(validate_workbook_text(text), [])

    def test_validate_ignores_references_inside_datasource_definitions(self) -> None:
        text = workbook(
            datasources=(
                "<datasource name='Sales'>"
                "<connection class='excel-direct'>"
                "<relation name='Sales' table='[Sales$]' type='table'>"
                "<columns><map key='[Revenue]' value='[Sales$].[Revenue]' /></columns>"
                "</relation></connection>"
                "<column datatype='real' name='[Revenue]' />"
                "</datasource>"
            ),
            worksheets=sheet("A", "<rows>[Sales].[sum:Revenue:qk]</rows>"),
            windows=window("A"),
        )
        self.assertEqual(validate_workbook_text(text), [])

    def test_validate_ignores_geographic_semantic_roles(self) -> None:
        """A semantic role shares the reference shape but names no datasource.

        ``distribution-bar-code-chart`` carries exactly this metadata, so a
        scan that treated it as a reference would reject a workbook the CLI
        itself had just generated.
        """
        text = workbook(
            datasources="<datasource name='Sales' />",
            worksheets=sheet(
                "A",
                "<view><datasource-dependencies datasource='Sales'>"
                "<column datatype='string' name='[State/Province]' "
                "semantic-role='[State].[Name]' />"
                "</datasource-dependencies></view>"
                "<rows>[Sales].[State/Province]</rows>",
            ),
            windows=window("A"),
        )
        self.assertEqual(validate_workbook_text(text), [])

    def test_validate_ignores_semantic_values(self) -> None:
        """A semantic-value key is a geocoding role, not a field reference.

        Tableau types both as QualifiedName-ST, so a map sheet's geocoding
        default is written exactly like a datasource-qualified reference.
        """
        text = workbook(
            datasources="<datasource name='Sales' />",
            worksheets=sheet(
                "A",
                "<semantic-values>"
                "<semantic-value key='[Country].[Name]' value='&quot;United "
                "States&quot;' />"
                "</semantic-values>",
            ),
            windows=window("A"),
        )
        self.assertEqual(validate_workbook_text(text), [])

    def test_validate_ignores_a_semantic_role_outside_a_definition(self) -> None:
        text = workbook(
            datasources="<datasource name='Sales' />",
            worksheets=sheet(
                "A", "<map-layer semantic-role='[Country].[ISO3166_2]' />"
            ),
            windows=window("A"),
        )
        self.assertEqual(validate_workbook_text(text), [])

    def test_validate_accepts_a_map_workbook(self) -> None:
        self.assertEqual(validate_workbook(FIXTURES / "map-workbook.twb"), [])

    def test_inject_into_a_workbook_with_a_map_sheet(self) -> None:
        """Geographic metadata must not block extending a real map workbook."""
        output = inject_resource(
            input_path=FIXTURES / "map-workbook.twb",
            output_path=self.tmp / "map-output.twb",
            resource_id="insights__line_chart",
            worksheet_name="ARR Trend",
            datasource_name=FIXTURE_DATASOURCE,
            field_mappings=dict(LINE_MAPPINGS),
            parameters={},
        )
        self.assertIn("<semantic-value key='[Country].[Name]'", output)
        self.assertIn("semantic-role='[State].[Name]'", output)
        self.assertEqual(validate_workbook_text(output), [])
        self.assertEqual(
            [
                item.get("name")
                for item in ET.fromstring(output).findall("worksheets/worksheet")
            ],
            ["Sales Map", "ARR Trend"],
        )

    def test_validate_still_reads_references_nested_in_a_definition(self) -> None:
        text = workbook(
            datasources="<datasource name='Sales' />",
            worksheets=sheet(
                "A",
                "<view><datasource-dependencies datasource='Sales'>"
                "<group name='[Regions]' semantic-role='[Country].[Name]'>"
                "<groupfilter function='member' level='[Missing].[Region]' />"
                "</group></datasource-dependencies></view>",
            ),
            windows=window("A"),
        )
        self.assertEqual(
            validate_workbook_text(text), ["unknown-datasource-reference: Missing"]
        )

    # --- ordering and dedup -------------------------------------------------

    def test_validate_returns_stable_ordered_deduplicated_errors(self) -> None:
        text = (
            "<workbook><worksheets>"
            "<worksheet name='A'><table>"
            "<rows>[Missing].[none:Category:nk]</rows><cols>{{DATE_MIN}}</cols>"
            "</table></worksheet>"
            "<worksheet name='A'><table>"
            "<rows>[federated.XXXX].[none:Category:nk]</rows>"
            "</table></worksheet>"
            "</worksheets><windows>"
            "<window class='worksheet' name='B' /><window class='worksheet' name='B' />"
            "</windows></workbook>"
        )
        self.assertEqual(
            validate_workbook_text(text),
            [
                "missing-datasources-container",
                "unresolved-template-token",
                "unresolved-federated-placeholder",
                "duplicate-worksheet-name: A",
                "duplicate-window-name: B",
                "worksheet-window-name-mismatch: A",
                "worksheet-window-name-mismatch: B",
                "unknown-datasource-reference: Missing",
                "unknown-datasource-reference: federated.XXXX",
            ],
        )

    def test_validate_rejects_an_unreadable_workbook(self) -> None:
        with self.assertRaisesRegex(ResourceError, "Cannot read workbook"):
            validate_workbook(self.tmp / "absent.twb")

    # --- no partial output --------------------------------------------------

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

    def test_inject_rejects_an_invalid_generated_workbook(self) -> None:
        output = self.tmp / "invalid.twb"
        with mock.patch.object(
            tableau_resources, "inject_fragments", return_value=BROKEN_WORKBOOK
        ):
            with self.assertRaisesRegex(
                ResourceError,
                "Generated workbook failed validation: unresolved-template-token",
            ):
                inject_resource(
                    input_path=FIXTURES / "existing-workbook.twb",
                    output_path=output,
                    resource_id="insights__line_chart",
                    worksheet_name="ARR Trend",
                    datasource_name=FIXTURE_DATASOURCE,
                    field_mappings=dict(LINE_MAPPINGS),
                    parameters={},
                )
        self.assertFalse(output.exists())

    def test_instantiate_rejects_an_invalid_generated_workbook(self) -> None:
        output = self.tmp / "invalid-starter.twb"
        with mock.patch.object(
            tableau_resources, "inject_fragments", return_value=BROKEN_WORKBOOK
        ):
            with self.assertRaisesRegex(
                ResourceError, "Generated workbook failed validation"
            ):
                instantiate_resource(
                    datasource_definition_path=FIXTURES / "target-datasource.xml",
                    output_path=output,
                    resource_id="insights__bar_chart",
                    worksheet_name="ARR by Offering",
                    field_mappings=dict(BAR_MAPPINGS),
                    parameters=dict(BAR_PARAMETERS),
                )
        self.assertFalse(output.exists())

    def test_invalid_generation_leaves_an_existing_output_untouched(self) -> None:
        output = self.tmp / "keep.twb"
        output.write_text("do not replace")
        with mock.patch.object(
            tableau_resources, "inject_fragments", return_value=BROKEN_WORKBOOK
        ):
            with self.assertRaisesRegex(
                ResourceError, "Generated workbook failed validation"
            ):
                inject_resource(
                    input_path=FIXTURES / "existing-workbook.twb",
                    output_path=output,
                    resource_id="insights__line_chart",
                    worksheet_name="ARR Trend",
                    datasource_name=FIXTURE_DATASOURCE,
                    field_mappings=dict(LINE_MAPPINGS),
                    parameters={},
                    overwrite=True,
                )
        self.assertEqual(output.read_text(), "do not replace")

    # --- delta gate ---------------------------------------------------------

    def hidden_sheet_workbook(self) -> Path:
        """An input workbook that already fails one rule, as a real one may.

        Tableau writes no worksheet window for a sheet that exists only to
        feed a dashboard, so this is the shape of a genuine pre-existing
        mismatch rather than a contrived one.
        """
        source = self.tmp / "hidden-sheet.twb"
        source.write_text(
            (FIXTURES / "existing-workbook.twb")
            .read_text()
            .replace(
                "  </worksheets>",
                "    <worksheet name='Hidden Sheet'>\n"
                "      <table />\n"
                "    </worksheet>\n"
                "  </worksheets>",
            )
        )
        return source

    def test_input_baseline_errors_are_reported_before_injection(self) -> None:
        self.assertEqual(
            validate_workbook(self.hidden_sheet_workbook()), [HIDDEN_SHEET_ERROR]
        )

    def test_inject_allows_an_unchanged_pre_existing_error(self) -> None:
        output_path = self.tmp / "hidden-sheet-output.twb"
        output = inject_resource(
            input_path=self.hidden_sheet_workbook(),
            output_path=output_path,
            resource_id="insights__line_chart",
            worksheet_name="ARR Trend",
            datasource_name=FIXTURE_DATASOURCE,
            field_mappings=dict(LINE_MAPPINGS),
            parameters={},
        )
        self.assertTrue(output_path.exists())
        self.assertEqual(validate_workbook_text(output), [HIDDEN_SHEET_ERROR])
        self.assertEqual(
            [
                item.get("name")
                for item in ET.fromstring(output).findall("worksheets/worksheet")
            ],
            ["Existing Sheet", "Hidden Sheet", "ARR Trend"],
        )

    def test_inject_blocks_a_newly_introduced_error(self) -> None:
        output_path = self.tmp / "introduced.twb"
        with mock.patch.object(
            tableau_resources, "inject_fragments", return_value=BROKEN_WORKBOOK
        ):
            with self.assertRaises(ResourceError) as raised:
                inject_resource(
                    input_path=self.hidden_sheet_workbook(),
                    output_path=output_path,
                    resource_id="insights__line_chart",
                    worksheet_name="ARR Trend",
                    datasource_name=FIXTURE_DATASOURCE,
                    field_mappings=dict(LINE_MAPPINGS),
                    parameters={},
                )
        message = str(raised.exception)
        self.assertEqual(
            message,
            "Generated workbook failed validation: unresolved-template-token "
            "(pre-existing errors carried in from the input workbook: "
            f"{HIDDEN_SHEET_ERROR})",
        )
        self.assertFalse(output_path.exists())

    def test_inject_blocks_a_new_instance_of_an_inherited_rule(self) -> None:
        """Inheritance is per error, not per rule.

        The input already has an unpaired sheet, but that cannot license a
        different unpaired sheet in the output.
        """
        output_path = self.tmp / "second-mismatch.twb"
        introduced = (
            "<workbook><datasources /><worksheets>"
            "<worksheet name='Hidden Sheet' /><worksheet name='Another Sheet' />"
            "</worksheets><windows /></workbook>"
        )
        with mock.patch.object(
            tableau_resources, "inject_fragments", return_value=introduced
        ):
            with self.assertRaises(ResourceError) as raised:
                inject_resource(
                    input_path=self.hidden_sheet_workbook(),
                    output_path=output_path,
                    resource_id="insights__line_chart",
                    worksheet_name="ARR Trend",
                    datasource_name=FIXTURE_DATASOURCE,
                    field_mappings=dict(LINE_MAPPINGS),
                    parameters={},
                )
        message = str(raised.exception)
        self.assertIn("worksheet-window-name-mismatch: Another Sheet", message)
        self.assertNotIn(
            "Generated workbook failed validation: "
            "worksheet-window-name-mismatch: Hidden Sheet",
            message,
        )
        self.assertFalse(output_path.exists())

    def test_inject_allows_an_output_that_removes_an_input_error(self) -> None:
        output_path = self.tmp / "repaired.twb"
        repaired = (FIXTURES / "existing-workbook.twb").read_text()
        with mock.patch.object(
            tableau_resources, "inject_fragments", return_value=repaired
        ):
            output = inject_resource(
                input_path=self.hidden_sheet_workbook(),
                output_path=output_path,
                resource_id="insights__line_chart",
                worksheet_name="ARR Trend",
                datasource_name=FIXTURE_DATASOURCE,
                field_mappings=dict(LINE_MAPPINGS),
                parameters={},
            )
        self.assertEqual(validate_workbook_text(output), [])
        self.assertEqual(output_path.read_text(), repaired)

    # --- instantiate baseline -----------------------------------------------

    def write_definition(self, name: str, body: str) -> Path:
        """Write a datasource definition that satisfies the bar mappings."""
        path = self.tmp / f"{name}.xml"
        path.write_text(
            f"{body}\n"
            "  <column datatype='real' name='[Revenue]' role='measure' "
            "type='quantitative' />\n"
            "  <column datatype='date' name='[Transaction Date]' "
            "role='dimension' type='ordinal' />\n"
            "  <column datatype='string' name='[Offering]' role='dimension' "
            "type='nominal' />\n"
            "</datasource>\n"
        )
        return path

    def instantiate_bar(self, definition: Path, output: Path) -> str:
        return instantiate_resource(
            datasource_definition_path=definition,
            output_path=output,
            resource_id="insights__bar_chart",
            worksheet_name="ARR by Offering",
            field_mappings=dict(BAR_MAPPINGS),
            parameters=dict(BAR_PARAMETERS),
        )

    def test_starter_workbook_is_a_clean_baseline(self) -> None:
        """The instantiate baseline inherits nothing, so nothing is excused."""
        self.assertEqual(validate_workbook(STARTER), [])

    def test_instantiate_rejects_a_definition_with_a_template_token(self) -> None:
        definition = self.write_definition(
            "token-definition",
            "<datasource caption='Sales Data' name='Sales Data' version='18.1'>\n"
            "  <connection class='federated'>\n"
            "    <relation name='Sales' table='[{{TABLE}}$]' type='table' />\n"
            "  </connection>",
        )
        output = self.tmp / "token-output.twb"
        with self.assertRaisesRegex(
            ResourceError,
            "^Generated workbook failed validation: unresolved-template-token$",
        ):
            self.instantiate_bar(definition, output)
        self.assertFalse(output.exists())

    def test_instantiate_rejects_a_definition_whose_caption_is_a_token(self) -> None:
        """The caption reaches the rendered view, so it is checked as input."""
        definition = self.write_definition(
            "caption-token-definition",
            "<datasource caption='{{DATASOURCE}}' name='Sales Data' "
            "version='18.1'>",
        )
        output = self.tmp / "caption-token-output.twb"
        with self.assertRaisesRegex(
            ResourceError,
            "^datasource_caption must not contain a template token: "
            r"\{\{DATASOURCE\}\}$",
        ):
            self.instantiate_bar(definition, output)
        self.assertFalse(output.exists())

    def test_instantiate_rejects_a_definition_with_a_federated_placeholder(
        self,
    ) -> None:
        definition = self.write_definition(
            "federated-definition",
            "<datasource caption='Sales Data' name='Sales Data' version='18.1'>\n"
            "  <connection class='federated'>\n"
            "    <named-connections>\n"
            "      <named-connection caption='sales' name='federated.XXXX' />\n"
            "    </named-connections>\n"
            "    <relation name='Sales' table='[Sales$]' type='table' />\n"
            "  </connection>",
        )
        output = self.tmp / "federated-output.twb"
        with self.assertRaisesRegex(
            ResourceError,
            "^Generated workbook failed validation: "
            "unresolved-federated-placeholder$",
        ):
            self.instantiate_bar(definition, output)
        self.assertFalse(output.exists())

    def test_instantiate_accepts_a_clean_definition(self) -> None:
        output_path = self.tmp / "clean-output.twb"
        output = self.instantiate_bar(
            self.write_definition(
                "clean-definition",
                "<datasource caption='Sales Data' name='Sales Data' "
                "version='18.1'>",
            ),
            output_path,
        )
        self.assertEqual(validate_workbook_text(output), [])
        self.assertTrue(output_path.exists())

    def test_instantiate_accepts_a_federated_definition_name(self) -> None:
        """A real federated name is not a placeholder and must still work."""
        output_path = self.tmp / "clean-federated-output.twb"
        output = self.instantiate_bar(
            self.write_definition(
                "clean-federated-definition",
                f"<datasource caption='Sales Data' name='{FIXTURE_DATASOURCE}' "
                "version='18.1'>",
            ),
            output_path,
        )
        self.assertEqual(validate_workbook_text(output), [])
        self.assertIn(f"[{FIXTURE_DATASOURCE}].[sum:Revenue:qk]", output)
        self.assertTrue(output_path.exists())

    # --- CLI ----------------------------------------------------------------

    def test_cli_validate_exits_zero_for_a_valid_workbook(self) -> None:
        result = self.run_cli(
            "validate", "--input", str(FIXTURES / "existing-workbook.twb")
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "[]")

    def test_cli_validate_exits_one_with_json_errors(self) -> None:
        path = self.tmp / "tokens.twb"
        path.write_text(BROKEN_WORKBOOK)
        result = self.run_cli("validate", "--input", str(path))
        self.assertEqual(result.returncode, 1)
        self.assertIn("unresolved-template-token", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_validate_reports_an_unreadable_input(self) -> None:
        result = self.run_cli("validate", "--input", str(self.tmp / "absent.twb"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Cannot read workbook", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()

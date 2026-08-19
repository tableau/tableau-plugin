"""Target-datasource metadata tests.

Covers the three defects that a real Tableau workbook exposes but the bundled
fixtures did not:

1. Fields declared only under ``<connection>/<metadata-records>`` were
   invisible to mapping validation, so every mapping against such a workbook
   was rejected.
2. A rendered ``<datasource-dependencies>`` column kept the donor's
   ``datatype``/``user-datatype``/``role`` after its name was rewritten to a
   target field, so the declaration described a field that no longer existed.
3. The rendered per-view ``<datasource>`` caption was set to the target's
   internal ``federated.<hash>`` name instead of its human caption.
"""

from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

PLUGIN = Path(__file__).resolve().parents[1]
FIXTURES = PLUGIN / "tests/fixtures"
sys.path.insert(0, str(PLUGIN / "scripts"))

from tableau_resources import (  # noqa: E402
    ResourceError,
    inject_resource,
    inspect_datasources,
    instantiate_resource,
)

FIXTURE_DATASOURCE = "federated.0fixture1sales2data"
METADATA_DATASOURCE = "federated.0meta1records2only"
TARGET_DATASOURCE = "federated.0captioned"
DONOR_DATASOURCE = "Sample - Superstore"
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


def dependency_columns(workbook: str, worksheet_name: str) -> dict[str, ET.Element]:
    """Return the worksheet's dependency ``<column>`` declarations by name."""
    root = ET.fromstring(workbook)
    for worksheet in root.findall("worksheets/worksheet"):
        if worksheet.get("name") != worksheet_name:
            continue
        return {
            (column.get("name") or "")[1:-1]: column
            for column in worksheet.iter("column")
            if (column.get("name") or "").startswith("[")
        }
    raise AssertionError(f"no worksheet named {worksheet_name}")


def view_datasource(workbook: str, worksheet_name: str) -> ET.Element:
    """Return the worksheet's per-view ``<datasource>`` declaration."""
    root = ET.fromstring(workbook)
    for worksheet in root.findall("worksheets/worksheet"):
        if worksheet.get("name") == worksheet_name:
            return worksheet.find("table/view/datasources/datasource")
    raise AssertionError(f"no worksheet named {worksheet_name}")


class TargetMetadataTest(unittest.TestCase):
    maxDiff = None

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

    def write_workbook(self, name: str, datasource: str) -> Path:
        """Write a minimal workbook around one datasource definition."""
        path = self.tmp / f"{name}.twb"
        path.write_text(
            "<?xml version='1.0' encoding='utf-8' ?>\n"
            "<workbook version='18.1' "
            "xmlns:user='http://www.tableausoftware.com/xml/user'>\n"
            "  <datasources>\n"
            f"{datasource}\n"
            "  </datasources>\n"
            "  <worksheets>\n"
            "  </worksheets>\n"
            "  <windows>\n"
            "  </windows>\n"
            "</workbook>\n"
        )
        return path

    # --- finding 1: metadata-record fields ----------------------------------

    def test_inspect_datasources_unions_metadata_record_fields(self) -> None:
        text = (FIXTURES / "metadata-records-workbook.twb").read_text()
        self.assertEqual(
            inspect_datasources(text),
            {METADATA_DATASOURCE: {"Revenue", "Transaction Date", "Offering"}},
        )

    def test_inject_into_a_metadata_record_only_workbook(self) -> None:
        output = self.inject_line_chart(
            input_path=FIXTURES / "metadata-records-workbook.twb",
            datasource_name=METADATA_DATASOURCE,
        )
        self.assertIn(f"[{METADATA_DATASOURCE}].[sum:Revenue:qk]", output)
        self.assertEqual(
            [
                item.get("name")
                for item in ET.fromstring(output).findall("worksheets/worksheet")
            ],
            ["ARR Trend"],
        )

    def test_inspect_datasources_unions_columns_and_metadata_records(self) -> None:
        path = self.write_workbook(
            "mixed",
            "    <datasource caption='Mixed' name='Mixed' version='18.1'>\n"
            "      <connection class='federated'>\n"
            "        <metadata-records>\n"
            "          <metadata-record class='column'>\n"
            "            <local-name>[Only In Records]</local-name>\n"
            "            <local-type>string</local-type>\n"
            "          </metadata-record>\n"
            "        </metadata-records>\n"
            "      </connection>\n"
            "      <column datatype='real' name='[Only A Column]' role='measure' "
            "type='quantitative' />\n"
            "    </datasource>",
        )
        self.assertEqual(
            inspect_datasources(path.read_text()),
            {"Mixed": {"Only In Records", "Only A Column"}},
        )

    def test_inspect_datasources_ignores_malformed_metadata_records(self) -> None:
        path = self.write_workbook(
            "malformed",
            "    <datasource caption='Odd' name='Odd' version='18.1'>\n"
            "      <connection class='federated'>\n"
            "        <metadata-records>\n"
            "          <metadata-record class='capability'>\n"
            "            <local-name>[Not A Column]</local-name>\n"
            "          </metadata-record>\n"
            "          <metadata-record class='column'>\n"
            "            <local-name>unbracketed</local-name>\n"
            "          </metadata-record>\n"
            "          <metadata-record class='column'>\n"
            "            <local-name />\n"
            "          </metadata-record>\n"
            "          <metadata-record class='column' />\n"
            "          <metadata-record class='column'>\n"
            "            <local-name>[Good]</local-name>\n"
            "            <local-type>string</local-type>\n"
            "          </metadata-record>\n"
            "        </metadata-records>\n"
            "      </connection>\n"
            "    </datasource>",
        )
        self.assertEqual(inspect_datasources(path.read_text()), {"Odd": {"Good"}})

    # --- finding 2: dependency metadata rewrite -----------------------------

    def test_mapped_dependency_column_uses_target_datatype(self) -> None:
        """The donor's ARR is an integer; the target's Revenue is a real."""
        output = self.inject_line_chart()
        revenue = dependency_columns(output, "ARR Trend")["Revenue"]
        self.assertEqual(revenue.get("datatype"), "real")
        self.assertEqual(revenue.get("user-datatype"), "real")
        self.assertEqual(revenue.get("role"), "measure")

    def test_mapped_dependency_column_uses_metadata_record_datatype(self) -> None:
        output = self.inject_line_chart(
            input_path=FIXTURES / "metadata-records-workbook.twb",
            datasource_name=METADATA_DATASOURCE,
        )
        columns = dependency_columns(output, "ARR Trend")
        self.assertEqual(columns["Revenue"].get("datatype"), "real")
        self.assertEqual(columns["Revenue"].get("role"), "measure")
        self.assertEqual(columns["Transaction Date"].get("datatype"), "date")
        self.assertEqual(columns["Transaction Date"].get("role"), "dimension")

    def test_unmapped_dependency_columns_keep_donor_metadata(self) -> None:
        """Only explicitly mapped fields are rewritten."""
        output = instantiate_resource(
            datasource_definition_path=FIXTURES / "target-datasource.xml",
            output_path=self.tmp / "bar.twb",
            resource_id="insights__bar_chart",
            worksheet_name="ARR by Offering",
            field_mappings=dict(BAR_MAPPINGS),
            parameters=dict(BAR_PARAMETERS),
        )
        columns = dependency_columns(output, "ARR by Offering")
        self.assertEqual(columns["Offering"].get("datatype"), "string")
        self.assertEqual(columns["Offering"].get("aggregation"), "Count")
        self.assertEqual(columns["Offering"].get("visual-totals"), "Default")

    def test_inject_rejects_a_cross_family_mapping(self) -> None:
        with self.assertRaisesRegex(ResourceError, "ARR"):
            self.inject_line_chart(
                field_mappings={
                    "ARR": "Offering",
                    "Close Date": "Transaction Date",
                }
            )
        self.assertFalse((self.tmp / "output.twb").exists())

    def test_inject_rejects_a_temporal_to_string_mapping(self) -> None:
        with self.assertRaisesRegex(ResourceError, "Close Date"):
            self.inject_line_chart(
                field_mappings={"ARR": "Revenue", "Close Date": "Offering"}
            )
        self.assertFalse((self.tmp / "output.twb").exists())

    def test_inject_allows_an_integer_to_real_mapping(self) -> None:
        """Both are numeric, so the mapping is legal and the type is rewritten."""
        output = self.inject_line_chart()
        self.assertEqual(
            dependency_columns(output, "ARR Trend")["Revenue"].get("datatype"), "real"
        )

    def test_inject_rejects_a_target_field_of_unknown_type(self) -> None:
        path = self.write_workbook(
            "untyped",
            "    <datasource caption='Untyped' name='Untyped' version='18.1'>\n"
            "      <column name='[Revenue]' />\n"
            "      <column datatype='date' name='[Transaction Date]' "
            "role='dimension' type='ordinal' />\n"
            "    </datasource>",
        )
        with self.assertRaisesRegex(ResourceError, "Revenue"):
            self.inject_line_chart(input_path=path, datasource_name="Untyped")
        self.assertFalse((self.tmp / "output.twb").exists())

    # --- finding 3: per-view caption ----------------------------------------

    def test_view_datasource_uses_the_target_caption(self) -> None:
        output = self.inject_line_chart()
        declared = view_datasource(output, "ARR Trend")
        self.assertEqual(declared.get("caption"), "Sales Data")
        self.assertEqual(declared.get("name"), FIXTURE_DATASOURCE)

    def test_view_datasource_falls_back_to_the_internal_name(self) -> None:
        path = self.write_workbook(
            "uncaptioned",
            "    <datasource name='Uncaptioned' version='18.1'>\n"
            "      <column datatype='real' name='[Revenue]' role='measure' "
            "type='quantitative' />\n"
            "      <column datatype='date' name='[Transaction Date]' "
            "role='dimension' type='ordinal' />\n"
            "    </datasource>",
        )
        output = self.inject_line_chart(
            input_path=path, datasource_name="Uncaptioned"
        )
        declared = view_datasource(output, "ARR Trend")
        self.assertEqual(declared.get("caption"), "Uncaptioned")
        self.assertEqual(declared.get("name"), "Uncaptioned")

    def test_view_datasource_caption_is_re_escaped(self) -> None:
        """A caption is decoded when read, so it must be escaped when written."""
        path = self.write_workbook(
            "escaped",
            "    <datasource caption='Sales &amp; Ops &lt;EMEA&gt;' "
            "name='federated.0escaped' version='18.1'>\n"
            "      <column datatype='real' name='[Revenue]' role='measure' "
            "type='quantitative' />\n"
            "      <column datatype='date' name='[Transaction Date]' "
            "role='dimension' type='ordinal' />\n"
            "    </datasource>",
        )
        output = self.inject_line_chart(
            input_path=path, datasource_name="federated.0escaped"
        )
        self.assertIn("caption='Sales &amp; Ops &lt;EMEA&gt;'", output)
        self.assertEqual(
            view_datasource(output, "ARR Trend").get("caption"),
            "Sales & Ops <EMEA>",
        )

    # --- a legitimate caption may look like donor residue ---------------------

    def write_typed_datasource(self, caption: str) -> str:
        """Return a datasource declaration the line chart can be mapped onto."""
        return (
            f"    <datasource caption='{caption}' name='{TARGET_DATASOURCE}' "
            "version='18.1'>\n"
            "      <column datatype='real' name='[Revenue]' role='measure' "
            "type='quantitative' />\n"
            "      <column datatype='date' name='[Transaction Date]' "
            "role='dimension' type='ordinal' />\n"
            "    </datasource>"
        )

    def assert_injects_with_caption(self, caption: str) -> None:
        path = self.write_workbook(
            f"captioned-{abs(hash(caption))}", self.write_typed_datasource(caption)
        )
        output = self.inject_line_chart(
            input_path=path, datasource_name=TARGET_DATASOURCE
        )
        declared = view_datasource(output, "ARR Trend")
        self.assertEqual(declared.get("caption"), caption)
        self.assertEqual(declared.get("name"), TARGET_DATASOURCE)
        self.assertIn(f"[{TARGET_DATASOURCE}].[sum:Revenue:qk]", output)

    def test_inject_allows_a_caption_equal_to_the_donor(self) -> None:
        """The target may legitimately be captioned after the donor itself."""
        self.assert_injects_with_caption(DONOR_DATASOURCE)

    def test_inject_allows_a_caption_containing_the_donor(self) -> None:
        self.assert_injects_with_caption(f"{DONOR_DATASOURCE} (EMEA Rollup)")

    def test_instantiate_allows_a_caption_equal_to_the_donor(self) -> None:
        definition = self.tmp / "donor-caption.xml"
        definition.write_text(
            f"<datasource caption='{DONOR_DATASOURCE}' name='Sales Data' "
            "version='18.1'>\n"
            "  <column datatype='real' name='[Revenue]' role='measure' "
            "type='quantitative' />\n"
            "  <column datatype='date' name='[Transaction Date]' "
            "role='dimension' type='ordinal' />\n"
            "</datasource>\n"
        )
        output = instantiate_resource(
            datasource_definition_path=definition,
            output_path=self.tmp / "donor-caption.twb",
            resource_id="insights__line_chart",
            worksheet_name="ARR Trend",
            field_mappings=dict(LINE_MAPPINGS),
            parameters={},
        )
        declared = view_datasource(output, "ARR Trend")
        self.assertEqual(declared.get("caption"), DONOR_DATASOURCE)
        self.assertEqual(declared.get("name"), "Sales Data")
        self.assertIn("[Sales Data].[sum:Revenue:qk]", output)

    def test_datasource_references_keep_the_internal_name(self) -> None:
        output = self.inject_line_chart()
        self.assertIn(f"[{FIXTURE_DATASOURCE}].[sum:Revenue:qk]", output)
        self.assertIn(f"datasource='{FIXTURE_DATASOURCE}'", output)
        self.assertNotIn("[Sales Data].[", output)


if __name__ == "__main__":
    unittest.main()

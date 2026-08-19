"""Rendering tests for executable bookmark conversion.

Covers assignment parsing, field/parameter contract validation, donor
rewriting, escaping, transient-state removal, identity assignment, and the
fail-closed output checks.
"""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET

PLUGIN = Path(__file__).resolve().parents[1]
FIXTURES = PLUGIN / "tests/fixtures"
GOLDEN = FIXTURES / "golden"
sys.path.insert(0, str(PLUGIN / "scripts"))

from tableau_resources import (  # noqa: E402
    ResourceError,
    load_catalog,
    parse_assignments,
    render_bookmark,
)

# Imported directly because two of its guarantees — a donor-addressing
# name/datasource attribute and a donor qualified reference — cannot be
# reached through the public render path, which rewrites both before this
# check runs. They are the checks a caption exemption must not weaken, so
# they are pinned here rather than left untested.
from tableau_resources import _reject_unsafe_output  # noqa: E402

PULSE_BAR_MAPPINGS = {
    "ARR": "Revenue",
    "Close Date": "Transaction Date",
    "Product": "Offering",
}
PULSE_BAR_PARAMETERS = {
    "DATE_MIN": "2026-01-01",
    "DATE_MAX": "2026-06-30",
    "DIRECTION": "DESC",
}
REFERENCE_ONLY_ID = (
    "magnitude__horizontal-bar__compare-discrete-categories-from-zero"
)
# Fragments are embedded in a workbook that declares Tableau's namespaces, so
# a fragment carrying a "user:" attribute is only parseable in that context.
WRAPPER = (
    "<wrapper xmlns:user='http://www.tableausoftware.com/xml/user'>%s</wrapper>"
)


def parse_fragment(fragment: str) -> ET.Element:
    return list(ET.fromstring(WRAPPER % fragment))[0]

SYNTHETIC_BOOKMARK = """<?xml version='1.0' encoding='utf-8' ?>
<bookmark version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
<cards>
  <edge name='left'>
    <strip size='160'>
      <card type='marks' />
    </strip>
  </edge>
</cards>
<window class='worksheet' name='synthetic'>
  <viewpoint>
    <highlight>
      <color-one-way>
        <field>[Donor DS].[none:Widget:nk]</field>
      </color-one-way>
    </highlight>
  </viewpoint>
  <simple-id uuid='{00000000-0000-0000-0000-000000000002}' />
</window>
<table>
    <view>
      <datasources>
        <datasource caption='Donor DS' name='Donor DS' />
      </datasources>
      <datasource-dependencies datasource='Donor DS'>
        <column datatype='string' name='[Widget]' role='dimension' type='nominal' />
        <column datatype='real' name='[Amount]' role='measure' type='quantitative' />
        <column-instance column='[Widget]' derivation='None' name='[none:Widget:nk]' pivot='key' type='nominal' />
        <column-instance column='[Amount]' derivation='Sum' name='[sum:Amount:qk]' pivot='key' type='quantitative' />
      </datasource-dependencies>
      <aggregation value='true' />
    </view>
    <style />
    <panes>
      <pane>
        <mark class='Bar' />
      </pane>
    </panes>
    <rows>[Donor DS].[none:Widget:nk]</rows>
    <cols>[Donor DS].[sum:Amount:qk]</cols>
  </table>
</bookmark>
"""


def _synthetic_entry(resource_id: str, bookmark: str) -> dict[str, object]:
    return {
        "id": resource_id,
        "type": "template",
        "family": None,
        "intent": "synthetic fixture",
        "path": f"./templates/executable/{resource_id}.tbm",
        "tier": "executable",
        "classificationReasons": [],
        "datasources": ["Donor DS"],
        "fields": [
            {
                "sourceField": "Amount",
                "datasource": "Donor DS",
                "datatype": "real",
                "role": "measure",
                "derivation": "Sum",
                "shelf": "columns",
            },
            {
                "sourceField": "Widget",
                "datasource": "Donor DS",
                "datatype": "string",
                "role": "dimension",
                "derivation": "None",
                "shelf": "rows",
            },
        ],
        "parameters": [],
        "keywords": ["synthetic"],
        "sha256": hashlib.sha256(bookmark.encode("utf-8")).hexdigest(),
    }


class RenderSupportMixin(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tableau-render-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def make_plugin_root(
        self,
        resource_id: str,
        bookmark: str,
        *,
        sha256: str | None = None,
        parameters: list[object] | None = None,
    ) -> Path:
        """Create a throwaway plugin root holding one synthetic template.

        The root deliberately has no ``catalog-overrides.json``, so anything
        the tests prove about parameter validation is proven from the
        generated catalog alone.
        """
        root = Path(tempfile.mkdtemp(dir=self.tmp))
        templates = root / "resources/templates/executable"
        templates.mkdir(parents=True)
        (templates / f"{resource_id}.tbm").write_text(bookmark, encoding="utf-8")
        entry = _synthetic_entry(resource_id, bookmark)
        if sha256 is not None:
            entry["sha256"] = sha256
        if parameters is not None:
            entry["parameters"] = parameters
        catalog = {
            "schemaVersion": 1,
            "generatedFrom": {
                "provenance": "./provenance.json",
                "overrides": "./catalog-overrides.json",
            },
            "resources": [entry],
        }
        (root / "resources/catalog.json").write_text(
            json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
        )
        return root

    def render_synthetic(
        self,
        bookmark: str,
        *,
        field_mappings: dict[str, str] | None = None,
        worksheet_name: str = "Synthetic Sheet",
        datasource_name: str = "Sales Data",
        sha256: str | None = None,
        catalog_parameters: list[object] | None = None,
        parameters: dict[str, str] | None = None,
        datasource_caption: str | None = None,
    ) -> tuple[str, str]:
        root = self.make_plugin_root(
            "synthetic", bookmark, sha256=sha256, parameters=catalog_parameters
        )
        return render_bookmark(
            plugin_root=root,
            resource_id="synthetic",
            worksheet_name=worksheet_name,
            datasource_name=datasource_name,
            field_mappings=(
                {"Widget": "Offering", "Amount": "Revenue"}
                if field_mappings is None
                else field_mappings
            ),
            parameters=parameters or {},
            datasource_caption=datasource_caption,
        )


class AssignmentParsingTest(unittest.TestCase):
    def test_parses_name_value_pairs_and_strips_whitespace(self) -> None:
        self.assertEqual(
            parse_assignments(["ARR=Revenue", " Close Date = Transaction Date "]),
            {"ARR": "Revenue", "Close Date": "Transaction Date"},
        )

    def test_keeps_equals_signs_inside_the_value(self) -> None:
        self.assertEqual(parse_assignments(["EXPR=a=b"]), {"EXPR": "a=b"})

    def test_missing_equals_fails(self) -> None:
        with self.assertRaisesRegex(ResourceError, "Expected NAME=VALUE, got: ARR"):
            parse_assignments(["ARR"])

    def test_empty_name_or_value_fails(self) -> None:
        with self.assertRaisesRegex(ResourceError, "Invalid or duplicate assignment"):
            parse_assignments(["=Revenue"])
        with self.assertRaisesRegex(ResourceError, "Invalid or duplicate assignment"):
            parse_assignments(["ARR="])

    def test_duplicate_name_fails(self) -> None:
        with self.assertRaisesRegex(ResourceError, "Invalid or duplicate assignment"):
            parse_assignments(["ARR=Revenue", "ARR=Bookings"])

    def test_duplicate_name_after_whitespace_normalization_fails(self) -> None:
        with self.assertRaisesRegex(ResourceError, "Invalid or duplicate assignment"):
            parse_assignments(["ARR=Revenue", " ARR =Bookings"])


class PulseBarRenderTest(unittest.TestCase):
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
                resource_id=REFERENCE_ONLY_ID,
                worksheet_name="Blocked",
                datasource_name="Sales Data",
                field_mappings={},
                parameters={},
            )

    def test_unknown_resource_fails_closed(self) -> None:
        with self.assertRaisesRegex(ResourceError, "Unknown resource: does-not-exist"):
            render_bookmark(
                plugin_root=PLUGIN,
                resource_id="does-not-exist",
                worksheet_name="Blocked",
                datasource_name="Sales Data",
                field_mappings={},
                parameters={},
            )

    def test_worksheet_and_window_shape(self) -> None:
        worksheet, window = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name="ARR by Offering",
            datasource_name="Sales Data",
            field_mappings=PULSE_BAR_MAPPINGS,
            parameters=PULSE_BAR_PARAMETERS,
        )
        worksheet_root = ET.fromstring(worksheet)
        self.assertEqual(worksheet_root.tag, "worksheet")
        self.assertEqual(worksheet_root.get("name"), "ARR by Offering")
        self.assertEqual([child.tag for child in worksheet_root], ["table"])

        window_root = ET.fromstring(window)
        self.assertEqual(window_root.tag, "window")
        self.assertEqual(window_root.get("class"), "worksheet")
        self.assertEqual(window_root.get("name"), "ARR by Offering")
        self.assertIsNotNone(window_root.find("cards"))

    def test_transient_highlight_state_is_removed(self) -> None:
        worksheet, window = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__line_chart",
            worksheet_name="ARR Trend",
            datasource_name="Sales Data",
            field_mappings={"ARR": "Revenue", "Close Date": "Transaction Date"},
            parameters={},
        )
        combined = worksheet + window
        self.assertNotIn("highlight", combined)
        self.assertNotIn("color-one-way", combined)
        # The donor-only [yr:Close Date:ok] instance existed solely inside the
        # removed highlight block.
        self.assertNotIn("yr:", combined)

    def test_fragment_simple_ids_are_deterministic_uuid5(self) -> None:
        first = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name="ARR by Offering",
            datasource_name="Sales Data",
            field_mappings=PULSE_BAR_MAPPINGS,
            parameters=PULSE_BAR_PARAMETERS,
        )
        second = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name="ARR by Offering",
            datasource_name="Sales Data",
            field_mappings=PULSE_BAR_MAPPINGS,
            parameters=PULSE_BAR_PARAMETERS,
        )
        renamed = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name="Other Name",
            datasource_name="Sales Data",
            field_mappings=PULSE_BAR_MAPPINGS,
            parameters=PULSE_BAR_PARAMETERS,
        )
        self.assertEqual(first, second)
        self.assertNotIn("F2A39237-BE90-4B47-9E19-B30712717ACA", first[1])
        window_uuid = ET.fromstring(first[1]).find("simple-id").get("uuid")
        renamed_uuid = ET.fromstring(renamed[1]).find("simple-id").get("uuid")
        self.assertNotEqual(window_uuid, renamed_uuid)
        parsed = uuid.UUID(window_uuid)
        self.assertEqual(parsed.version, 5)
        self.assertEqual(window_uuid, "{%s}" % str(parsed).upper())


class ContractValidationTest(unittest.TestCase):
    def render_bar(self, **overrides: object) -> tuple[str, str]:
        kwargs: dict[str, object] = {
            "plugin_root": PLUGIN,
            "resource_id": "insights__bar_chart",
            "worksheet_name": "ARR by Offering",
            "datasource_name": "Sales Data",
            "field_mappings": dict(PULSE_BAR_MAPPINGS),
            "parameters": dict(PULSE_BAR_PARAMETERS),
        }
        kwargs.update(overrides)
        return render_bookmark(**kwargs)

    def test_unknown_field_mapping_is_rejected(self) -> None:
        mappings = dict(PULSE_BAR_MAPPINGS)
        mappings["Not A Field"] = "Revenue"
        with self.assertRaisesRegex(ResourceError, "Unknown field mappings: Not A Field"):
            self.render_bar(field_mappings=mappings)

    def test_missing_parameter_is_rejected(self) -> None:
        parameters = dict(PULSE_BAR_PARAMETERS)
        del parameters["DATE_MAX"]
        with self.assertRaisesRegex(ResourceError, "Missing parameters: DATE_MAX"):
            self.render_bar(parameters=parameters)

    def test_unknown_parameter_is_rejected(self) -> None:
        parameters = dict(PULSE_BAR_PARAMETERS)
        parameters["NOPE"] = "1"
        with self.assertRaisesRegex(ResourceError, "Unknown parameters: NOPE"):
            self.render_bar(parameters=parameters)

    def test_non_iso_date_parameter_is_rejected(self) -> None:
        parameters = dict(PULSE_BAR_PARAMETERS)
        parameters["DATE_MIN"] = "01/01/2026"
        with self.assertRaisesRegex(ResourceError, "DATE_MIN.*ISO-8601 date"):
            self.render_bar(parameters=parameters)

    def test_enum_parameter_outside_allowed_values_is_rejected(self) -> None:
        parameters = dict(PULSE_BAR_PARAMETERS)
        parameters["DIRECTION"] = "SIDEWAYS"
        with self.assertRaisesRegex(ResourceError, "DIRECTION.*ASC, DESC"):
            self.render_bar(parameters=parameters)

    def test_empty_datasource_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResourceError, "datasource_name"):
            self.render_bar(datasource_name="   ")

    def test_empty_worksheet_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResourceError, "worksheet_name"):
            self.render_bar(worksheet_name="")

    def test_template_token_in_a_mapped_value_is_rejected(self) -> None:
        mappings = dict(PULSE_BAR_MAPPINGS)
        mappings["ARR"] = "{{DATE_MIN}}"
        with self.assertRaisesRegex(ResourceError, "template token"):
            self.render_bar(field_mappings=mappings)


class EscapingTest(RenderSupportMixin):
    def test_worksheet_and_window_names_are_xml_escaped(self) -> None:
        name = "Q1 <ARR> & \"Top\" 'Offerings'"
        worksheet, window = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name=name,
            datasource_name="Sales Data",
            field_mappings=PULSE_BAR_MAPPINGS,
            parameters=PULSE_BAR_PARAMETERS,
        )
        self.assertIn("&lt;ARR&gt;", worksheet)
        self.assertIn("&amp;", worksheet)
        self.assertEqual(ET.fromstring(worksheet).get("name"), name)
        self.assertEqual(ET.fromstring(window).get("name"), name)

    def test_target_datasource_name_is_xml_escaped(self) -> None:
        worksheet, _ = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name="Escaped DS",
            datasource_name="Sales & Ops",
            field_mappings=PULSE_BAR_MAPPINGS,
            parameters=PULSE_BAR_PARAMETERS,
        )
        self.assertIn("[Sales &amp; Ops].[sum:Revenue:qk]", worksheet)
        rows = ET.fromstring(worksheet).find("table/rows")
        self.assertEqual(rows.text, "[Sales & Ops].[none:Offering:nk]")

    def test_target_field_name_uses_tableau_bracket_escaping(self) -> None:
        worksheet, _ = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name="Bracketed",
            datasource_name="Sales Data",
            field_mappings={
                "ARR": "Rev]enue",
                "Close Date": "Transaction Date",
                "Product": "Offering",
            },
            parameters=PULSE_BAR_PARAMETERS,
        )
        self.assertIn("[Sales Data].[sum:Rev]]enue:qk]", worksheet)
        self.assertIn("name='[Rev]]enue]'", worksheet)
        ET.fromstring(worksheet)

    def test_source_field_name_uses_tableau_bracket_unescaping(self) -> None:
        bookmark = SYNTHETIC_BOOKMARK.replace("Widget", "Widget]] Type")
        root = self.make_plugin_root("synthetic", bookmark)
        catalog_path = root / "resources/catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["resources"][0]["fields"][1]["sourceField"] = "Widget] Type"
        catalog_path.write_text(
            json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
        )

        worksheet, _ = render_bookmark(
            plugin_root=root,
            resource_id="synthetic",
            worksheet_name="Bracketed Source",
            datasource_name="Sales Data",
            field_mappings={"Widget] Type": "Offering", "Amount": "Revenue"},
            parameters={},
        )

        self.assertIn("[Sales Data].[none:Offering:nk]", worksheet)
        self.assertNotIn("Widget]] Type", worksheet)

    def test_identity_field_mapping_is_valid(self) -> None:
        worksheet, _ = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name="Identity",
            datasource_name="Sales Data",
            field_mappings={
                "ARR": "ARR",
                "Close Date": "Close Date",
                "Product": "Product",
            },
            parameters=PULSE_BAR_PARAMETERS,
        )
        self.assertIn("[Sales Data].[sum:ARR:qk]", worksheet)
        self.assertNotIn("Sample - Superstore", worksheet)

    def test_swapped_field_mappings_do_not_chain(self) -> None:
        worksheet, _ = self.render_synthetic(
            SYNTHETIC_BOOKMARK,
            field_mappings={"Widget": "Amount", "Amount": "Widget"},
        )
        self.assertIn("[Sales Data].[none:Amount:nk]", worksheet)
        self.assertIn("[Sales Data].[sum:Widget:qk]", worksheet)


class StructuralSafetyTest(RenderSupportMixin):
    def test_catalog_hash_drift_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResourceError, "does not match the catalog hash"):
            self.render_synthetic(SYNTHETIC_BOOKMARK, sha256="0" * 64)

    def test_root_level_cards_are_hoisted_into_the_window(self) -> None:
        _, window = self.render_synthetic(SYNTHETIC_BOOKMARK)
        window_root = ET.fromstring(window)
        self.assertEqual(
            [child.tag for child in window_root],
            ["cards", "viewpoint", "simple-id"],
        )
        self.assertIsNotNone(window_root.find("cards/edge"))

    def test_duplicate_root_level_cards_are_rejected(self) -> None:
        duplicate = SYNTHETIC_BOOKMARK.replace(
            "<window class='worksheet' name='synthetic'>",
            "<cards><edge name='right' /></cards>\n"
            "<window class='worksheet' name='synthetic'>",
        )
        with self.assertRaisesRegex(ResourceError, "more than one.*<cards>"):
            self.render_synthetic(duplicate)

    def test_existing_window_cards_are_not_duplicated(self) -> None:
        _, window = render_bookmark(
            plugin_root=PLUGIN,
            resource_id="insights__bar_chart",
            worksheet_name="Cards",
            datasource_name="Sales Data",
            field_mappings=PULSE_BAR_MAPPINGS,
            parameters=PULSE_BAR_PARAMETERS,
        )
        self.assertEqual(len(ET.fromstring(window).findall("cards")), 1)

    def test_self_closing_highlight_is_removed(self) -> None:
        collapsed = SYNTHETIC_BOOKMARK.replace(
            """    <highlight>
      <color-one-way>
        <field>[Donor DS].[none:Widget:nk]</field>
      </color-one-way>
    </highlight>
""",
            "    <highlight />\n",
        )
        self.assertIn("<highlight />", collapsed)
        _, window = self.render_synthetic(collapsed)
        self.assertNotIn("highlight", window)
        self.assertEqual(
            [child.tag for child in ET.fromstring(window)],
            ["cards", "viewpoint", "simple-id"],
        )

    def test_nested_highlights_are_removed_without_losing_siblings(self) -> None:
        nested = SYNTHETIC_BOOKMARK.replace(
            """    <highlight>
      <color-one-way>
        <field>[Donor DS].[none:Widget:nk]</field>
      </color-one-way>
    </highlight>
""",
            """    <highlight>
      <highlight />
    </highlight>
    <zoom type='entire-view' />
    <keep-me />
""",
        )
        _, window = self.render_synthetic(nested)
        viewpoint = ET.fromstring(window).find("viewpoint")
        self.assertEqual([child.tag for child in viewpoint], ["zoom", "keep-me"])
        self.assertEqual((viewpoint.text or "").strip(), "")

    def test_unreferenced_donor_columns_are_removed(self) -> None:
        extra_column = SYNTHETIC_BOOKMARK.replace(
            "<column datatype='real' name='[Amount]'",
            "<column datatype='string' name='[Unused Donor Field]' "
            "role='dimension' type='nominal' />\n"
            "        <column datatype='real' name='[Amount]'",
        )
        worksheet, _ = self.render_synthetic(extra_column)
        self.assertNotIn("Unused Donor Field", worksheet)

    def test_unreferenced_donor_columns_are_not_mappable(self) -> None:
        extra_column = SYNTHETIC_BOOKMARK.replace(
            "<column datatype='real' name='[Amount]'",
            "<column datatype='string' name='[Unused Donor Field]' "
            "role='dimension' type='nominal' />\n"
            "        <column datatype='real' name='[Amount]'",
        )
        with self.assertRaisesRegex(
            ResourceError, "Unknown field mappings: Unused Donor Field"
        ):
            self.render_synthetic(
                extra_column,
                field_mappings={
                    "Widget": "Offering",
                    "Amount": "Revenue",
                    "Unused Donor Field": "Offering",
                },
            )

    def test_noncanonical_donor_escaping_is_rewritten(self) -> None:
        quoted_donor = SYNTHETIC_BOOKMARK.replace("Donor DS", 'Donor "DS"')
        root = self.make_plugin_root("synthetic", quoted_donor)
        catalog_path = root / "resources/catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        entry = catalog["resources"][0]
        entry["datasources"] = ['Donor "DS"']
        for field in entry["fields"]:
            field["datasource"] = 'Donor "DS"'
        catalog_path.write_text(
            json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
        )

        worksheet, _ = render_bookmark(
            plugin_root=root,
            resource_id="synthetic",
            worksheet_name="Quoted Donor",
            datasource_name="Sales Data",
            field_mappings={"Widget": "Offering", "Amount": "Revenue"},
            parameters={},
        )

        self.assertNotIn('Donor "DS"', worksheet)
        self.assertIn("[Sales Data].[none:Offering:nk]", worksheet)

    def test_two_tables_are_rejected(self) -> None:
        broken = SYNTHETIC_BOOKMARK.replace("</bookmark>", "<table />\n</bookmark>")
        with self.assertRaisesRegex(ResourceError, "exactly one <window> and one <table>"):
            self.render_synthetic(broken)

    def test_unresolvable_donor_reference_is_rejected(self) -> None:
        broken = SYNTHETIC_BOOKMARK.replace(
            "<aggregation value='true' />",
            "<filter class='categorical' column='[Donor DS].[Mystery]' />",
        )
        with self.assertRaisesRegex(ResourceError, "unresolved donor field reference"):
            self.render_synthetic(broken)

    def test_residual_donor_datasource_text_is_rejected(self) -> None:
        broken = SYNTHETIC_BOOKMARK.replace(
            "<style />",
            "<style><style-rule element='worksheet'>"
            "<format attr='title' value='Donor DS' /></style-rule></style>",
        )
        with self.assertRaisesRegex(ResourceError, "still references the donor"):
            self.render_synthetic(broken)

    def test_a_target_caption_equal_to_the_donor_is_allowed(self) -> None:
        """A target may legitimately be captioned after the donor itself.

        The caption is display text, not an address, so it is not residue.
        """
        worksheet, _ = self.render_synthetic(
            SYNTHETIC_BOOKMARK, datasource_caption="Donor DS"
        )
        self.assertIn("caption='Donor DS'", worksheet)
        self.assertIn("name='Sales Data'", worksheet)
        self.assertIn("[Sales Data].[none:Offering:nk]", worksheet)

    def test_a_target_caption_containing_the_donor_is_allowed(self) -> None:
        worksheet, _ = self.render_synthetic(
            SYNTHETIC_BOOKMARK, datasource_caption="Donor DS Rollup (EMEA)"
        )
        self.assertIn("caption='Donor DS Rollup (EMEA)'", worksheet)
        self.assertIn("[Sales Data].[sum:Revenue:qk]", worksheet)

    def test_donor_text_elsewhere_is_rejected_even_with_a_matching_caption(
        self,
    ) -> None:
        """Exempting the caption must not exempt donor text anywhere else."""
        broken = SYNTHETIC_BOOKMARK.replace(
            "<style />",
            "<style><style-rule element='worksheet'>"
            "<format attr='title' value='Donor DS' /></style-rule></style>",
        )
        with self.assertRaisesRegex(ResourceError, "still references the donor"):
            self.render_synthetic(broken, datasource_caption="Donor DS")

    def test_a_donor_caption_on_another_element_is_still_rejected(self) -> None:
        """Only a caption holding the target's own label is exempt."""
        broken = SYNTHETIC_BOOKMARK.replace(
            "<mark class='Bar' />",
            "<mark caption='Donor DS Legend' class='Bar' />",
        )
        with self.assertRaisesRegex(ResourceError, "still references the donor"):
            self.render_synthetic(broken, datasource_caption="Donor DS")

    def test_duplicate_simple_id_in_one_fragment_is_rejected(self) -> None:
        broken = SYNTHETIC_BOOKMARK.replace(
            "<simple-id uuid='{00000000-0000-0000-0000-000000000002}' />",
            "<simple-id uuid='{00000000-0000-0000-0000-000000000002}' />\n"
            "  <simple-id uuid='{00000000-0000-0000-0000-000000000003}' />",
        )
        with self.assertRaisesRegex(ResourceError, "more than one <simple-id>"):
            self.render_synthetic(broken)

    def test_unreplaced_template_token_is_rejected(self) -> None:
        broken = SYNTHETIC_BOOKMARK.replace(
            "<aggregation value='true' />",
            "<aggregation value='{{UNDECLARED_TOKEN}}' />",
        )
        with self.assertRaisesRegex(ResourceError, "unresolved template token"):
            self.render_synthetic(broken)

    def test_federated_placeholder_is_rejected(self) -> None:
        broken = SYNTHETIC_BOOKMARK.replace(
            "<aggregation value='true' />",
            "<aggregation value='federated.0x1y2z' />",
        )
        with self.assertRaisesRegex(ResourceError, "federated"):
            self.render_synthetic(broken)

    def test_federated_target_datasource_is_accepted(self) -> None:
        worksheet, window = self.render_synthetic(
            SYNTHETIC_BOOKMARK, datasource_name="federated.0abc123def"
        )
        self.assertIn("[federated.0abc123def].[none:Offering:nk]", worksheet)
        self.assertNotIn("Donor DS", worksheet + window)

    def test_foreign_federated_reference_is_rejected_for_a_federated_target(
        self,
    ) -> None:
        broken = SYNTHETIC_BOOKMARK.replace(
            "<aggregation value='true' />",
            "<aggregation value='federated.0x1y2z' />",
        )
        with self.assertRaisesRegex(ResourceError, "federated.0x1y2z"):
            self.render_synthetic(broken, datasource_name="federated.0abc123def")


class DonorMetadataReferenceTest(unittest.TestCase):
    """Fix round 1, finding 1: unqualified donor metadata must not survive.

    Six executable templates carry ``aggregate-role-from='[State/Province]'``,
    a donor column named without a datasource qualifier. It must be mappable,
    and dropped rather than emitted when the caller omits it.
    """

    affected = (
        "change-over-time-area-chart",
        "change-over-time-stacked-area-chart",
        "magnitude-paired-bar",
        "magnitude-paired-column-chart",
        "part-to-whole-pie-chart",
        "part-to-whole-stacked-bar-chart",
    )
    primary = "magnitude-paired-bar"
    primary_mappings = {
        "Customer Name": "Offering",
        "Order Date": "Transaction Date",
        "Profit": "Revenue",
    }

    def render(
        self,
        resource_id: str,
        mappings: dict[str, str] | None = None,
        **extra: str,
    ) -> tuple[str, str]:
        entry = next(
            item
            for item in load_catalog(PLUGIN)["resources"]
            if item["id"] == resource_id
        )
        mapped = dict(
            mappings
            if mappings is not None
            else {
                field["sourceField"]: field["sourceField"]
                for field in entry["fields"]
            }
        )
        mapped.update(extra)
        return render_bookmark(
            plugin_root=PLUGIN,
            resource_id=resource_id,
            worksheet_name=f"Sheet {resource_id}",
            datasource_name="Sales Data",
            field_mappings=mapped,
            parameters={},
        )

    def test_metadata_only_field_accepts_a_mapping_and_is_rewritten(self) -> None:
        worksheet, window = self.render(
            self.primary, self.primary_mappings, **{"State/Province": "Offering"}
        )
        self.assertIn("aggregate-role-from='[Offering]'", worksheet)
        self.assertNotIn("State/Province", worksheet + window)

    def test_omitted_metadata_field_drops_the_donor_only_attribute(self) -> None:
        worksheet, window = self.render(self.primary, self.primary_mappings)
        self.assertNotIn("aggregate-role-from", worksheet + window)
        self.assertNotIn("State/Province", worksheet + window)
        # The column that carried the metadata survives, with its own mapping.
        self.assertIn("name='[Offering]'", worksheet)

    def test_every_affected_template_renders_without_the_donor_field(self) -> None:
        for resource_id in self.affected:
            with self.subTest(resource=resource_id):
                worksheet, window = self.render(resource_id)
                self.assertNotIn("State/Province", worksheet + window)
                self.assertNotIn("aggregate-role-from", worksheet + window)
                mapped, _ = self.render(resource_id, **{"State/Province": "Offering"})
                self.assertIn("aggregate-role-from='[Offering]'", mapped)


class SyntheticDonorMetadataTest(RenderSupportMixin):
    """Metadata-reference discovery, stripping, and its fail-closed backstop."""

    def with_metadata(self, value: str = "[Region]") -> str:
        return SYNTHETIC_BOOKMARK.replace(
            "<column datatype='string' name='[Widget]'",
            f"<column aggregate-role-from='{value}' datatype='string' name='[Widget]'",
        )

    def test_metadata_reference_is_stripped_when_unmapped(self) -> None:
        worksheet, _ = self.render_synthetic(self.with_metadata())
        self.assertNotIn("aggregate-role-from", worksheet)
        self.assertNotIn("Region", worksheet)
        self.assertIn("<column datatype='string' name='[Offering]'", worksheet)

    def test_metadata_reference_is_rewritten_when_mapped(self) -> None:
        worksheet, _ = self.render_synthetic(
            self.with_metadata(),
            field_mappings={
                "Widget": "Offering",
                "Amount": "Revenue",
                "Region": "Transaction Date",
            },
        )
        self.assertIn("aggregate-role-from='[Transaction Date]'", worksheet)
        self.assertNotIn("Region", worksheet)

    def test_unmapped_metadata_field_used_elsewhere_fails_closed(self) -> None:
        # The attribute is stripped, but the same unqualified reference also
        # appears in a sort, where nothing can safely rewrite it.
        broken = self.with_metadata().replace(
            "<aggregation value='true' />",
            "<aggregation value='true' />\n      <sort-order field='[Region]' />",
        )
        with self.assertRaisesRegex(
            ResourceError, r"still references the unmapped donor field \[Region\]"
        ):
            self.render_synthetic(broken)

    def test_metadata_attribute_that_is_not_a_field_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ResourceError, "not a single field reference: Region"
        ):
            self.render_synthetic(self.with_metadata("Region"))


class CatalogParameterContractTest(RenderSupportMixin):
    """Fix round 1, finding 2: contracts come from the catalog, or not at all."""

    bookmark = SYNTHETIC_BOOKMARK.replace(
        "<aggregation value='true' />",
        "<aggregation value='true' />\n"
        "      <filter class='quantitative' column='[Donor DS].[sum:Amount:qk]'>"
        "<min>#{{THRESHOLD}}#</min></filter>",
    )

    def test_declared_parameter_without_a_type_fails_closed(self) -> None:
        with self.assertRaisesRegex(ResourceError, "has no typed contract"):
            self.render_synthetic(
                self.bookmark,
                catalog_parameters=[{"name": "THRESHOLD"}],
                parameters={"THRESHOLD": "5"},
            )

    def test_name_only_catalog_parameter_fails_closed(self) -> None:
        with self.assertRaisesRegex(ResourceError, "without a typed contract"):
            self.render_synthetic(
                self.bookmark,
                catalog_parameters=["THRESHOLD"],
                parameters={"THRESHOLD": "5"},
            )

    def test_enum_contract_without_allowed_values_fails_closed(self) -> None:
        with self.assertRaisesRegex(ResourceError, "declares no allowed values"):
            self.render_synthetic(
                self.bookmark,
                catalog_parameters=[{"name": "THRESHOLD", "type": "enum"}],
                parameters={"THRESHOLD": "5"},
            )

    def test_catalog_contract_is_enforced_without_an_overrides_file(self) -> None:
        contract = [{"name": "THRESHOLD", "type": "number", "required": True}]
        with self.assertRaisesRegex(ResourceError, "must be a number"):
            self.render_synthetic(
                self.bookmark,
                catalog_parameters=contract,
                parameters={"THRESHOLD": "not-a-number"},
            )
        worksheet, _ = self.render_synthetic(
            self.bookmark, catalog_parameters=contract, parameters={"THRESHOLD": "5"}
        )
        self.assertIn("<min>#5#</min>", worksheet)


class ExecutableCoverageTest(unittest.TestCase):
    """Every executable template must render with an identity mapping."""

    @staticmethod
    def parameter_values(contracts: list[dict[str, object]]) -> dict[str, str]:
        """Build one valid value per declared parameter, from the catalog alone."""
        values: dict[str, str] = {}
        for contract in contracts:
            kind = contract["type"]
            if kind == "date":
                values[contract["name"]] = "2026-01-01"
            elif kind == "enum":
                values[contract["name"]] = contract["allowed"][0]
            else:
                values[contract["name"]] = "1"
        return values

    def test_every_executable_template_renders(self) -> None:
        catalog = load_catalog(PLUGIN)
        executable = [
            entry
            for entry in catalog["resources"]
            if entry["tier"] == "executable" and entry["type"] == "template"
        ]
        self.assertEqual(len(executable), 24)
        for entry in executable:
            resource_id = entry["id"]
            with self.subTest(resource=resource_id):
                mappings = {
                    field["sourceField"]: field["sourceField"]
                    for field in entry["fields"]
                }
                worksheet, window = render_bookmark(
                    plugin_root=PLUGIN,
                    resource_id=resource_id,
                    worksheet_name=f"Sheet {resource_id}",
                    datasource_name="Sales Data",
                    field_mappings=mappings,
                    parameters=self.parameter_values(entry["parameters"]),
                )
                combined = worksheet + window
                for donor in entry["datasources"]:
                    self.assertNotIn(donor, combined)
                self.assertNotIn("{{", combined)
                self.assertNotIn("<highlight", combined)
                worksheet_root = parse_fragment(worksheet)
                window_root = parse_fragment(window)
                self.assertEqual(worksheet_root.tag, "worksheet")
                self.assertEqual(worksheet_root.get("name"), f"Sheet {resource_id}")
                self.assertEqual([c.tag for c in worksheet_root], ["table"])
                self.assertEqual(window_root.tag, "window")
                self.assertEqual(window_root.get("class"), "worksheet")
                self.assertEqual(window_root.get("name"), f"Sheet {resource_id}")
                self.assertIsNotNone(window_root.find("cards"))


class GoldenOutputTest(unittest.TestCase):
    """Golden fragments for both Pulse templates and a portable bar template."""

    cases = {
        "insights__bar_chart": {
            "worksheet_name": "ARR by Offering",
            "field_mappings": PULSE_BAR_MAPPINGS,
            "parameters": PULSE_BAR_PARAMETERS,
        },
        "insights__line_chart": {
            "worksheet_name": "ARR Trend",
            "field_mappings": {"ARR": "Revenue", "Close Date": "Transaction Date"},
            "parameters": {},
        },
        "magnitude-simple-bar": {
            "worksheet_name": "Revenue by Offering",
            "field_mappings": {
                "Customer Name": "Offering",
                "Profit": "Revenue",
            },
            "parameters": {},
        },
    }

    def test_target_datasource_fixture_declares_every_mapping_target(self) -> None:
        datasource = ET.parse(FIXTURES / "target-datasource.xml").getroot()
        self.assertEqual(datasource.tag, "datasource")
        self.assertEqual(datasource.get("name"), "Sales Data")
        available = {
            column.get("name").strip("[]") for column in datasource.iter("column")
        }
        for case in self.cases.values():
            for target in case["field_mappings"].values():
                self.assertIn(target, available)

    def test_golden_fragments_match(self) -> None:
        for resource_id, case in self.cases.items():
            with self.subTest(resource=resource_id):
                worksheet, window = render_bookmark(
                    plugin_root=PLUGIN,
                    resource_id=resource_id,
                    worksheet_name=case["worksheet_name"],
                    datasource_name="Sales Data",
                    field_mappings=case["field_mappings"],
                    parameters=case["parameters"],
                )
                expected_worksheet = (
                    GOLDEN / f"{resource_id}.worksheet.xml"
                ).read_text(encoding="utf-8")
                expected_window = (GOLDEN / f"{resource_id}.window.xml").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(worksheet + "\n", expected_worksheet)
                self.assertEqual(window + "\n", expected_window)


class UnsafeOutputCheckTest(unittest.TestCase):
    """Pins the donor checks a caption exemption is not allowed to weaken.

    Two of them — a donor-addressing ``name``/``datasource`` attribute and a
    donor qualified reference — cannot be produced through the public render
    path, which rewrites both before the check runs, so they are exercised
    against the check itself.
    """

    def reject(self, fragment: str, *, target_caption: str | None = None) -> None:
        _reject_unsafe_output(
            {"worksheet": fragment},
            donor="Donor DS",
            target_datasource="Sales Data",
            raw_to_logical={},
            field_mappings={},
            target_caption=target_caption,
        )

    def test_a_caption_holding_the_target_label_is_allowed(self) -> None:
        self.reject(
            "<datasource caption='Donor DS' name='Sales Data' />",
            target_caption="Donor DS",
        )

    def test_a_donor_addressing_name_attribute_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResourceError, "still references the donor"):
            self.reject(
                "<datasource caption='Donor DS' name='Donor DS' />",
                target_caption="Donor DS",
            )

    def test_a_donor_addressing_datasource_attribute_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResourceError, "still references the donor"):
            self.reject(
                "<datasource-dependencies caption='Donor DS' "
                "datasource='Donor DS' />",
                target_caption="Donor DS",
            )

    def test_a_donor_qualified_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResourceError, "still references the donor"):
            self.reject(
                "<view caption='Donor DS'>"
                "<rows>[Donor DS].[none:Widget:nk]</rows></view>",
                target_caption="Donor DS",
            )

    def test_an_unexempted_caption_is_rejected(self) -> None:
        """With no target caption supplied, nothing is exempt."""
        with self.assertRaisesRegex(ResourceError, "still references the donor"):
            self.reject("<datasource caption='Donor DS' name='Sales Data' />")

    def test_an_unresolved_template_token_is_still_rejected(self) -> None:
        with self.assertRaisesRegex(ResourceError, "unresolved template token"):
            self.reject(
                "<datasource caption='Donor DS' name='{{DS}}' />",
                target_caption="Donor DS",
            )

    def test_a_foreign_federated_datasource_is_still_rejected(self) -> None:
        with self.assertRaisesRegex(ResourceError, "federated datasource"):
            self.reject(
                "<datasource caption='Donor DS' name='federated.0other' />",
                target_caption="Donor DS",
            )

    def test_a_stale_donor_field_is_still_rejected(self) -> None:
        with self.assertRaisesRegex(ResourceError, "unmapped donor field"):
            _reject_unsafe_output(
                {"worksheet": "<view caption='Donor DS'><rows>[Widget]</rows></view>"},
                donor="Donor DS",
                target_datasource="Sales Data",
                raw_to_logical={"Widget": "Widget"},
                field_mappings={},
                target_caption="Donor DS",
            )


if __name__ == "__main__":
    unittest.main()

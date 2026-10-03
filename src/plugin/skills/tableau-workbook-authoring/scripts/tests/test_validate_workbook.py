import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1]
sys.path.insert(0, str(SCRIPTS))

import tableau_resources
from validate_workbook import _default_schemas_dir, validate_workbook

DS = "sqlproxy.test"
LEGACY_SORT = (
    f"<sort class='computed' column='[{DS}].[none:Artist:nk]' direction='DESC' "
    f"using='[{DS}].[sum:Weeks:qk]' />"
)
COMPUTED_SORT = (
    f"<computed-sort column='[{DS}].[none:Artist:nk]' direction='DESC' "
    f"using='[{DS}].[sum:Weeks:qk]' />"
)


def workbook(
    *,
    sort=LEGACY_SORT,
    manifest="<WindowsPersistSimpleIdentifiers />",
    dashboard_datasources="<datasources />",
    zone_sheet="Top Artists",
    action_sheet="Top Artists",
    shelf_field="sum:Weeks:qk",
    shelf_datasource=DS,
    simple_id="",
    source_build="2025.1.0 (20251.25.0313.2002)",
):
    """A small workbook shaped like an unedited Tableau Cloud download: a
    measure sort, a dashboard, and a filter action."""
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<!-- build 20263.26.0930.1502                               -->
<workbook original-version='18.1' source-build='{source_build}' source-platform='mac' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <document-format-change-manifest>
    {manifest}
  </document-format-change-manifest>
  <preferences />
  <datasources>
    <datasource caption='Test' inline='true' name='{DS}' version='18.1'>
      <connection class='sqlproxy' dbname='test' port='443' server='example.com' />
      <column datatype='string' name='[Artist]' role='dimension' type='nominal' />
      <column datatype='integer' name='[Weeks]' role='measure' type='quantitative' />
    </datasource>
  </datasources>
  <actions>
    <action caption='Filter' name='[Action1]'>
      <activation auto-clear='true' type='on-select' />
      <source dashboard='Dash' type='sheet' worksheet='{action_sheet}' />
      <command command='tsc:tsl-filter'>
        <param name='special-fields' value='all' />
        <param name='target' value='Dash' />
      </command>
    </action>
  </actions>
  <worksheets>
    <worksheet name='Top Artists'>
      <table>
        <view>
          <datasources>
            <datasource caption='Test' name='{DS}' />
          </datasources>
          <datasource-dependencies datasource='{DS}'>
            <column datatype='string' name='[Artist]' role='dimension' type='nominal' />
            <column datatype='integer' name='[Weeks]' role='measure' type='quantitative' />
            <column-instance column='[Artist]' derivation='None' name='[none:Artist:nk]' pivot='key' type='nominal' />
            <column-instance column='[Weeks]' derivation='Sum' name='[sum:Weeks:qk]' pivot='key' type='quantitative' />
          </datasource-dependencies>
          {sort}
          <aggregation value='true' />
        </view>
        <style />
        <panes>
          <pane selection-relaxation-option='selection-relaxation-allow'>
            <view>
              <breakdown value='auto' />
            </view>
            <mark class='Bar' />
          </pane>
        </panes>
        <rows>[{DS}].[none:Artist:nk]</rows>
        <cols>[{shelf_datasource}].[{shelf_field}]</cols>
      </table>
      {simple_id}
    </worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='Dash'>
      <style />
      <size maxheight='800' maxwidth='1000' minheight='800' minwidth='1000' sizing-mode='fixed' />
      {dashboard_datasources}
      <zones>
        <zone h='100000' id='2' type-v2='layout-basic' w='100000' x='0' y='0'>
          <zone h='100000' id='3' name='{zone_sheet}' w='100000' x='0' y='0' />
        </zone>
      </zones>
    </dashboard>
  </dashboards>
  <windows>
    <window class='worksheet' name='Top Artists'>
      <cards />
    </window>
    <window class='dashboard' maximized='true' name='Dash'>
      <viewpoints>
        <viewpoint name='Top Artists' />
      </viewpoints>
      <active id='-1' />
    </window>
  </windows>
</workbook>
"""


class ValidateWorkbookTests(unittest.TestCase):
    def validate(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "wb.twb")
            Path(path).write_text(text, encoding="utf-8")
            return validate_workbook(path, _default_schemas_dir())

    def messages(self, result):
        return [issue.message for issue in result.issues]

    def assertInvalidWith(self, text, fragment):
        result = self.validate(text)
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any(fragment in message for message in self.messages(result)),
            self.messages(result),
        )

    def test_cloud_download_shape_is_valid(self):
        # Regression: an unedited Tableau Cloud download (legacy sorts, no
        # simple-id, no SortTagCleanup) must pass with no warnings telling the
        # agent to change it.
        result = self.validate(workbook())
        self.assertTrue(result.is_valid, self.messages(result))
        self.assertEqual(result.warnings, [])

    def test_computed_sort_without_sort_tag_cleanup_is_rejected(self):
        self.assertInvalidWith(workbook(sort=COMPUTED_SORT), "<sort class='computed'")

    def test_computed_sort_with_sort_tag_cleanup_is_valid(self):
        result = self.validate(
            workbook(sort=COMPUTED_SORT, manifest="<SortTagCleanup />")
        )
        self.assertTrue(result.is_valid, self.messages(result))

    def test_legacy_sort_with_sort_tag_cleanup_is_rejected(self):
        self.assertInvalidWith(workbook(manifest="<SortTagCleanup />"), "'sort'")

    def test_simple_id_present_warns(self):
        result = self.validate(
            workbook(simple_id="<simple-id uuid='{00000000-0000-0000-0000-000000000001}' />")
        )
        self.assertTrue(result.is_valid, self.messages(result))
        self.assertTrue(any("simple-id" in w.message for w in result.warnings))

    def test_dashboard_without_datasources_is_rejected(self):
        self.assertInvalidWith(
            workbook(dashboard_datasources=""), "dashboard-missing-datasources: Dash"
        )

    def test_zone_naming_missing_sheet_is_rejected(self):
        self.assertInvalidWith(workbook(zone_sheet="Nope"), "unknown-zone-sheet: Nope")

    def test_action_source_missing_sheet_is_rejected(self):
        self.assertInvalidWith(
            workbook(action_sheet="Nope"), "unknown-action-source-sheet: Nope"
        )

    def test_unknown_field_is_rejected(self):
        self.assertInvalidWith(
            workbook(shelf_field="sum:Nope:qk"), "unknown-field-reference"
        )

    def test_unknown_datasource_is_rejected(self):
        self.assertInvalidWith(
            workbook(shelf_datasource="sqlproxy.nope"), "unknown-datasource-reference"
        )

    def test_malformed_xml_is_fatal(self):
        result = self.validate(workbook().replace("</worksheets>", ""))
        self.assertFalse(result.is_valid)
        self.assertEqual([i.level for i in result.issues], ["fatal"])

    def test_placeholder_source_build_falls_back_to_build_comment(self):
        # A non-numeric source-build (the old starter's) must not drop the
        # workbook to the 2018.1 schema via the frozen `version` attribute.
        result = self.validate(workbook(source_build="plugin"))
        self.assertEqual(result.version, "26.3")


class MatchTargetConventionsTests(unittest.TestCase):
    FRAGMENT = (
        "<worksheet name='X'><table><view>"
        f"{COMPUTED_SORT}"
        "<manual-sort column='[a]' direction='ASC'><dictionary /></manual-sort>"
        "</view></table>\n"
        "<simple-id uuid='{00000000-0000-0000-0000-000000000001}' />\n"
        "</worksheet>"
    )

    def test_legacy_target_gets_legacy_sorts_and_no_simple_id(self):
        out = tableau_resources.match_target_conventions(workbook(), self.FRAGMENT)
        self.assertIn("<sort class='computed' column=", out)
        self.assertIn("<sort class='manual' column='[a]' direction='ASC'><dictionary /></sort>", out)
        self.assertNotIn("-sort", out)
        self.assertNotIn("simple-id", out)

    def test_modern_target_keeps_newer_forms(self):
        target = workbook(
            sort=COMPUTED_SORT,
            manifest="<SortTagCleanup />",
            simple_id="<simple-id uuid='{00000000-0000-0000-0000-000000000002}' />",
        )
        out = tableau_resources.match_target_conventions(target, self.FRAGMENT)
        self.assertEqual(out, self.FRAGMENT)

    def test_starter_has_numeric_source_build(self):
        starter = (
            tableau_resources.PLUGIN_ROOT / "resources" / tableau_resources.STARTER_RELATIVE_PATH
        ).read_text(encoding="utf-8")
        self.assertRegex(starter, r"source-build='20\d\d\.\d")


if __name__ == "__main__":
    unittest.main()

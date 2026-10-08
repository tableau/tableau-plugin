import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from tableau_resources import validate_workbook_text

try:
    from validate_workbook import reference_issues
except SystemExit:  # validate_workbook exits when lxml is missing
    reference_issues = None


def workbook(zones="", actions="", rows="[ds].[none:Region:nk]"):
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources>
    <datasource name='ds'><column name='[Region]' datatype='string' role='dimension' type='nominal' /></datasource>
  </datasources>
  <worksheets>
    <worksheet name='Map'><table><rows>{rows}</rows></table></worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='Overview'><zones><zone id='1' type-v2='layout-basic'>{zones}</zone></zones></dashboard>
  </dashboards>
  <windows>
    <window class='worksheet' name='Map' />
    <window class='dashboard' name='Overview' />
  </windows>
  {actions}
</workbook>"""


def action(source):
    return f"<actions><action caption='Filter' name='[Action1]'>{source}</action></actions>"


class ZoneChecks(unittest.TestCase):
    def test_zone_naming_real_worksheet_passes(self):
        self.assertEqual(validate_workbook_text(workbook("<zone id='2' name='Map' />")), [])

    def test_zone_naming_missing_worksheet_fails(self):
        errors = validate_workbook_text(workbook("<zone id='2' name='Mpa' />"))
        self.assertEqual(errors, ["unknown-zone-worksheet: Overview/Mpa"])

    def test_legend_zone_naming_missing_worksheet_fails(self):
        errors = validate_workbook_text(workbook("<zone id='2' name='Gone' type-v2='color' />"))
        self.assertEqual(errors, ["unknown-zone-worksheet: Overview/Gone"])

    def test_named_text_zone_is_not_a_sheet_reference(self):
        self.assertEqual(
            validate_workbook_text(workbook("<zone id='2' name='Title' type-v2='text' />")), []
        )


class ActionChecks(unittest.TestCase):
    def test_action_from_real_sheet_passes(self):
        text = workbook(actions=action("<source dashboard='Overview' type='sheet' worksheet='Map' />"))
        self.assertEqual(validate_workbook_text(text), [])

    def test_action_from_missing_worksheet_fails(self):
        text = workbook(actions=action("<source dashboard='Overview' type='sheet' worksheet='Gone' />"))
        self.assertEqual(validate_workbook_text(text), ["unknown-action-source: Filter/Gone"])

    def test_action_from_missing_dashboard_fails(self):
        text = workbook(actions=action("<source dashboard='Gone' type='sheet' worksheet='Map' />"))
        self.assertEqual(validate_workbook_text(text), ["unknown-action-source: Filter/Gone"])

    def test_stale_exclude_sheet_is_tolerated(self):
        source = "<source datasource='ds' type='datasource'><exclude-sheet name='Deleted' /></source>"
        self.assertEqual(validate_workbook_text(workbook(actions=action(source))), [])


@unittest.skipIf(reference_issues is None, "validate_workbook needs lxml")
class BaselineChecks(unittest.TestCase):
    broken = workbook("<zone id='2' name='Gone' />").encode()
    clean = workbook().encode()

    def test_without_baseline_reference_problems_are_warnings(self):
        issues = reference_issues(self.broken)
        self.assertEqual([i.level for i in issues], ["warning"])

    def test_problem_introduced_by_edit_is_an_error(self):
        issues = reference_issues(self.broken, baseline_bytes=self.clean)
        self.assertEqual(
            [(i.level, i.message) for i in issues],
            [("error", "reference check: unknown-zone-worksheet: Overview/Gone")],
        )

    def test_problem_inherited_from_baseline_is_dropped(self):
        self.assertEqual(reference_issues(self.broken, baseline_bytes=self.broken), [])

    def test_unknown_field_introduced_by_edit_is_an_error(self):
        edited = workbook(rows="[ds].[none:Regoin:nk]").encode()
        issues = reference_issues(edited, baseline_bytes=self.clean)
        self.assertEqual(
            [i.message for i in issues],
            ["reference check: unknown-field-reference: ds.Regoin"],
        )


if __name__ == "__main__":
    unittest.main()

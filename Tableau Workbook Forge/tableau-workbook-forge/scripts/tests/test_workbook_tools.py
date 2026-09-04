import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from workbook_tools import (
    apply_edit_plan,
    diff_workbooks,
    package,
    replace_run_color,
    safe_extract,
    validate,
    validate_package,
    workbook_inventory,
)


VALID_TWB = """<?xml version='1.0' encoding='utf-8'?>
<workbook><actions/><worksheets><worksheet name='Sheet 1'><run fontcolor='#000000'>Text</run></worksheet></worksheets></workbook>
"""

RICH_TWB = """<?xml version='1.0' encoding='utf-8'?>
<workbook source-build='2025.1'>
  <datasources><datasource name='ds.1' caption='Sales'/></datasources>
  <actions/>
  <worksheets>
    <worksheet name='Sheet 1'><run fontcolor='#000000' fontname='Arial'>Text</run></worksheet>
    <worksheet name='Sheet 2'><run fontcolor='#333333'>Other</run></worksheet>
  </worksheets>
  <dashboards><dashboard name='Overview'><zones><zone id='1' type-v2='worksheet' name='Sheet 1' x='0' y='0' w='400' h='300'/></zones></dashboard></dashboards>
  <windows><window class='worksheet' name='Sheet 1'/></windows>
</workbook>
"""


class WorkbookToolsTests(unittest.TestCase):
    def test_validate_and_replace_color(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(VALID_TWB, encoding="utf-8")
            self.assertTrue(validate(str(twb))["ok"])
            self.assertEqual(replace_run_color(str(twb), "#000000", "#E6E6E6"), 1)
            self.assertIn("#E6E6E6", twb.read_text(encoding="utf-8"))

    def test_validate_rejects_forbidden_format(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text("<workbook><worksheets/><format attr='font-color'/></workbook>", encoding="utf-8")
            self.assertFalse(validate(str(twb))["ok"])

    def test_extract_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory, "unsafe.twbx")
            with zipfile.ZipFile(archive, "w") as package_file:
                package_file.writestr("../escape.twb", VALID_TWB)
            with self.assertRaisesRegex(ValueError, "unsafe archive member"):
                safe_extract(str(archive), str(Path(directory, "run")))

    def test_extract_and_deterministic_package(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory, "input.twbx")
            with zipfile.ZipFile(archive, "w") as package_file:
                package_file.writestr("Workbook/book.twb", VALID_TWB)
                package_file.writestr("Data/data.txt", "preserve me")
            result = safe_extract(str(archive), str(Path(directory, "run")))
            output = Path(directory, "output.twbx")
            package(result["extracted_dir"], result["working_twb"], result["original_member"], str(output))
            with zipfile.ZipFile(output) as package_file:
                self.assertEqual(package_file.read("Data/data.txt"), b"preserve me")
                self.assertIn(b"worksheets", package_file.read("Workbook/book.twb"))

    def test_package_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "extracted")
            root.mkdir()
            member = root / "book.twb"
            member.write_text(VALID_TWB, encoding="utf-8")
            edited = Path(directory, "edited.twb")
            edited.write_text(VALID_TWB, encoding="utf-8")
            output = Path(directory, "existing.twbx")
            output.write_bytes(b"keep")
            with self.assertRaisesRegex(FileExistsError, "output already exists"):
                package(str(root), str(edited), "book.twb", str(output))
            self.assertEqual(output.read_bytes(), b"keep")

    def test_inventory_reports_structure_and_styles(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(RICH_TWB, encoding="utf-8")
            inventory = workbook_inventory(str(twb))
            self.assertEqual([item["name"] for item in inventory["worksheets"]], ["Sheet 1", "Sheet 2"])
            self.assertEqual(inventory["dashboards"][0]["zone_count"], 1)
            self.assertEqual(inventory["datasources"], ["Sales"])
            self.assertEqual(inventory["fonts"], {"Arial": 1})
            self.assertEqual(inventory["colors"]["#000000"], 1)

    def test_validate_rejects_duplicate_worksheet_names(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(
                "<workbook><worksheets><worksheet name='A'/><worksheet name='A'/></worksheets></workbook>",
                encoding="utf-8",
            )
            result = validate(str(twb))
            self.assertFalse(result["ok"])
            self.assertFalse(next(check for check in result["checks"] if check["id"] == "worksheet-names")["ok"])

    def test_validate_rejects_dangling_worksheet_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(
                "<workbook><worksheets><worksheet name='A'/></worksheets><dashboards><dashboard name='D'><zone id='1' type-v2='worksheet' name='Missing'/></dashboard></dashboards></workbook>",
                encoding="utf-8",
            )
            self.assertFalse(validate(str(twb))["ok"])

    def test_validate_rejects_duplicate_dashboard_zone_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(
                "<workbook><worksheets><worksheet name='A'/></worksheets><dashboards><dashboard name='D'><zone id='1'/><zone id='1'/></dashboard></dashboards></workbook>",
                encoding="utf-8",
            )
            self.assertFalse(validate(str(twb))["ok"])

    def test_apply_plan_dry_run_and_scoped_style(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(RICH_TWB, encoding="utf-8")
            original = twb.read_bytes()
            plan = Path(directory, "plan.json")
            plan.write_text(json.dumps({
                "version": "1.0",
                "operations": [{
                    "op": "replace_run_style",
                    "worksheet": "Sheet 1",
                    "match": {"fontcolor": "#000000"},
                    "set": {"fontcolor": "#17365D", "fontname": "Tableau Book"},
                    "expected": 1,
                }],
            }), encoding="utf-8")
            preview = apply_edit_plan(str(twb), str(plan), dry_run=True)
            self.assertTrue(preview["ok"])
            self.assertEqual(twb.read_bytes(), original)
            applied = apply_edit_plan(str(twb), str(plan))
            self.assertTrue(applied["ok"])
            self.assertIn("#17365D", twb.read_text(encoding="utf-8"))
            self.assertIn("#333333", twb.read_text(encoding="utf-8"))

    def test_apply_plan_renames_known_references(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(RICH_TWB, encoding="utf-8")
            plan = Path(directory, "plan.json")
            plan.write_text(json.dumps({
                "version": "1.0",
                "operations": [{"op": "rename_worksheet", "from": "Sheet 1", "to": "Sales Overview"}],
            }), encoding="utf-8")
            result = apply_edit_plan(str(twb), str(plan))
            self.assertEqual(result["changes"][0]["updated_known_references"], 2)
            self.assertNotIn("name=\"Sheet 1\"", twb.read_text(encoding="utf-8"))
            self.assertTrue(validate(str(twb))["ok"])

    def test_apply_plan_blocks_unknown_worksheet_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(
                "<workbook><worksheets><worksheet name='Sheet 1'/></worksheets><custom value='Sheet 1'/></workbook>",
                encoding="utf-8",
            )
            plan = Path(directory, "plan.json")
            plan.write_text(json.dumps({
                "version": "1.0",
                "operations": [{"op": "rename_worksheet", "from": "Sheet 1", "to": "Renamed"}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported worksheet references"):
                apply_edit_plan(str(twb), str(plan))

    def test_apply_plan_replaces_exact_run_text(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(RICH_TWB, encoding="utf-8")
            plan = Path(directory, "plan.json")
            plan.write_text(json.dumps({
                "version": "1.0",
                "operations": [{
                    "op": "replace_run_text",
                    "worksheet": "Sheet 1",
                    "from": "Text",
                    "to": "Revenue",
                    "expected": 1,
                }],
            }), encoding="utf-8")
            result = apply_edit_plan(str(twb), str(plan))
            self.assertEqual(result["changes"][0]["matched"], 1)
            self.assertIn(">Revenue</run>", twb.read_text(encoding="utf-8"))

    def test_apply_plan_sets_exact_zone_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(RICH_TWB, encoding="utf-8")
            plan = Path(directory, "plan.json")
            plan.write_text(json.dumps({
                "version": "1.0",
                "operations": [{
                    "op": "set_zone_geometry",
                    "dashboard": "Overview",
                    "zone_id": "1",
                    "set": {"x": 20, "y": 40, "w": 600, "h": 320},
                }],
            }), encoding="utf-8")
            result = apply_edit_plan(str(twb), str(plan))
            self.assertEqual(result["changes"][0]["before"], {"x": "0", "y": "0", "w": "400", "h": "300"})
            payload = twb.read_text(encoding="utf-8")
            self.assertIn('x="20"', payload)
            self.assertIn('w="600"', payload)

    def test_zone_geometry_rejects_nonpositive_size(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(RICH_TWB, encoding="utf-8")
            plan = Path(directory, "plan.json")
            plan.write_text(json.dumps({
                "version": "1.0",
                "operations": [{
                    "op": "set_zone_geometry",
                    "dashboard": "Overview",
                    "zone_id": "1",
                    "set": {"w": 0},
                }],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside the supported range"):
                apply_edit_plan(str(twb), str(plan))

    def test_diff_reports_exact_change(self):
        with tempfile.TemporaryDirectory() as directory:
            before = Path(directory, "before.twb")
            after = Path(directory, "after.twb")
            before.write_text(VALID_TWB, encoding="utf-8")
            after.write_text(VALID_TWB.replace("#000000", "#17365D"), encoding="utf-8")
            result = diff_workbooks(str(before), str(after))
            self.assertTrue(result["changed"])
            self.assertTrue(any("#17365D" in line for line in result["diff"]))

    def test_validate_package_compares_unrelated_members(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory, "input.twbx")
            with zipfile.ZipFile(baseline, "w") as package_file:
                package_file.writestr("Workbook/book.twb", VALID_TWB)
                package_file.writestr("Data/data.txt", "preserve me")
            extracted = safe_extract(str(baseline), str(Path(directory, "run")))
            replace_run_color(extracted["working_twb"], "#000000", "#17365D")
            output = Path(directory, "output.twbx")
            package(extracted["extracted_dir"], extracted["working_twb"], extracted["original_member"], str(output))
            result = validate_package(str(output), str(baseline))
            self.assertTrue(result["ok"])
            self.assertTrue(result["baseline_comparison"]["unrelated_members_preserved"])

            changed = Path(directory, "changed-asset.twbx")
            with zipfile.ZipFile(output) as source, zipfile.ZipFile(changed, "w") as target:
                for member in source.infolist():
                    data = b"changed" if member.filename == "Data/data.txt" else source.read(member.filename)
                    target.writestr(member, data)
            changed_result = validate_package(str(changed), str(baseline))
            self.assertFalse(changed_result["ok"])
            self.assertEqual(changed_result["baseline_comparison"]["changed_unrelated_members"], ["Data/data.txt"])

    def test_validate_rejects_doctype(self):
        with tempfile.TemporaryDirectory() as directory:
            twb = Path(directory, "book.twb")
            twb.write_text(
                "<!DOCTYPE workbook><workbook><worksheets><worksheet name='A'/></worksheets></workbook>",
                encoding="utf-8",
            )
            self.assertFalse(validate(str(twb))["ok"])


if __name__ == "__main__":
    unittest.main()

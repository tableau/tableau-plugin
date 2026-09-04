import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "render_wireframe.py"


def valid_spec():
    return {
        "title": "Sales <script>alert(1)</script>",
        "subtitle": "Manager view",
        "width": 1400,
        "height": 900,
        "columns": 12,
        "zones": [
            {"id": "kpi", "title": "Sales YTD", "kind": "kpi", "x": 1, "y": 1, "w": 4, "h": 1, "details": ["Placeholder: $1.2M"]},
            {"id": "trend", "title": "Monthly sales", "kind": "line", "x": 1, "y": 2, "w": 8, "h": 3, "details": ["MONTH(Order Date)"]},
        ],
        "filters": ["Region"],
        "notes": ["Mock values are placeholders"],
    }


class RendererTests(unittest.TestCase):
    def run_cli(self, payload, cwd=None, preset_output="", force=False):
        temp_dir = Path(tempfile.mkdtemp())
        input_path, output_path = temp_dir / "spec.json", temp_dir / "wireframe.html"
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        if preset_output:
            output_path.write_text(preset_output, encoding="utf-8")
        command = [sys.executable, str(SCRIPT.resolve()), str(input_path), str(output_path)]
        if force:
            command.append("--force")
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
        return result, output_path

    def test_renders_self_contained_html_and_escapes_text(self):
        result, output = self.run_cli(valid_spec())
        self.assertEqual(result.returncode, 0)
        text = output.read_text(encoding="utf-8")
        self.assertIn("<!doctype html>", text)
        self.assertIn("Sales &lt;script&gt;", text)
        self.assertNotIn("<script>alert(1)</script>", text)

    def test_runs_from_another_directory(self):
        result, output = self.run_cli(valid_spec(), cwd=tempfile.gettempdir())
        self.assertEqual(result.returncode, 0)
        self.assertTrue(output.exists())

    def test_rejects_overlap_without_overwriting_output(self):
        spec = valid_spec()
        spec["zones"].append({"id": "bad", "title": "Bad", "kind": "bar", "x": 2, "y": 1, "w": 2, "h": 1})
        result, output = self.run_cli(spec, preset_output="keep")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_rejects_out_of_bounds_zone(self):
        spec = valid_spec()
        spec["zones"][0]["x"], spec["zones"][0]["w"] = 11, 3
        self.assertEqual(self.run_cli(spec)[0].returncode, 2)

    def test_rejects_duplicate_id(self):
        spec = valid_spec()
        spec["zones"][1]["id"] = "kpi"
        self.assertEqual(self.run_cli(spec)[0].returncode, 2)

    def test_rejects_invalid_theme_color(self):
        spec = valid_spec()
        spec["theme"] = {"primary": "red"}
        self.assertEqual(self.run_cli(spec)[0].returncode, 2)

    def test_rejects_unknown_keys(self):
        spec = valid_spec()
        spec["publish"] = True
        self.assertEqual(self.run_cli(spec)[0].returncode, 2)

    def test_rejects_boolean_integer(self):
        spec = valid_spec()
        spec["width"] = True
        self.assertEqual(self.run_cli(spec)[0].returncode, 2)

    def test_refuses_existing_output_without_force(self):
        result, output = self.run_cli(valid_spec(), preset_output="keep")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_force_replaces_existing_output(self):
        result, output = self.run_cli(valid_spec(), preset_output="old", force=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("<!doctype html>", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

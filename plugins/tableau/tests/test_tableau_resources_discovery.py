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

    def test_inspect_exposes_typed_parameter_contracts(self) -> None:
        result = self.run_cli("inspect", "insights__bar_chart")
        self.assertEqual(result.returncode, 0, result.stderr)
        contracts = {
            parameter["name"]: parameter
            for parameter in json.loads(result.stdout)["parameters"]
        }
        self.assertEqual(contracts["DATE_MIN"]["type"], "date")
        self.assertEqual(contracts["DATE_MAX"]["type"], "date")
        self.assertEqual(contracts["DIRECTION"]["type"], "enum")
        self.assertEqual(contracts["DIRECTION"]["allowed"], ["ASC", "DESC"])
        for contract in contracts.values():
            self.assertTrue(contract["required"])

    def test_inspect_text_shows_parameter_types_and_allowed_values(self) -> None:
        result = self.run_cli("inspect", "insights__bar_chart", "--format", "text")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("  - DATE_MIN (date, required)", result.stdout)
        self.assertIn("  - DATE_MAX (date, required)", result.stdout)
        self.assertIn(
            "  - DIRECTION (enum, required, allowed: ASC, DESC)", result.stdout
        )

    def test_unknown_resource_fails_closed(self) -> None:
        result = self.run_cli("inspect", "does-not-exist")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown resource", result.stderr)


if __name__ == "__main__":
    unittest.main()

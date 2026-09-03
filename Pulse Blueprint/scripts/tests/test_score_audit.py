import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "score_audit.py"


def base_payload():
    return {
        "methodology_version": "1.0",
        "definitions": [
            {"id": "a", "name": "Revenue", "status": "assessed"},
            {"id": "b", "name": "Partial", "status": "partial"},
            {"id": "c", "name": "Blocked", "status": "failed"},
        ],
        "findings": [],
    }


class AuditScoreTests(unittest.TestCase):
    def run_cli(self, payload, cwd=None):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = Path(handle.name)
        try:
            return subprocess.run([sys.executable, str(SCRIPT.resolve()), str(path.resolve())], cwd=cwd, capture_output=True, text=True, check=False)
        finally:
            path.unlink()

    def test_coverage_and_composite_exclusions(self):
        output = json.loads(self.run_cli(base_payload()).stdout)
        self.assertEqual(output["coverage"], {"assessed": 1, "failed": 1, "partial": 1})
        self.assertEqual(output["overall_score"], 100)
        self.assertTrue(output["definitions"][1]["provisional"])
        self.assertIsNone(output["definitions"][2]["score"])

    def test_penalties_and_grade(self):
        payload = base_payload()
        payload["findings"] = [
            {"definition_id": "a", "rule_id": "r1", "evidence_key": "x", "severity": "high", "summary": "x"},
            {"definition_id": "a", "rule_id": "r2", "evidence_key": "y", "severity": "medium", "summary": "y"},
            {"definition_id": "a", "rule_id": "r3", "evidence_key": "z", "severity": "low", "summary": "z"},
        ]
        output = json.loads(self.run_cli(payload).stdout)
        self.assertEqual(output["overall_score"], 92.5)
        self.assertEqual(output["overall_grade"], "A-")

    def test_observation_is_not_scored(self):
        payload = base_payload()
        payload["findings"] = [{"definition_id": "a", "rule_id": "dimension.count", "evidence_key": "dimensions", "severity": "medium", "summary": "one dimension", "observation": True}]
        output = json.loads(self.run_cli(payload).stdout)
        self.assertEqual(output["overall_score"], 100)
        self.assertEqual(len(output["observations"]), 1)

    def test_dedup_keeps_highest_severity(self):
        payload = base_payload()
        common = {"definition_id": "a", "rule_id": "same", "evidence_key": "same", "summary": "duplicate"}
        payload["findings"] = [{**common, "severity": "low"}, {**common, "severity": "critical"}]
        output = json.loads(self.run_cli(payload).stdout)
        self.assertEqual(len(output["findings"]), 1)
        self.assertEqual(output["overall_score"], 90)

    def test_partial_score_does_not_affect_composite(self):
        payload = base_payload()
        payload["findings"] = [{"definition_id": "b", "rule_id": "r", "evidence_key": "e", "severity": "critical", "summary": "partial"}]
        output = json.loads(self.run_cli(payload).stdout)
        self.assertEqual(output["overall_score"], 100)
        self.assertEqual(output["definitions"][1]["score"], 90)

    def test_rejects_finding_for_failed_definition(self):
        payload = base_payload()
        payload["findings"] = [{"definition_id": "c", "rule_id": "r", "evidence_key": "e", "severity": "low", "summary": "bad"}]
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_rejects_unknown_definition(self):
        payload = base_payload()
        payload["findings"] = [{"definition_id": "z", "rule_id": "r", "evidence_key": "e", "severity": "low", "summary": "bad"}]
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_rejects_wrong_methodology(self):
        payload = base_payload()
        payload["methodology_version"] = "0.9"
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_rejects_invalid_boolean(self):
        payload = base_payload()
        payload["findings"] = [{"definition_id": "a", "rule_id": "r", "evidence_key": "e", "severity": "low", "summary": "bad", "observation": "yes"}]
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_cross_directory_cli(self):
        self.assertEqual(self.run_cli(base_payload(), cwd=tempfile.gettempdir()).returncode, 0)

    def test_all_failed_has_no_composite(self):
        payload = {"methodology_version": "1.0", "definitions": [{"id": "x", "name": "Blocked", "status": "failed"}], "findings": []}
        output = json.loads(self.run_cli(payload).stdout)
        self.assertIsNone(output["overall_score"])
        self.assertIsNone(output["overall_grade"])

    def test_rejects_unknown_top_level_key(self):
        payload = base_payload()
        payload["publish"] = True
        self.assertEqual(self.run_cli(payload).returncode, 2)


if __name__ == "__main__":
    unittest.main()

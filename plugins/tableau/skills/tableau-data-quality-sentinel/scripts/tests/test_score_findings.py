import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "score_findings.py"


def base_payload():
    return {"sources": [{"id": "a", "name": "Orders"}, {"id": "b", "name": "Blocked", "status": "failed"}], "findings": []}


class ScoreTests(unittest.TestCase):
    def run_cli(self, payload, cwd=None):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = Path(handle.name)
        try:
            return subprocess.run([sys.executable, str(SCRIPT.resolve()), str(path.resolve())], cwd=cwd, capture_output=True, text=True, check=False)
        finally:
            path.unlink()

    def test_empty_profile_scores_100_and_failed_excluded(self):
        output = json.loads(self.run_cli(base_payload()).stdout)
        self.assertEqual(output["overall_score"], 100)
        self.assertEqual(output["coverage"], {"failed": 1, "profiled": 1, "reused": 0})
        self.assertIsNone(output["sources"][1]["score"])

    def test_penalties_and_cross_domain_escalation(self):
        payload = base_payload()
        payload["findings"] = [
            {"source_id": "a", "domain": "types", "rule_id": "r1", "severity": "high", "evidence_key": "x", "summary": "x"},
            {"source_id": "a", "domain": "metadata", "rule_id": "r2", "severity": "high", "evidence_key": "y", "summary": "y", "additional_domains": ["types"]},
        ]
        output = json.loads(self.run_cli(payload).stdout)
        self.assertEqual(output["overall_score"], 85)
        self.assertEqual(output["findings"][1]["effective_severity"], "critical")

    def test_dedup_keeps_highest(self):
        payload = base_payload()
        common = {"source_id": "a", "domain": "naming", "rule_id": "same", "evidence_key": "field", "summary": "same"}
        payload["findings"] = [{**common, "severity": "low"}, {**common, "severity": "medium"}]
        output = json.loads(self.run_cli(payload).stdout)
        self.assertEqual(len(output["findings"]), 1)
        self.assertEqual(output["overall_score"], 98)

    def test_observation_does_not_reduce_score(self):
        payload = base_payload()
        payload["findings"] = [{"source_id": "a", "domain": "schema", "rule_id": "single", "severity": "low", "evidence_key": "one", "summary": "one table", "observation": True}]
        output = json.loads(self.run_cli(payload).stdout)
        self.assertEqual(output["overall_score"], 100)
        self.assertEqual(len(output["observations"]), 1)

    def test_combined_condition_becomes_critical(self):
        payload = base_payload()
        payload["findings"] = [{"source_id": "a", "domain": "metadata", "rule_id": "combined", "severity": "low", "evidence_key": "all", "summary": "combined", "combined_critical": True}]
        output = json.loads(self.run_cli(payload).stdout)
        self.assertEqual(output["overall_score"], 90)

    def test_unknown_source_is_rejected(self):
        payload = base_payload()
        payload["findings"] = [{"source_id": "z", "domain": "schema", "rule_id": "r", "severity": "low", "evidence_key": "e", "summary": "bad"}]
        result = self.run_cli(payload)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown source", result.stderr)

    def test_invalid_boolean_is_rejected(self):
        payload = base_payload()
        payload["findings"] = [{"source_id": "a", "domain": "schema", "rule_id": "r", "severity": "low", "evidence_key": "e", "summary": "bad", "systemic": "yes"}]
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_cross_directory_cli(self):
        self.assertEqual(self.run_cli(base_payload(), cwd=tempfile.gettempdir()).returncode, 0)

    def test_unassessed_domain_has_null_score(self):
        payload = {"sources": [{"id": "a", "name": "Partial", "assessed_domains": ["schema"]}], "findings": []}
        output = json.loads(self.run_cli(payload).stdout)
        self.assertIsNone(output["sources"][0]["domains"]["metadata"]["score"])
        self.assertEqual(output["sources"][0]["domains"]["schema"]["score"], 100)
        self.assertIsNone(output["domains"]["metadata"]["score"])

    def test_finding_in_unassessed_domain_is_rejected(self):
        payload = {"sources": [{"id": "a", "name": "Partial", "assessed_domains": ["schema"]}], "findings": [{"source_id": "a", "domain": "metadata", "rule_id": "r", "severity": "low", "evidence_key": "e", "summary": "bad"}]}
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_reused_source_requires_matching_methodology(self):
        payload = {"sources": [{"id": "a", "name": "Prior", "status": "reused"}], "findings": []}
        self.assertEqual(self.run_cli(payload).returncode, 2)
        payload["methodology_version"] = "1.0"
        self.assertEqual(self.run_cli(payload).returncode, 0)


if __name__ == "__main__":
    unittest.main()

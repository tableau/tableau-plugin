import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "validate_evidence.py"


def valid_payload():
    return {
        "artifact_type": "dashboard_documentation",
        "query_authorized": False,
        "target": {"id": "v1", "name": "Sales", "kind": "view"},
        "sources": [{"id": "img", "type": "view_image", "scope": "default render"}],
        "records": [
            {"id": "r1", "subject": "dashboard", "attribute": "title", "value": "Sales", "status": "observed", "sources": ["img"]},
            {"id": "r2", "subject": "dashboard", "attribute": "audience", "value": "managers", "status": "inferred", "sources": ["img"], "note": "KPI emphasis"},
            {"id": "r3", "subject": "dashboard", "attribute": "refresh cadence", "value": None, "status": "unknown", "sources": [], "note": "not exposed"},
        ],
    }


class EvidenceTests(unittest.TestCase):
    def run_cli(self, payload, cwd=None):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = Path(handle.name)
        try:
            return subprocess.run([sys.executable, str(SCRIPT.resolve()), str(path.resolve())], cwd=cwd, capture_output=True, text=True, check=False)
        finally:
            path.unlink()

    def test_valid_ledger_and_counts(self):
        output = json.loads(self.run_cli(valid_payload()).stdout)
        self.assertEqual(output["summary"]["records_by_status"], {"inferred": 1, "observed": 1, "unknown": 1})
        self.assertEqual(output["summary"]["sources_by_type"], {"view_image": 1})

    def test_cross_directory_cli(self):
        self.assertEqual(self.run_cli(valid_payload(), cwd=tempfile.gettempdir()).returncode, 0)

    def test_queried_data_requires_authorization(self):
        payload = valid_payload()
        payload["sources"][0]["type"] = "queried_data"
        self.assertEqual(self.run_cli(payload).returncode, 2)
        payload["query_authorized"] = True
        self.assertEqual(self.run_cli(payload).returncode, 0)

    def test_observed_requires_source(self):
        payload = valid_payload()
        payload["records"][0]["sources"] = []
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_inferred_requires_note(self):
        payload = valid_payload()
        del payload["records"][1]["note"]
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_unknown_requires_null_and_no_sources(self):
        payload = valid_payload()
        payload["records"][2]["value"] = "daily"
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_rejects_duplicate_claim_case_insensitively(self):
        payload = valid_payload()
        payload["records"].append({"id": "r4", "subject": "Dashboard", "attribute": "Title", "value": "Other", "status": "observed", "sources": ["img"]})
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_rejects_unknown_source_reference(self):
        payload = valid_payload()
        payload["records"][0]["sources"] = ["missing"]
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_rejects_unreferenced_source(self):
        payload = valid_payload()
        payload["sources"].append({"id": "meta", "type": "view_metadata", "scope": "metadata"})
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_rejects_unknown_top_level_key(self):
        payload = valid_payload()
        payload["publish"] = True
        self.assertEqual(self.run_cli(payload).returncode, 2)

    def test_allows_unresolved_target_id(self):
        payload = valid_payload()
        payload["target"]["id"] = None
        self.assertEqual(self.run_cli(payload).returncode, 0)

    def test_rejects_nested_value_objects(self):
        payload = valid_payload()
        payload["records"][0]["value"] = {"unsafe": "shape"}
        self.assertEqual(self.run_cli(payload).returncode, 2)


if __name__ == "__main__":
    unittest.main()

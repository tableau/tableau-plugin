import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "score_viz.py"
sys.path.insert(0, str(SCRIPT.parent))

from score_viz import WEIGHTS, calculate


def payload(score=8):
    return {"domains": {domain: {"base": score, "adjustments": []} for domain in WEIGHTS}}


class ScoreVizTests(unittest.TestCase):
    def test_weights_total_one(self):
        self.assertEqual(sum(WEIGHTS.values()), 1)

    def test_equal_domains_return_same_score_and_tier(self):
        result = calculate(payload(8))
        self.assertEqual(result["score"], 8.0)
        self.assertEqual(result["tier"], "Would Publish to Public")

    def test_half_even_rounding(self):
        assessment = payload(7.45)
        self.assertEqual(calculate(assessment)["score"], 7.4)
        assessment = payload(7.55)
        self.assertEqual(calculate(assessment)["score"], 7.6)

    def test_domain_and_overall_caps_apply(self):
        assessment = payload(9)
        assessment["caps"] = {
            "domains": {"D2": 5.5, "D1": 6.0},
            "overall": [{"label": "ethical risk", "value": 7.9, "kind": "safety"}],
        }
        result = calculate(assessment)
        self.assertEqual(result["domains"]["D2"]["score"], 5.5)
        self.assertEqual(result["score"], 7.9)
        self.assertEqual(result["applied_overall_cap"]["label"], "ethical risk")
        self.assertEqual(result["tier"], "Safety remediation required")
        self.assertEqual(result["safety_status"], "blocked")

    def test_rejects_excess_bonus(self):
        assessment = payload(7)
        assessment["domains"]["D3"]["adjustments"] = [
            {"id": "innovative-clarity", "label": "innovation", "value": 0.3, "kind": "bonus"}
        ]
        assessment["domains"]["D4"]["adjustments"] = [
            {"id": "aesthetic-excellence", "label": "aesthetics", "value": 0.5, "kind": "bonus"}
        ]
        assessment["domains"]["D6"]["adjustments"] = [
            {"id": "exceptional-annotations", "label": "annotations", "value": 0.2, "kind": "bonus"}
        ]
        with self.assertRaisesRegex(ValueError, "bonuses exceed"):
            calculate(assessment)

    def test_rejects_unclassified_positive_adjustment(self):
        assessment = payload(7)
        assessment["domains"]["D5"]["adjustments"] = [{"label": "nice colors", "value": 0.2}]
        with self.assertRaisesRegex(ValueError, "positive adjustments"):
            calculate(assessment)

    def test_rejects_bonus_in_wrong_domain(self):
        assessment = payload(7)
        assessment["domains"]["D1"]["adjustments"] = [
            {"id": "aesthetic-excellence", "label": "unsupported placement", "value": 0.5, "kind": "bonus"}
        ]
        with self.assertRaisesRegex(ValueError, "not allowed in D1"):
            calculate(assessment)

    def test_rejects_bonus_above_individual_maximum(self):
        assessment = payload(7)
        assessment["domains"]["D3"]["adjustments"] = [
            {"id": "innovative-clarity", "label": "too large", "value": 0.4, "kind": "bonus"}
        ]
        with self.assertRaisesRegex(ValueError, "no more than 0.3"):
            calculate(assessment)

    def test_safety_cap_blocks_even_below_cap(self):
        assessment = payload(4)
        assessment["caps"] = {
            "overall": [{"label": "Exposed sensitive information", "value": 7.9, "kind": "safety"}]
        }
        result = calculate(assessment)
        self.assertEqual(result["score"], 4.0)
        self.assertEqual(result["tier"], "Safety remediation required")
        self.assertEqual(result["safety_status"], "blocked")

    def test_cli_runs_from_outside_skill_directory(self):
        assessment = payload(8)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "assessment.json")
            source.write_text(json.dumps(assessment), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT.resolve()), str(source.resolve())],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["score"], 8.0)

    def test_cli_rejects_missing_domain(self):
        assessment = payload(7)
        del assessment["domains"]["D7"]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "assessment.json")
            source.write_text(json.dumps(assessment), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(source)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("exactly D1 through D7", completed.stderr)


if __name__ == "__main__":
    unittest.main()

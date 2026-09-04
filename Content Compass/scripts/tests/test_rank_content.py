import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "rank_content.py"
sys.path.insert(0, str(SCRIPT.parent))

from rank_content import rank


def candidate(candidate_id, name, **overrides):
    value = {"id": candidate_id, "type": "view", "name": name, "project": "Sales"}
    value.update(overrides)
    return value


class RankContentTests(unittest.TestCase):
    def test_strong_match_has_named_signals(self):
        payload = {
            "query": {"terms": ["sales", "region"], "temporal": True},
            "as_of": "2026-09-03",
            "candidates": [candidate(
                "v1",
                "Regional Sales Trends",
                description="Monthly sales by region",
                fields=["Region", "Sales Amount", "Order Date"],
                tags=["sales"],
                has_date_field=True,
                updated_at="2026-08-15T00:00:00Z",
            )],
        }
        result = rank(payload)
        item = result["tiers"]["High"][0]
        self.assertEqual(item["score"], 100)
        self.assertEqual(item["top_signals"][0]["id"], "name-primary-word")

    def test_name_and_field_use_only_strongest_signal(self):
        payload = {
            "query": {"terms": ["sales"], "synonyms": ["revenue"], "implied_terms": ["amount"]},
            "candidates": [candidate("v1", "Wholesale Revenue", fields=["Sales Amount", "Revenue Amount"])],
        }
        signals = rank(payload)["tiers"]["Medium"][0]["signals"]
        name_ids = {item["id"] for item in signals if item["id"].startswith("name-")}
        field_ids = {item["id"] for item in signals if item["id"].startswith("field-")}
        self.assertEqual(name_ids, {"name-synonym-word"})
        self.assertEqual(field_ids, {"field-primary"})

    def test_usage_bonus_requires_four_views_in_same_project(self):
        candidates = [candidate(f"v{index}", f"Sales {index}", usage_count=count) for index, count in enumerate([1, 2, 3, 100])]
        result = rank({"query": {"terms": ["sales"]}, "candidates": candidates})
        top = result["tiers"]["Medium"][0]
        self.assertEqual(top["candidate"]["usage_count"], 100)
        self.assertIn("usage-top-quartile", {item["id"] for item in top["signals"]})
        awarded = [
            item for item in result["tiers"]["Medium"]
            if "usage-top-quartile" in {entry["id"] for entry in item["signals"]}
        ]
        self.assertEqual(len(awarded), 1)

    def test_field_phrase_does_not_span_distinct_fields(self):
        payload = {
            "query": {"terms": ["regional sales"]},
            "candidates": [candidate("v1", "Overview", fields=["Regional", "Sales"])],
        }
        self.assertEqual(rank(payload)["qualified_candidates"], 0)

    def test_ties_end_with_name_ascending(self):
        payload = {
            "query": {"terms": ["sales"]},
            "max_per_tier": 3,
            "candidates": [candidate("b", "Sales Beta"), candidate("a", "Sales"), candidate("c", "Sales Alpha")],
        }
        names = [item["candidate"]["name"] for item in rank(payload)["tiers"]["Low"]]
        self.assertEqual(names, ["Sales", "Sales Alpha", "Sales Beta"])

    def test_recency_is_deterministic_and_requires_as_of(self):
        item = candidate("v1", "Sales", updated_at="2026-08-15T00:00:00Z")
        without_date = rank({"query": {"terms": ["sales"]}, "candidates": [item]})
        self.assertEqual(without_date["tiers"]["Low"][0]["score"], 30)
        self.assertTrue(without_date["warnings"])
        with_date = rank({"query": {"terms": ["sales"]}, "as_of": "2026-09-03", "candidates": [item]})
        self.assertEqual(with_date["tiers"]["Medium"][0]["score"], 35)

    def test_filters_below_threshold_and_caps_tiers(self):
        candidates = [candidate("none", "Inventory"), candidate("a", "Sales A"), candidate("b", "Sales B")]
        result = rank({"query": {"terms": ["sales"]}, "max_per_tier": 1, "candidates": candidates})
        self.assertEqual(result["qualified_candidates"], 2)
        self.assertEqual(result["tier_totals"]["Low"], 2)
        self.assertEqual(len(result["tiers"]["Low"]), 1)

    def test_rejects_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, "ids must be unique"):
            rank({"query": {"terms": ["sales"]}, "candidates": [candidate("x", "Sales"), candidate("x", "Sales 2")]})

    def test_cli_runs_outside_skill_directory(self):
        payload = {"query": {"terms": ["sales"]}, "candidates": [candidate("v1", "Sales Overview")]}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "input.json")
            source.write_text(json.dumps(payload), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT.resolve()), str(source.resolve())],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["qualified_candidates"], 1)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Unit tests for score_governance.py."""

import unittest

from score_governance import grade, score_scan


class ScoreTests(unittest.TestCase):
    def test_normalizes_across_assessed_entities(self):
        payload = {
            "entities": [
                {"id": "a", "status": "assessed", "include_in_score": True,
                 "applicable_domains": ["naming", "metadata"]},
                {"id": "b", "status": "assessed", "include_in_score": True,
                 "applicable_domains": ["naming", "metadata"]},
                {"id": "c", "status": "partial", "include_in_score": False,
                 "applicable_domains": ["metadata"]},
            ],
            "findings": [
                {"entity_id": "a", "domain": "naming", "rule_id": "r1", "severity": "HIGH"},
                {"entity_id": "a", "domain": "naming", "rule_id": "r2", "severity": "LOW"},
                {"entity_id": "c", "domain": "metadata", "rule_id": "missing", "severity": "MEDIUM"},
            ],
        }
        result = score_scan(payload)
        self.assertEqual(result["score"], 87.5)
        self.assertEqual(result["grade"], "B+")
        self.assertEqual(result["included_entities"], 2)
        self.assertEqual(result["coverage"], {"assessed": 2, "partial": 1})

    def test_rejects_partial_entity_in_score(self):
        payload = {"entities": [{"id": "a", "status": "partial", "include_in_score": True,
                                  "applicable_domains": ["metadata"]}], "findings": []}
        with self.assertRaisesRegex(ValueError, "only assessed"):
            score_scan(payload)

    def test_rejects_duplicate_finding(self):
        finding = {"entity_id": "a", "domain": "metadata", "rule_id": "r", "severity": "LOW"}
        payload = {"entities": [{"id": "a", "status": "assessed", "include_in_score": True,
                                  "applicable_domains": ["metadata"]}],
                   "findings": [finding, finding.copy()]}
        with self.assertRaisesRegex(ValueError, "duplicate finding"):
            score_scan(payload)

    def test_grade_boundaries(self):
        self.assertEqual(grade(97), "A+")
        self.assertEqual(grade(90), "A-")
        self.assertEqual(grade(59.99), "F")


if __name__ == "__main__":
    unittest.main()

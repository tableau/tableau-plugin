import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "calc_checks.py"
sys.path.insert(0, str(SCRIPT.parent))

from calc_checks import check_stored_formula, normalize


class CalcChecksTests(unittest.TestCase):
    def test_normalize_preserves_fields_and_folds_functions(self):
        self.assertEqual(normalize("SUM ( [Sales] ) // note\n / COUNT([ID])"), "sum([Sales] ) / count([ID])")

    def test_normalize_preserves_comment_markers_and_whitespace_in_strings(self):
        formula = "IF [URL] = 'https://example.test/a  b' THEN SUM ( [Sales] ) END // note"
        self.assertEqual(
            normalize(formula),
            "IF [URL] = 'https://example.test/a  b' THEN sum([Sales] ) END",
        )

    def test_check_accepts_expected_operator(self):
        result = check_stored_formula("IF [Sales] < 10 THEN 1 END", ["<"])
        self.assertTrue(result["ok"])

    def test_check_rejects_double_escape_and_missing_operator(self):
        result = check_stored_formula("[Sales] &amp;lt; 10", ["<"])
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["issues"]), 2)

    def test_cli_returns_nonzero_for_invalid_formula(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "check", "--expect-operator", ">"],
            input="",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("stored formula is empty", completed.stdout)


if __name__ == "__main__":
    unittest.main()

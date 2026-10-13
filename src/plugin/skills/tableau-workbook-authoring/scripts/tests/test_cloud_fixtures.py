"""Workbooks Tableau Cloud saved itself must pass the validator.

The fixtures are real site content, so their workbooks are git-ignored. Every
.twb/.twbx file under $TABLEAU_PLUGIN_FIXTURES (default src/fixtures) is
tested, at any depth. Files whose schema errors are known XSD gaps can be
listed in a ``known-schema-gaps.txt`` anywhere under that directory, one file
name per line, ``#`` comments allowed. Without any workbooks the tests skip.
"""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).parents[1]
SCHEMAS = SCRIPTS.parent / "resources" / "schemas"
sys.path.insert(0, str(SCRIPTS))

try:
    from lxml import etree
    from validate_workbook import manifest_issues, validate_workbook
except (ImportError, SystemExit):  # validate_workbook exits when lxml is missing
    validate_workbook = None

FIXTURES = Path(os.environ.get(
    "TABLEAU_PLUGIN_FIXTURES", Path(__file__).parents[5] / "fixtures"  # src/fixtures
))


def _known_schema_gaps() -> set[str]:
    gaps = set()
    for listing in FIXTURES.rglob("known-schema-gaps.txt"):
        names = (line.split("#", 1)[0].strip() for line in listing.read_text().splitlines())
        gaps.update(name for name in names if name)
    return gaps


@unittest.skipIf(validate_workbook is None, "validate_workbook needs lxml")
class CloudSavedFixtures(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.workbooks = sorted(p for p in FIXTURES.rglob("*.twb*")
                               if p.suffix in (".twb", ".twbx"))
        if not cls.workbooks:
            raise unittest.SkipTest(f"no fixtures under {FIXTURES}")
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def twb(self, path: Path) -> Path:
        if path.suffix != ".twbx":
            return path
        with zipfile.ZipFile(path) as package:
            inner = next(n for n in package.namelist() if n.endswith(".twb"))
            out = Path(self.tmp.name) / ("-".join(path.relative_to(FIXTURES).parts) + ".twb")
            out.write_bytes(package.read(inner))
        return out

    def test_valid_against_itself_as_baseline(self):
        for path in self.workbooks:
            with self.subTest(path.name):
                result = validate_workbook(str(self.twb(path)), str(SCHEMAS),
                                           baseline=str(self.twb(path)))
                self.assertTrue(result.is_valid, [i.message for i in result.issues])

    def test_manifest_rules_match_what_cloud_wrote(self):
        parser = etree.XMLParser(huge_tree=True)
        for path in self.workbooks:
            with self.subTest(path.name):
                doc = etree.parse(str(self.twb(path)), parser).getroot()
                self.assertEqual([i.message for i in manifest_issues(doc)], [])

    def test_schema_valid_without_baseline(self):
        gaps = _known_schema_gaps()
        for path in self.workbooks:
            if path.name in gaps:
                continue
            with self.subTest(path.name):
                result = validate_workbook(str(self.twb(path)), str(SCHEMAS))
                self.assertTrue(result.is_valid, [i.message for i in result.issues])


if __name__ == "__main__":
    unittest.main()

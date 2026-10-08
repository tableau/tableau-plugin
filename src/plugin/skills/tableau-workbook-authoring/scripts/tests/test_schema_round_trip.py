import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1]
SCHEMAS = SCRIPTS.parent / "resources" / "schemas"
sys.path.insert(0, str(SCRIPTS))

try:
    from validate_workbook import validate_workbook
except SystemExit:  # validate_workbook exits when lxml is missing
    validate_workbook = None

DATASOURCE = """<datasource caption='Sample - Superstore' inline='true' name='sqlproxy.abc' version='18.1'>
  <connection class='sqlproxy' dbname='Superstore' server='example' port='443' channel='https' />
  <column datatype='string' name='[Customer Name]' role='dimension' type='nominal' />
  <column datatype='real' name='[Profit]' role='measure' type='quantitative' />
</datasource>"""


@unittest.skipIf(validate_workbook is None, "validate_workbook needs lxml")
class RoundTrip(unittest.TestCase):
    """A ranked bar from the catalog uses `<computed-sort>`; Tableau Cloud saves
    the same sort as `<sort class='computed'>` with no `<simple-id>`."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        (tmp / "ds.xml").write_text(DATASOURCE, encoding="utf-8")
        cls.generated = tmp / "generated.twb"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "tableau_resources.py"), "instantiate",
             "ranking-ordered-bar", "--datasource-definition", str(tmp / "ds.xml"),
             "--output", str(cls.generated), "--worksheet-name", "Bars",
             "--map", "Customer Name=Customer Name", "--map", "Profit=Profit"],
            check=True, capture_output=True,
        )
        text = cls.generated.read_text(encoding="utf-8")
        assert "<computed-sort " in text
        text = text.replace("<computed-sort ", "<sort class='computed' ")
        text = re.sub(r"\s*<simple-id [^>]*/>", "", text)
        cls.cloud_saved = tmp / "cloud_saved.twb"
        cls.cloud_saved.write_text(text, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def validate(self, path, baseline=None):
        return validate_workbook(str(path), str(SCHEMAS), baseline=baseline and str(baseline))

    def test_generated_workbook_is_valid(self):
        result = self.validate(self.generated)
        self.assertTrue(result.is_valid, [i.message for i in result.issues])

    def test_legacy_sort_without_simple_id_is_valid_and_quiet(self):
        result = self.validate(self.cloud_saved)
        self.assertTrue(result.is_valid, [i.message for i in result.issues])
        self.assertFalse([w for w in result.warnings if "simple-id" in w.message])

    def test_schema_errors_in_baseline_are_dropped(self):
        broken = Path(self.tmp.name) / "broken_original.twb"
        broken.write_text(
            self.cloud_saved.read_text(encoding="utf-8").replace("</table>", "<bogus /></table>", 1),
            encoding="utf-8",
        )
        self.assertFalse(self.validate(broken).is_valid)
        result = self.validate(broken, baseline=broken)
        self.assertTrue(result.is_valid, [i.message for i in result.issues])
        self.assertTrue([w for w in result.warnings if "already in the baseline" in w.message])

    def test_schema_error_introduced_by_edit_is_reported(self):
        edited = Path(self.tmp.name) / "edited.twb"
        edited.write_text(
            self.cloud_saved.read_text(encoding="utf-8").replace("</table>", "<bogus /></table>", 1),
            encoding="utf-8",
        )
        result = self.validate(edited, baseline=self.cloud_saved)
        self.assertFalse(result.is_valid)
        self.assertTrue(any("'bogus'" in i.message for i in result.issues))


if __name__ == "__main__":
    unittest.main()

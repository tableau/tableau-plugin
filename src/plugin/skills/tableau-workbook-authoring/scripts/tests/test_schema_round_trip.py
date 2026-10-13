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
    """A ranked bar from the catalog uses `<computed-sort>` and `<simple-id>`,
    which the starter's manifest flags allow. A Cloud-saved workbook without
    those flags uses `<sort class='computed'>` and no `<simple-id>`."""

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
        text = re.sub(r"\s*<(SortTagCleanup|SheetIdentifierTracking) />", "", text)
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

    def test_modern_forms_without_manifest_flags_are_rejected(self):
        unflagged = Path(self.tmp.name) / "unflagged.twb"
        unflagged.write_text(
            re.sub(r"\s*<(SortTagCleanup|SheetIdentifierTracking) />", "",
                   self.generated.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        result = self.validate(unflagged)
        self.assertFalse(result.is_valid)
        messages = " ".join(i.message for i in result.issues)
        self.assertIn("<SortTagCleanup />", messages)
        self.assertIn("<SheetIdentifierTracking />", messages)

    def test_every_sheet_has_its_own_simple_id_under_the_flag(self):
        text = self.generated.read_text(encoding="utf-8")
        worksheet = re.search(r"<worksheet .*?</worksheet>", text, re.S).group()
        window = re.search(r"<window .*?</window>", text, re.S).group()
        ids = [re.search(r"<simple-id uuid='([^']+)'", part).group(1)
               for part in (worksheet, window)]
        self.assertNotEqual(*ids)

    def test_missing_simple_id_under_the_flag_is_rejected(self):
        stripped = Path(self.tmp.name) / "no_ids.twb"
        stripped.write_text(
            re.sub(r"\s*<simple-id [^>]*/>", "", self.generated.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        result = self.validate(stripped)
        self.assertFalse(result.is_valid)
        messages = [i.message for i in result.issues]
        self.assertTrue(any(m.startswith("Element 'worksheet' ('Bars')") for m in messages), messages)
        self.assertTrue(any(m.startswith("Element 'window' ('Bars')") for m in messages), messages)

    def test_inject_writes_the_forms_the_target_manifest_allows(self):
        injected = Path(self.tmp.name) / "injected.twb"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "tableau_resources.py"), "inject",
             "ranking-ordered-bar", "--input", str(self.cloud_saved),
             "--output", str(injected), "--worksheet-name", "More Bars",
             "--datasource", "sqlproxy.abc",
             "--map", "Customer Name=Customer Name", "--map", "Profit=Profit"],
            check=True, capture_output=True,
        )
        text = injected.read_text(encoding="utf-8")
        self.assertNotIn("<computed-sort", text)
        self.assertNotIn("<simple-id", text)
        self.assertEqual(text.count("<sort class='computed'"), 2)
        result = self.validate(injected, baseline=self.cloud_saved)
        self.assertTrue(result.is_valid, [i.message for i in result.issues])


if __name__ == "__main__":
    unittest.main()

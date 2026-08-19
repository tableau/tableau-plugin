import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

PLUGIN = Path(__file__).resolve().parents[1]
RESOURCES = PLUGIN / "resources"


class ResourceLayoutTest(unittest.TestCase):
    def test_required_layout_and_pinned_pulse_resources(self) -> None:
        provenance = json.loads((RESOURCES / "provenance.json").read_text())
        self.assertEqual(provenance["schemaVersion"], 1)
        self.assertEqual(
            provenance["sources"][0]["commit"],
            "3e77dd40997a2ffcb89fb25fa40c9abc1ac59a71",
        )
        for name in ("insights__bar_chart.tbm", "insights__line_chart.tbm"):
            matches = list((RESOURCES / "templates").glob(f"*/{name}"))
            self.assertEqual(len(matches), 1, name)
            self.assertEqual(ET.parse(matches[0]).getroot().tag, "bookmark")

    def test_every_declared_import_hash_matches(self) -> None:
        provenance = json.loads((RESOURCES / "provenance.json").read_text())
        for source in provenance["sources"]:
            for imported in source["imports"]:
                matches = list((RESOURCES / "templates").glob(f"*/{imported['filename']}"))
                self.assertEqual(len(matches), 1, imported["filename"])
                path = matches[0]
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(digest, imported["sha256"], path)

    def test_starter_is_datasource_free_workbook(self) -> None:
        root = ET.parse(RESOURCES / "starters/minimal-workbook.twb").getroot()
        self.assertEqual(root.tag, "workbook")
        datasources = root.find("datasources")
        self.assertIsNotNone(datasources)
        self.assertEqual(len(list(datasources)), 0)
        self.assertIsNotNone(root.find("worksheets"))
        self.assertIsNotNone(root.find("windows"))

    def test_gitignore_excludes_os_and_interpreter_cruft(self) -> None:
        # Filesystem noise like .DS_Store and __pycache__/ must never be
        # trackable, since the catalog generator now treats them as
        # non-resources and would otherwise disagree with a dirty checkout.
        repo_root = PLUGIN.parents[1]
        gitignore = (repo_root / ".gitignore").read_text().splitlines()
        self.assertIn(".DS_Store", gitignore)
        self.assertIn("__pycache__/", gitignore)

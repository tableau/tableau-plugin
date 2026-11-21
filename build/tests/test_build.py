"""Check that the OpenAI builds use installable marketplace entries."""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build import PAYLOAD_DEST_SUBPATH, build_platform, zip_plugin


MANIFESTS = ("plugin.json", ".codex-plugin/plugin.json")


class OpenAIBuildTests(unittest.TestCase):
    def test_catalog_and_manifests_agree_on_the_install_name(self):
        expected_names = {
            "prod": "Tableau",
            "test": "Tableau-test",
            "stage": "Tableau-stage",
            "dev": "Tableau-dev",
        }

        with TemporaryDirectory() as tmp:
            for variant, expected_name in expected_names.items():
                with self.subTest(variant=variant):
                    dist = build_platform("openai", Path(tmp), variant=variant)
                    marketplace = dist / ".agents/plugins/marketplace.json"
                    (entry,) = json.loads(marketplace.read_text(encoding="utf-8"))["plugins"]
                    self.assertEqual(entry["name"], expected_name)

                    plugin_dir = dist / entry["source"]["path"]
                    for relative in MANIFESTS:
                        manifest = json.loads((plugin_dir / relative).read_text(encoding="utf-8"))
                        self.assertEqual(manifest["name"], entry["name"], relative)

    def test_only_prod_zip_uses_the_submission_id(self):
        names = {
            "prod": "app-6a5937013728819186b9de76e1f68de1",
            "test": "Tableau-test",
        }
        with TemporaryDirectory() as tmp:
            for variant, archive_name in names.items():
                with self.subTest(variant=variant):
                    dist = build_platform("openai", Path(tmp), variant=variant)
                    plugin_dir = dist / PAYLOAD_DEST_SUBPATH
                    before = {name: (plugin_dir / name).read_bytes() for name in MANIFESTS}

                    with ZipFile(zip_plugin(dist, "openai", variant)) as archive:
                        for name, original in before.items():
                            expected = {**json.loads(original), "name": archive_name}
                            self.assertEqual(json.loads(archive.read(name)), expected, name)
                            self.assertEqual((plugin_dir / name).read_bytes(), original, name)


if __name__ == "__main__":
    unittest.main()

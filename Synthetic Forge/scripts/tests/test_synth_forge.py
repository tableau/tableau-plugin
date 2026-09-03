import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "synth_forge.py"
SPEC = importlib.util.spec_from_file_location("synth_forge", MODULE_PATH)
forge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(forge)


def profile() -> dict:
    return {
        "version": "1.0",
        "tables": [
            {
                "name": "customers",
                "rows": 12,
                "fields": [
                    {"name": "customer_id", "type": "id", "unique": True,
                     "generator": {"kind": "sequence", "prefix": "CUS-", "width": 4}},
                    {"name": "email", "type": "string", "unique": True,
                     "generator": {"kind": "synthetic_email"}},
                    {"name": "segment", "type": "string", "nullable_rate": 0.25,
                     "generator": {"kind": "categorical", "values": [
                         {"value": "Consumer", "weight": 3}, {"value": "Business", "weight": 1}
                     ]}}
                ]
            },
            {
                "name": "orders",
                "rows": 40,
                "fields": [
                    {"name": "order_id", "type": "id", "unique": True,
                     "generator": {"kind": "sequence", "prefix": "ORD-", "width": 5}},
                    {"name": "customer_id", "type": "id"},
                    {"name": "amount", "type": "float", "decimals": 2,
                     "generator": {"kind": "normal", "mean": 75, "stddev": 10, "min": 1, "max": 200},
                     "validation": {"mean_tolerance": 0.25}},
                    {"name": "ordered_on", "type": "date",
                     "generator": {"kind": "date_range", "start": "2025-01-01", "end": "2025-01-31"}}
                ]
            }
        ],
        "relationships": [{
            "parent_table": "customers", "parent_field": "customer_id",
            "child_table": "orders", "child_field": "customer_id"
        }],
        "privacy": {"forbidden_values_sha256": []}
    }


class ForgeTests(unittest.TestCase):
    def write_profile(self, root: Path, value: dict | None = None) -> Path:
        path = root / "profile.json"
        path.write_text(json.dumps(value or profile()), encoding="utf-8")
        return path

    def test_profile_rejects_raw_values(self):
        value = profile()
        value["tables"][0]["fields"][0]["source_values"] = ["real-id"]
        with self.assertRaisesRegex(forge.ForgeError, "prohibited raw-value key"):
            forge.normalize_profile(value)

    def test_profile_rejects_cycles(self):
        value = profile()
        value["tables"][0]["fields"][0]["unique"] = False
        value["relationships"].append({
            "parent_table": "orders", "parent_field": "order_id",
            "child_table": "customers", "child_field": "customer_id"
        })
        with self.assertRaisesRegex(forge.ForgeError, "cycle"):
            forge.normalize_profile(value)

    def test_profile_rejects_filename_collision_and_zero_mean_tolerance(self):
        value = profile()
        value["tables"][1]["name"] = "customer_s"
        value["tables"][0]["name"] = "customer s"
        value["relationships"] = []
        with self.assertRaisesRegex(forge.ForgeError, "filename normalization"):
            forge.normalize_profile(value)
        value = profile()
        amount = value["tables"][1]["fields"][2]
        amount["generator"]["mean"] = 0
        with self.assertRaisesRegex(forge.ForgeError, "zero mean"):
            forge.normalize_profile(value)

    def test_profile_rejects_predictably_invalid_generator_combinations(self):
        value = profile()
        value["tables"][0]["fields"][2]["unique"] = True
        with self.assertRaisesRegex(forge.ForgeError, "cannot guarantee uniqueness"):
            forge.normalize_profile(value)
        value = profile()
        value["tables"][0]["fields"][2]["generator"] = {"kind": "constant", "value": None}
        with self.assertRaisesRegex(forge.ForgeError, "null constant"):
            forge.normalize_profile(value)
        value = profile()
        value["tables"][1]["fields"][1]["type"] = "integer"
        with self.assertRaisesRegex(forge.ForgeError, "incompatible"):
            forge.normalize_profile(value)

    def test_generate_is_deterministic_and_idempotent_for_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self.write_profile(root)
            first = root / "first"
            second = root / "second"
            result1 = forge.generate_run(str(profile_path), str(first), "csv", 42)
            result2 = forge.generate_run(str(profile_path), str(second), "csv", 42)
            self.assertEqual(result1["fingerprint"], result2["fingerprint"])
            for filename in ("customers.csv", "orders.csv", "validation.json", "profile.normalized.json", "manifest.json", "GENLOG.md"):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())
            reused = forge.generate_run(str(profile_path), str(first), "csv", 42)
            self.assertEqual(reused["status"], "reused")
            self.assertTrue(forge.validate_run(str(profile_path), str(first))["ok"])

    def test_foreign_keys_are_valid_for_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self.write_profile(root)
            output = root / "json-run"
            forge.generate_run(str(profile_path), str(output), "json", 9)
            customers = json.loads((output / "customers.json").read_text())
            orders = json.loads((output / "orders.json").read_text())
            keys = {row["customer_id"] for row in customers}
            self.assertTrue(all(row["customer_id"] in keys for row in orders))

    def test_sqlite_export_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self.write_profile(root)
            output = root / "sqlite-run"
            forge.generate_run(str(profile_path), str(output), "sqlite", 5)
            with sqlite3.connect(output / "data.sqlite") as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM "orders"').fetchone()[0], 40)
                types = {row[1]: row[2] for row in connection.execute('PRAGMA table_info("orders")')}
                self.assertEqual(types["amount"], "REAL")
            self.assertTrue(forge.validate_run(str(profile_path), str(output))["ok"])

    def test_csv_null_encoding_preserves_empty_and_backslash_strings(self):
        for value in ("", r"\N", r"\leading", "ordinary"):
            self.assertEqual(forge._csv_decode(forge._csv_encode(value)), value)
        self.assertIsNone(forge._csv_decode(forge._csv_encode(None)))

    def test_privacy_hash_detects_leak(self):
        value = profile()
        prohibited = "Consumer"
        value["privacy"]["forbidden_values_sha256"] = [hashlib.sha256(prohibited.encode()).hexdigest()]
        normalized = forge.normalize_profile(value)
        data = forge.generate_data(normalized, 1)
        validation = forge.validate_data(normalized, data)
        self.assertFalse(validation["ok"])
        self.assertTrue(any(gate["gate"] == "privacy" and gate["status"] == "fail" for gate in validation["gates"]))

    def test_output_conflict_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self.write_profile(root)
            output = root / "existing"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("user data")
            with self.assertRaisesRegex(forge.ForgeError, "already exists") as caught:
                forge.generate_run(str(profile_path), str(output), "csv", 0)
            self.assertEqual(caught.exception.code, 20)
            self.assertEqual(marker.read_text(), "user data")

    def test_validation_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self.write_profile(root)
            output = root / "run"
            forge.generate_run(str(profile_path), str(output), "json", 7)
            rows = json.loads((output / "orders.json").read_text())
            rows[0]["customer_id"] = "NOT-A-PARENT"
            (output / "orders.json").write_text(json.dumps(rows))
            validation = forge.validate_run(str(profile_path), str(output))
            self.assertFalse(validation["ok"])
            self.assertTrue(any(gate["gate"] == "foreign_key" and gate["status"] == "fail" for gate in validation["gates"]))

    def test_manifest_hash_detects_semantically_valid_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = self.write_profile(root)
            output = root / "run"
            forge.generate_run(str(profile_path), str(output), "json", 3)
            path = output / "customers.json"
            rows = json.loads(path.read_text())
            path.write_text(json.dumps(rows, separators=(",", ":")))
            validation = forge.validate_run(str(profile_path), str(output))
            self.assertFalse(validation["ok"])
            self.assertTrue(any(gate["gate"] == "file_hash" and gate["status"] == "fail" for gate in validation["gates"]))
            with self.assertRaisesRegex(forge.ForgeError, "not a valid matching run"):
                forge.generate_run(str(profile_path), str(output), "json", 3)


if __name__ == "__main__":
    unittest.main()

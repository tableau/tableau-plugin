#!/usr/bin/env python3
"""Deterministic, profile-driven synthetic data generator using the stdlib."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

VERSION = "2.0.0"
SUPPORTED_FORMATS = ("csv", "json", "sqlite")
SUPPORTED_TYPES = {"string", "integer", "float", "boolean", "date", "datetime", "id"}
FORBIDDEN_PROFILE_KEYS = {"source_values", "raw_values", "sample_values"}
SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9 _-]{0,63}$")


class ForgeError(Exception):
    def __init__(self, message: str, code: int = 10):
        super().__init__(message)
        self.code = code


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_forbidden_key(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_PROFILE_KEYS:
                return f"{path}.{key}"
            found = _find_forbidden_key(child, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_forbidden_key(child, f"{path}[{index}]")
            if found:
                return found
    return None


def load_profile(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForgeError(f"cannot read profile: {exc}") from exc
    return normalize_profile(value)


def normalize_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ForgeError("profile root must be an object")
    forbidden = _find_forbidden_key(value)
    if forbidden:
        raise ForgeError(f"profile contains prohibited raw-value key: {forbidden}")
    if value.get("version") != "1.0":
        raise ForgeError('profile version must be "1.0"')
    tables = value.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ForgeError("profile.tables must be a non-empty array")

    normalized: dict[str, Any] = {"version": "1.0", "tables": [], "relationships": [], "privacy": {"forbidden_values_sha256": []}}
    table_names: set[str] = set()
    file_stems: set[str] = set()
    for table in tables:
        if not isinstance(table, dict):
            raise ForgeError("every table must be an object")
        name = table.get("name")
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
            raise ForgeError(f"invalid table name: {name!r}")
        key = name.casefold()
        if key in table_names:
            raise ForgeError(f"duplicate table name: {name}")
        table_names.add(key)
        stem = _file_stem(name).casefold()
        if stem in file_stems:
            raise ForgeError(f"table names collide after filename normalization: {name}")
        file_stems.add(stem)
        rows = table.get("rows")
        if not isinstance(rows, int) or isinstance(rows, bool) or rows <= 0:
            raise ForgeError(f"{name}.rows must be a positive integer")
        fields = table.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ForgeError(f"{name}.fields must be a non-empty array")
        out_fields = []
        field_names: set[str] = set()
        for field in fields:
            out_fields.append(_normalize_field(name, rows, field, field_names))
        normalized["tables"].append({"name": name, "rows": rows, "fields": out_fields})

    relationships = value.get("relationships", [])
    if not isinstance(relationships, list):
        raise ForgeError("relationships must be an array")
    lookup = {table["name"]: table for table in normalized["tables"]}
    child_slots: set[tuple[str, str]] = set()
    for relation in relationships:
        if not isinstance(relation, dict):
            raise ForgeError("every relationship must be an object")
        required = ("parent_table", "parent_field", "child_table", "child_field")
        if any(not isinstance(relation.get(key), str) for key in required):
            raise ForgeError("relationship fields must be strings")
        rel = {key: relation[key] for key in required}
        if rel["parent_table"] == rel["child_table"]:
            raise ForgeError("self-referential relationships are not supported")
        parent = lookup.get(rel["parent_table"])
        child = lookup.get(rel["child_table"])
        if parent is None or child is None:
            raise ForgeError(f"relationship references an unknown table: {rel}")
        parent_field = _field_by_name(parent, rel["parent_field"])
        child_field = _field_by_name(child, rel["child_field"])
        if not parent_field.get("unique") and not (parent_field["type"] == "id" and _guarantees_unique(parent_field["generator"])):
            raise ForgeError(f"relationship parent must guarantee unique values: {rel['parent_table']}.{rel['parent_field']}")
        if parent_field["nullable_rate"] == 1:
            raise ForgeError(f"relationship parent cannot be entirely null: {rel['parent_table']}.{rel['parent_field']}")
        if parent_field["type"] != child_field["type"] and {parent_field["type"], child_field["type"]} - {"id", "string"}:
            raise ForgeError(f"relationship field types are incompatible: {rel}")
        child_non_null = child["rows"] - round(child["rows"] * child_field["nullable_rate"])
        if child_field["unique"] and child_non_null > 1:
            raise ForgeError(f"relationship child cannot guarantee uniqueness: {rel['child_table']}.{rel['child_field']}")
        slot = (rel["child_table"], rel["child_field"])
        if slot in child_slots:
            raise ForgeError(f"multiple relationships target {slot[0]}.{slot[1]}")
        child_slots.add(slot)
        normalized["relationships"].append(rel)

    privacy = value.get("privacy", {})
    if privacy is None:
        privacy = {}
    if not isinstance(privacy, dict):
        raise ForgeError("privacy must be an object")
    hashes = privacy.get("forbidden_values_sha256", [])
    if not isinstance(hashes, list) or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item) for item in hashes):
        raise ForgeError("privacy.forbidden_values_sha256 must contain lowercase SHA-256 strings")
    normalized["privacy"] = {"forbidden_values_sha256": sorted(set(hashes))}
    _topological_tables(normalized)
    return normalized


def _normalize_field(table_name: str, rows: int, field: Any, seen: set[str]) -> dict[str, Any]:
    if not isinstance(field, dict):
        raise ForgeError(f"{table_name}: every field must be an object")
    name = field.get("name")
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
        raise ForgeError(f"invalid field name in {table_name}: {name!r}")
    key = name.casefold()
    if key in seen:
        raise ForgeError(f"duplicate field name in {table_name}: {name}")
    seen.add(key)
    field_type = field.get("type")
    if field_type not in SUPPORTED_TYPES:
        raise ForgeError(f"unsupported type for {table_name}.{name}: {field_type!r}")
    nullable_rate = field.get("nullable_rate", 0.0)
    if isinstance(nullable_rate, bool) or not isinstance(nullable_rate, (int, float)) or not 0 <= nullable_rate <= 1:
        raise ForgeError(f"nullable_rate must be between 0 and 1 for {table_name}.{name}")
    decimals = field.get("decimals", 0 if field_type == "integer" else 2)
    if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 12:
        raise ForgeError(f"decimals must be an integer from 0 to 12 for {table_name}.{name}")
    generator = field.get("generator") or _default_generator(field_type)
    if not isinstance(generator, dict) or not isinstance(generator.get("kind"), str):
        raise ForgeError(f"generator must be an object with kind for {table_name}.{name}")
    _validate_generator(table_name, name, field_type, generator)
    unique = bool(field.get("unique", False))
    non_null_count = rows - round(rows * float(nullable_rate))
    if unique and non_null_count > 1 and not _guarantees_unique(generator):
        raise ForgeError(f"generator {generator['kind']} cannot guarantee uniqueness for {table_name}.{name}")
    if generator["kind"] == "constant" and generator.get("value") is None and nullable_rate != 1:
        raise ForgeError(f"null constant requires nullable_rate 1 for {table_name}.{name}")
    validation = field.get("validation", {})
    if not isinstance(validation, dict):
        raise ForgeError(f"validation must be an object for {table_name}.{name}")
    tolerance = validation.get("mean_tolerance")
    if tolerance is not None and (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0):
        raise ForgeError(f"mean_tolerance must be non-negative for {table_name}.{name}")
    if tolerance is not None and generator.get("mean") == 0:
        raise ForgeError(f"fractional mean_tolerance is undefined for a zero mean in {table_name}.{name}")
    return {
        "name": name,
        "type": field_type,
        "nullable_rate": float(nullable_rate),
        "unique": unique,
        "decimals": decimals,
        "generator": generator,
        "validation": validation,
    }


def _default_generator(field_type: str) -> dict[str, Any]:
    defaults = {
        "string": {"kind": "sequence", "prefix": "Value-", "width": 6},
        "id": {"kind": "sequence", "prefix": "ID-", "width": 8},
        "integer": {"kind": "integer_uniform", "min": 0, "max": 100},
        "float": {"kind": "uniform", "min": 0.0, "max": 1.0},
        "boolean": {"kind": "boolean", "probability_true": 0.5},
        "date": {"kind": "date_range", "start": "2025-01-01", "end": "2025-12-31"},
        "datetime": {"kind": "datetime_range", "start": "2025-01-01T00:00:00", "end": "2025-12-31T23:59:59"},
    }
    return defaults[field_type]


def _validate_generator(table: str, field: str, field_type: str, generator: dict[str, Any]) -> None:
    kind = generator["kind"]
    allowed = {
        "sequence", "uuid", "categorical", "integer_uniform", "uniform", "normal", "lognormal",
        "boolean", "date_range", "datetime_range", "synthetic_name", "synthetic_email", "constant",
    }
    if kind not in allowed:
        raise ForgeError(f"unsupported generator for {table}.{field}: {kind}")
    compatible = {
        "sequence": {"id", "string", "integer"}, "uuid": {"id", "string"}, "categorical": SUPPORTED_TYPES,
        "integer_uniform": {"integer"}, "uniform": {"float", "integer"}, "normal": {"float", "integer"},
        "lognormal": {"float"}, "boolean": {"boolean"}, "date_range": {"date"},
        "datetime_range": {"datetime"}, "synthetic_name": {"string"}, "synthetic_email": {"string"},
        "constant": SUPPORTED_TYPES,
    }
    if field_type not in compatible[kind]:
        raise ForgeError(f"generator {kind} is incompatible with {table}.{field} type {field_type}")
    if kind == "categorical":
        _categorical_parts(generator, table, field)
    if kind in {"integer_uniform", "uniform"}:
        lo, hi = generator.get("min"), generator.get("max")
        if not _number(lo) or not _number(hi) or lo > hi:
            raise ForgeError(f"{kind} requires numeric min <= max for {table}.{field}")
        if kind == "integer_uniform" and (not isinstance(lo, int) or not isinstance(hi, int)):
            raise ForgeError(f"integer_uniform bounds must be integers for {table}.{field}")
    if kind == "normal" and (not _number(generator.get("mean")) or not _number(generator.get("stddev")) or generator["stddev"] <= 0):
        raise ForgeError(f"normal requires numeric mean and positive stddev for {table}.{field}")
    if kind == "lognormal" and (not _number(generator.get("mean")) or generator["mean"] <= 0 or not _number(generator.get("sigma")) or generator["sigma"] <= 0):
        raise ForgeError(f"lognormal requires positive mean and sigma for {table}.{field}")
    if kind in {"normal", "lognormal"} and ("min" in generator or "max" in generator):
        lo, hi = generator.get("min", -math.inf), generator.get("max", math.inf)
        if not _number(lo) and lo != -math.inf:
            raise ForgeError(f"{kind} min must be numeric for {table}.{field}")
        if not _number(hi) and hi != math.inf:
            raise ForgeError(f"{kind} max must be numeric for {table}.{field}")
        if lo > hi:
            raise ForgeError(f"{kind} requires min <= max for {table}.{field}")
    if kind == "boolean" and (not _number(generator.get("probability_true")) or not 0 <= generator["probability_true"] <= 1):
        raise ForgeError(f"boolean probability_true must be between 0 and 1 for {table}.{field}")
    if kind == "date_range":
        _parse_date_range(generator, table, field, False)
    if kind == "datetime_range":
        _parse_date_range(generator, table, field, True)
    if kind == "synthetic_email" and "domain" in generator:
        domain = generator["domain"]
        if not isinstance(domain, str) or not re.fullmatch(r"[A-Za-z0-9.-]+", domain):
            raise ForgeError(f"invalid synthetic email domain for {table}.{field}")
    if kind == "sequence":
        if not isinstance(generator.get("start", 1), int) or isinstance(generator.get("start", 1), bool):
            raise ForgeError(f"sequence start must be an integer for {table}.{field}")
        width = generator.get("width", 0)
        if not isinstance(width, int) or isinstance(width, bool) or width < 0:
            raise ForgeError(f"sequence width must be a non-negative integer for {table}.{field}")
        if field_type == "integer" and generator.get("prefix"):
            raise ForgeError(f"integer sequence cannot use a prefix for {table}.{field}")
    if kind == "constant" and generator.get("value") is not None and not _value_matches(generator.get("value"), field_type):
        raise ForgeError(f"constant value does not match {table}.{field} type {field_type}")
    if kind == "categorical":
        values, _ = _categorical_parts(generator, table, field)
        if any(value is None or not _value_matches(value, field_type) for value in values):
            raise ForgeError(f"categorical value does not match {table}.{field} type {field_type}")


def _guarantees_unique(generator: dict[str, Any]) -> bool:
    return generator.get("kind") in {"sequence", "uuid", "synthetic_name", "synthetic_email"}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_date_range(generator: dict[str, Any], table: str, field: str, with_time: bool) -> tuple[Any, Any]:
    parser = dt.datetime.fromisoformat if with_time else dt.date.fromisoformat
    try:
        start, end = parser(generator["start"]), parser(generator["end"])
    except (KeyError, TypeError, ValueError) as exc:
        label = "datetime" if with_time else "date"
        raise ForgeError(f"invalid ISO {label} range for {table}.{field}") from exc
    if start > end:
        raise ForgeError(f"range start exceeds end for {table}.{field}")
    return start, end


def _categorical_parts(generator: dict[str, Any], table: str, field: str) -> tuple[list[Any], list[float]]:
    entries = generator.get("values")
    if not isinstance(entries, list) or not entries:
        raise ForgeError(f"categorical values must be a non-empty array for {table}.{field}")
    values, weights = [], []
    for entry in entries:
        if isinstance(entry, dict):
            value, weight = entry.get("value"), entry.get("weight", 1.0)
        else:
            value, weight = entry, 1.0
        if not _number(weight) or weight <= 0:
            raise ForgeError(f"categorical weights must be positive for {table}.{field}")
        values.append(value)
        weights.append(float(weight))
    return values, weights


def _field_by_name(table: dict[str, Any], name: str) -> dict[str, Any]:
    for field in table["fields"]:
        if field["name"] == name:
            return field
    raise ForgeError(f"unknown field: {table['name']}.{name}")


def _topological_tables(profile: dict[str, Any]) -> list[str]:
    names = [table["name"] for table in profile["tables"]]
    incoming = {name: 0 for name in names}
    children = {name: [] for name in names}
    for rel in profile.get("relationships", []):
        parent, child = rel["parent_table"], rel["child_table"]
        incoming[child] += 1
        children[parent].append(child)
    ready = sorted(name for name, count in incoming.items() if count == 0)
    ordered = []
    while ready:
        name = ready.pop(0)
        ordered.append(name)
        for child in sorted(children[name]):
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
                ready.sort()
    if len(ordered) != len(names):
        raise ForgeError("relationships contain a cycle")
    return ordered


def run_fingerprint(profile: dict[str, Any], seed: int, output_format: str) -> str:
    return sha256_text(canonical_json({"engine": VERSION, "profile": profile, "seed": seed, "format": output_format}))


def derive_seed(seed: int, table: str, field: str) -> int:
    return int(sha256_text(f"{seed}:{table}:{field}")[:16], 16)


def generate_data(profile: dict[str, Any], seed: int) -> dict[str, list[dict[str, Any]]]:
    tables = {table["name"]: table for table in profile["tables"]}
    relation_by_child = {(rel["child_table"], rel["child_field"]): rel for rel in profile["relationships"]}
    generated: dict[str, list[dict[str, Any]]] = {}
    for table_name in _topological_tables(profile):
        table = tables[table_name]
        columns: dict[str, list[Any]] = {}
        for field in table["fields"]:
            relation = relation_by_child.get((table_name, field["name"]))
            rng = random.Random(derive_seed(seed, table_name, field["name"]))
            if relation:
                parent_values = [row[relation["parent_field"]] for row in generated[relation["parent_table"]] if row[relation["parent_field"]] is not None]
                if not parent_values:
                    raise ForgeError(f"relationship parent has no usable keys: {relation}", 30)
                values = [rng.choice(parent_values) for _ in range(table["rows"])]
            else:
                values = _generate_field(field, table["rows"], rng)
            null_count = round(table["rows"] * field["nullable_rate"])
            if null_count:
                for index in rng.sample(range(table["rows"]), null_count):
                    values[index] = None
            columns[field["name"]] = values
        generated[table_name] = [
            {field["name"]: columns[field["name"]][index] for field in table["fields"]}
            for index in range(table["rows"])
        ]
    return generated


def _generate_field(field: dict[str, Any], count: int, rng: random.Random) -> list[Any]:
    gen, kind = field["generator"], field["generator"]["kind"]
    decimals = field["decimals"]
    if kind == "sequence":
        start, prefix, width = int(gen.get("start", 1)), str(gen.get("prefix", "")), int(gen.get("width", 0))
        values = [start + index for index in range(count)]
        if field["type"] == "integer" and not prefix:
            return values
        return [f"{prefix}{value:0{width}d}" for value in values]
    if kind == "uuid":
        return [str(uuid.UUID(int=rng.getrandbits(128))) for _ in range(count)]
    if kind == "categorical":
        values, weights = _categorical_parts(gen, "profile", field["name"])
        return rng.choices(values, weights=weights, k=count)
    if kind == "integer_uniform":
        return [rng.randint(gen["min"], gen["max"]) for _ in range(count)]
    if kind == "uniform":
        values = [rng.uniform(gen["min"], gen["max"]) for _ in range(count)]
        return [_numeric_cast(value, field["type"], decimals) for value in values]
    if kind in {"normal", "lognormal"}:
        if kind == "normal":
            values = [rng.gauss(gen["mean"], gen["stddev"]) for _ in range(count)]
        else:
            mu = math.log(gen["mean"]) - (gen["sigma"] ** 2) / 2
            values = [rng.lognormvariate(mu, gen["sigma"]) for _ in range(count)]
        if "min" in gen:
            values = [max(gen["min"], value) for value in values]
        if "max" in gen:
            values = [min(gen["max"], value) for value in values]
        return [_numeric_cast(value, field["type"], decimals) for value in values]
    if kind == "boolean":
        return [rng.random() < gen["probability_true"] for _ in range(count)]
    if kind in {"date_range", "datetime_range"}:
        with_time = kind == "datetime_range"
        start, end = _parse_date_range(gen, "profile", field["name"], with_time)
        span = int((end - start).total_seconds()) if with_time else (end - start).days
        values = [start + (dt.timedelta(seconds=rng.randint(0, span)) if with_time else dt.timedelta(days=rng.randint(0, span))) for _ in range(count)]
        return [value.isoformat() for value in values]
    if kind == "synthetic_name":
        prefix = str(gen.get("prefix", "Person-"))
        return [f"{prefix}{index + 1:06d}" for index in range(count)]
    if kind == "synthetic_email":
        domain = gen.get("domain", "example.invalid")
        return [f"user-{index + 1:06d}@{domain}" for index in range(count)]
    if kind == "constant":
        return [gen.get("value") for _ in range(count)]
    raise ForgeError(f"unsupported generator: {kind}", 30)


def _numeric_cast(value: float, field_type: str, decimals: int) -> int | float:
    return int(round(value)) if field_type == "integer" else round(value, decimals)


def validate_data(profile: dict[str, Any], data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []
    failures = 0
    forbidden_hashes = set(profile["privacy"]["forbidden_values_sha256"])
    tables = {table["name"]: table for table in profile["tables"]}
    for table in profile["tables"]:
        rows = data.get(table["name"])
        ok = isinstance(rows, list) and len(rows) == table["rows"]
        gates.append(_gate("row_count", table["name"], ok, {"expected": table["rows"], "actual": len(rows) if isinstance(rows, list) else None}))
        failures += not ok
        if not isinstance(rows, list):
            continue
        for field in table["fields"]:
            values = [row.get(field["name"]) for row in rows]
            missing = sum(field["name"] not in row for row in rows)
            type_errors = sum(not _value_matches(value, field["type"]) for value in values if value is not None)
            ok = missing == 0 and type_errors == 0
            gates.append(_gate("type", f"{table['name']}.{field['name']}", ok, {"missing": missing, "type_errors": type_errors}))
            failures += not ok
            expected_nulls = round(table["rows"] * field["nullable_rate"])
            actual_nulls = sum(value is None for value in values)
            ok = expected_nulls == actual_nulls
            gates.append(_gate("null_count", f"{table['name']}.{field['name']}", ok, {"expected": expected_nulls, "actual": actual_nulls}))
            failures += not ok
            non_null = [value for value in values if value is not None]
            if field["unique"]:
                ok = len(non_null) == len({canonical_json(value) for value in non_null})
                gates.append(_gate("unique", f"{table['name']}.{field['name']}", ok, {"values": len(non_null)}))
                failures += not ok
            range_gate = _validate_range(field, non_null)
            if range_gate:
                range_gate["target"] = f"{table['name']}.{field['name']}"
                gates.append(range_gate)
                failures += range_gate["status"] == "fail"
            if forbidden_hashes:
                leaked = sum(sha256_text(str(value)) in forbidden_hashes for value in non_null)
                ok = leaked == 0
                gates.append(_gate("privacy", f"{table['name']}.{field['name']}", ok, {"forbidden_matches": leaked}))
                failures += not ok
    for rel in profile["relationships"]:
        parent = {row[rel["parent_field"]] for row in data[rel["parent_table"]] if row[rel["parent_field"]] is not None}
        child = [row[rel["child_field"]] for row in data[rel["child_table"]] if row[rel["child_field"]] is not None]
        invalid = sum(value not in parent for value in child)
        ok = invalid == 0
        target = f"{rel['child_table']}.{rel['child_field']}->{rel['parent_table']}.{rel['parent_field']}"
        gates.append(_gate("foreign_key", target, ok, {"invalid": invalid}))
        failures += not ok
    return {"ok": failures == 0, "failed_gates": failures, "gates": gates}


def _gate(name: str, target: str, ok: bool, detail: dict[str, Any]) -> dict[str, Any]:
    return {"gate": name, "target": target, "status": "pass" if ok else "fail", "detail": detail}


def _value_matches(value: Any, field_type: str) -> bool:
    if field_type in {"string", "id"}:
        return isinstance(value, str)
    if field_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == "float":
        return _number(value)
    if field_type == "boolean":
        return isinstance(value, bool)
    try:
        (dt.date.fromisoformat if field_type == "date" else dt.datetime.fromisoformat)(value)
        return isinstance(value, str)
    except (TypeError, ValueError):
        return False


def _validate_range(field: dict[str, Any], values: list[Any]) -> dict[str, Any] | None:
    gen = field["generator"]
    if not values or field["type"] not in {"integer", "float"}:
        return None
    detail: dict[str, Any] = {"actual_min": min(values), "actual_max": max(values)}
    ok = True
    if "min" in gen:
        detail["expected_min"] = gen["min"]
        ok = ok and min(values) >= gen["min"]
    if "max" in gen:
        detail["expected_max"] = gen["max"]
        ok = ok and max(values) <= gen["max"]
    tolerance = field["validation"].get("mean_tolerance")
    if tolerance is not None and "mean" in gen:
        actual_mean = sum(values) / len(values)
        detail.update({"target_mean": gen["mean"], "actual_mean": actual_mean, "mean_tolerance": tolerance})
        ok = ok and abs(actual_mean - gen["mean"]) / abs(gen["mean"]) <= tolerance
    return _gate("numeric_constraints", field["name"], ok, detail)


def export_data(profile: dict[str, Any], data: dict[str, list[dict[str, Any]]], destination: Path, output_format: str) -> list[Path]:
    files: list[Path] = []
    if output_format == "sqlite":
        path = destination / "data.sqlite"
        connection = sqlite3.connect(path)
        try:
            for table_name, rows in data.items():
                columns = list(rows[0])
                table_profile = next(table for table in profile["tables"] if table["name"] == table_name)
                field_types = {field["name"]: field["type"] for field in table_profile["fields"]}
                schema = ", ".join(_quote(column) + " " + _sqlite_type(field_types[column]) for column in columns)
                connection.execute(f"CREATE TABLE {_quote(table_name)} ({schema})")
                placeholders = ",".join("?" for _ in columns)
                connection.executemany(
                    f"INSERT INTO {_quote(table_name)} VALUES ({placeholders})",
                    [[_serialize_scalar(row[column]) for column in columns] for row in rows],
                )
            connection.commit()
        finally:
            connection.close()
        return [path]
    for table_name, rows in data.items():
        stem = _file_stem(table_name)
        if output_format == "csv":
            path = destination / f"{stem}.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows({key: _csv_encode(value) for key, value in row.items()} for row in rows)
        elif output_format == "json":
            path = destination / f"{stem}.json"
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            raise ForgeError(f"unsupported format: {output_format}", 50)
        files.append(path)
    return files


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _file_stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "table"


def _serialize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _sqlite_type(field_type: str) -> str:
    if field_type in {"integer", "boolean"}:
        return "INTEGER"
    if field_type == "float":
        return "REAL"
    return "TEXT"


def _csv_encode(value: Any) -> str:
    if value is None:
        return r"\N"
    rendered = "true" if value is True else "false" if value is False else str(value)
    return "\\" + rendered if rendered.startswith("\\") else rendered


def _csv_decode(value: str) -> str | None:
    if value == r"\N":
        return None
    return value[1:] if value.startswith("\\") else value


def load_export(profile: dict[str, Any], data_dir: Path, output_format: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    if output_format == "sqlite":
        connection = sqlite3.connect(data_dir / "data.sqlite")
        try:
            for table in profile["tables"]:
                fields = table["fields"]
                cursor = connection.execute(f"SELECT * FROM {_quote(table['name'])}")
                result[table["name"]] = [
                    {field["name"]: _parse_scalar(value, field["type"]) for field, value in zip(fields, row)}
                    for row in cursor.fetchall()
                ]
        finally:
            connection.close()
        return result
    for table in profile["tables"]:
        fields = table["fields"]
        path = data_dir / f"{_file_stem(table['name'])}.{output_format}"
        if output_format == "json":
            rows = json.loads(path.read_text(encoding="utf-8"))
            result[table["name"]] = rows
        else:
            with path.open(encoding="utf-8", newline="") as handle:
                result[table["name"]] = [
                    {field["name"]: _parse_scalar(_csv_decode(row[field["name"]]), field["type"]) for field in fields}
                    for row in csv.DictReader(handle)
                ]
    return result


def _parse_scalar(value: Any, field_type: str) -> Any:
    if value is None or value == "":
        return None
    if field_type == "integer":
        return int(value)
    if field_type == "float":
        return float(value)
    if field_type == "boolean":
        if value in (True, "true", "True", "1", 1):
            return True
        if value in (False, "false", "False", "0", 0):
            return False
        return value
    return value


def generate_run(profile_path: str, output_path: str, output_format: str, seed: int) -> dict[str, Any]:
    profile = load_profile(profile_path)
    output = Path(output_path).resolve()
    fingerprint = run_fingerprint(profile, seed, output_format)
    if output.exists():
        manifest_path = output / "manifest.json"
        try:
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("fingerprint") == fingerprint and manifest.get("format") == output_format:
                    validation = validate_run(profile_path, str(output))
                    if validation["ok"]:
                        return {"status": "reused", "output": str(output), "fingerprint": fingerprint, "validation": validation}
        except (ForgeError, OSError, KeyError, json.JSONDecodeError, sqlite3.Error, ValueError):
            pass
        raise ForgeError(f"output directory already exists and is not a valid matching run: {output}", 20)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        data = generate_data(profile, seed)
        files = export_data(profile, data, stage, output_format)
        validation = validate_data(profile, load_export(profile, stage, output_format))
        (stage / "validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
        (stage / "profile.normalized.json").write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
        if not validation["ok"]:
            raise ForgeError(f"validation failed; staged data retained at {stage}", 40)
        file_records = [{"path": path.name, "sha256": file_hash(path)} for path in sorted(files)]
        manifest = {"engine_version": VERSION, "fingerprint": fingerprint, "seed": seed, "format": output_format, "tables": {name: len(rows) for name, rows in data.items()}, "files": file_records}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        genlog = ["# Synthetic Forge Run", "", f"- Fingerprint: `{fingerprint}`", f"- Seed: `{seed}`", f"- Format: `{output_format}`", "- Validation: `pass`", "", "## Tables", ""]
        genlog.extend(f"- `{name}`: {len(rows)} rows" for name, rows in data.items())
        (stage / "GENLOG.md").write_text("\n".join(genlog) + "\n", encoding="utf-8")
        os.replace(stage, output)
        return {"status": "created", "output": str(output), "fingerprint": fingerprint, "validation": validation}
    except ForgeError:
        raise
    except Exception as exc:
        raise ForgeError(f"generation failed; staged data retained at {stage}: {exc}", 30) from exc


def validate_run(profile_path: str, data_path: str) -> dict[str, Any]:
    profile = load_profile(profile_path)
    root = Path(data_path)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        output_format = manifest["format"]
        if output_format not in SUPPORTED_FORMATS:
            raise ForgeError(f"manifest contains unsupported format: {output_format}", 40)
        seed = manifest["seed"]
        expected_fingerprint = run_fingerprint(profile, seed, output_format)
        fingerprint_ok = manifest.get("fingerprint") == expected_fingerprint
        manifest_gates = [_gate("fingerprint", "manifest.json", fingerprint_ok, {"expected": expected_fingerprint, "actual": manifest.get("fingerprint")})]
        manifest_gates.extend(_verify_manifest_files(root, manifest.get("files")))
        validation = validate_data(profile, load_export(profile, root, output_format))
        validation["gates"] = manifest_gates + validation["gates"]
        manifest_failures = sum(gate["status"] == "fail" for gate in manifest_gates)
        validation["failed_gates"] += manifest_failures
        validation["ok"] = validation["failed_gates"] == 0
    except (OSError, KeyError, json.JSONDecodeError, sqlite3.Error, ValueError) as exc:
        raise ForgeError(f"cannot validate output: {exc}", 40) from exc
    return validation


def _verify_manifest_files(root: Path, records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list) or not records:
        return [_gate("file_hash", "manifest.json", False, {"error": "missing file records"})]
    gates = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not isinstance(record.get("sha256"), str):
            gates.append(_gate("file_hash", "manifest.json", False, {"error": "invalid file record"}))
            continue
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
            gates.append(_gate("file_hash", record["path"], False, {"error": "unsafe file path"}))
            continue
        path = root / relative
        actual = file_hash(path) if path.is_file() else None
        gates.append(_gate("file_hash", record["path"], actual == record["sha256"], {"expected": record["sha256"], "actual": actual}))
    return gates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("profile-check", help="validate and normalize a profile")
    check.add_argument("--profile", required=True)
    generate = sub.add_parser("generate", help="generate and validate a synthetic dataset")
    generate.add_argument("--profile", required=True)
    generate.add_argument("--output", required=True)
    generate.add_argument("--format", choices=SUPPORTED_FORMATS, default="csv")
    generate.add_argument("--seed", type=int, default=0)
    validate = sub.add_parser("validate", help="read generated files back and validate them")
    validate.add_argument("--profile", required=True)
    validate.add_argument("--data", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "profile-check":
            payload = {"ok": True, "profile": load_profile(args.profile)}
        elif args.command == "generate":
            payload = generate_run(args.profile, args.output, args.format, args.seed)
        else:
            validation = validate_run(args.profile, args.data)
            payload = validation
            if not validation["ok"]:
                print(json.dumps(payload, indent=2), file=sys.stderr)
                return 40
        print(json.dumps(payload, indent=2))
        return 0
    except ForgeError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "exit_code": exc.code}), file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())

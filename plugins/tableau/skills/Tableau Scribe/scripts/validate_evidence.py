#!/usr/bin/env python3
"""Validate and normalize a Tableau Scribe evidence ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ARTIFACT_TYPES = {"dashboard_documentation", "datasource_dictionary"}
TARGET_KINDS = {"view", "workbook", "datasource"}
SOURCE_TYPES = {"user_provided", "view_image", "view_metadata", "workbook_metadata", "datasource_metadata", "lineage", "queried_data"}
STATUSES = {"observed", "inferred", "unknown"}
TOP_KEYS = {"artifact_type", "query_authorized", "target", "sources", "records"}
TARGET_KEYS = {"id", "name", "kind"}
SOURCE_KEYS = {"id", "type", "scope"}
RECORD_KEYS = {"id", "subject", "attribute", "value", "status", "sources", "note"}


class InputError(ValueError):
    """Raised when a ledger violates the evidence contract."""


def require_text(value: Any, label: str, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise InputError(f"{label} exceeds {maximum} characters")
    return value


def require_keys(item: Any, required: set[str], allowed: set[str], label: str) -> None:
    if not isinstance(item, dict):
        raise InputError(f"{label} must be an object")
    missing, extra = required - set(item), set(item) - allowed
    if missing:
        raise InputError(f"{label} missing keys: {sorted(missing)}")
    if extra:
        raise InputError(f"{label} has unknown keys: {sorted(extra)}")


def valid_value(value: Any) -> bool:
    scalar = value is None or isinstance(value, (str, int, float, bool))
    sequence = isinstance(value, list) and len(value) <= 20 and all(item is not None and isinstance(item, (str, int, float, bool)) for item in value)
    return scalar or sequence


def validate(payload: Any) -> dict[str, Any]:
    require_keys(payload, TOP_KEYS, TOP_KEYS, "input")
    artifact_type = payload["artifact_type"]
    if artifact_type not in ARTIFACT_TYPES:
        raise InputError(f"artifact_type must be one of {sorted(ARTIFACT_TYPES)}")
    query_authorized = payload["query_authorized"]
    if not isinstance(query_authorized, bool):
        raise InputError("query_authorized must be boolean")

    target_raw = payload["target"]
    require_keys(target_raw, TARGET_KEYS, TARGET_KEYS, "target")
    target_id = target_raw["id"]
    if target_id is not None:
        target_id = require_text(target_id, "target.id", 128)
    kind = target_raw["kind"]
    if kind not in TARGET_KINDS:
        raise InputError(f"target.kind must be one of {sorted(TARGET_KINDS)}")
    target = {"id": target_id, "name": require_text(target_raw["name"], "target.name"), "kind": kind}

    if not isinstance(payload["sources"], list) or not isinstance(payload["records"], list):
        raise InputError("sources and records must be arrays")
    sources, source_ids, source_type_by_id = [], set(), {}
    for index, item in enumerate(payload["sources"]):
        label = f"sources[{index}]"
        require_keys(item, SOURCE_KEYS, SOURCE_KEYS, label)
        source_id = require_text(item["id"], f"{label}.id", 128)
        if source_id in source_ids:
            raise InputError(f"duplicate source id: {source_id}")
        source_type = item["type"]
        if source_type not in SOURCE_TYPES:
            raise InputError(f"{label}.type must be one of {sorted(SOURCE_TYPES)}")
        if source_type == "queried_data" and not query_authorized:
            raise InputError("queried_data source requires query_authorized=true")
        source_ids.add(source_id)
        source_type_by_id[source_id] = source_type
        sources.append({"id": source_id, "type": source_type, "scope": require_text(item["scope"], f"{label}.scope")})

    records, record_ids, claims, referenced_sources = [], set(), set(), set()
    for index, item in enumerate(payload["records"]):
        label = f"records[{index}]"
        require_keys(item, RECORD_KEYS - {"note"}, RECORD_KEYS, label)
        record_id = require_text(item["id"], f"{label}.id", 128)
        if record_id in record_ids:
            raise InputError(f"duplicate record id: {record_id}")
        record_ids.add(record_id)
        subject = require_text(item["subject"], f"{label}.subject")
        attribute = require_text(item["attribute"], f"{label}.attribute")
        claim_key = (subject.casefold(), attribute.casefold())
        if claim_key in claims:
            raise InputError(f"duplicate subject/attribute claim: {subject} / {attribute}")
        claims.add(claim_key)
        status = item["status"]
        if status not in STATUSES:
            raise InputError(f"{label}.status must be one of {sorted(STATUSES)}")
        if not valid_value(item["value"]):
            raise InputError(f"{label}.value must be a scalar or an array of at most 20 scalars")
        record_sources = item["sources"]
        if not isinstance(record_sources, list) or any(not isinstance(value, str) for value in record_sources):
            raise InputError(f"{label}.sources must be an array of source IDs")
        if len(set(record_sources)) != len(record_sources):
            raise InputError(f"{label}.sources must not contain duplicates")
        unknown_sources = set(record_sources) - source_ids
        if unknown_sources:
            raise InputError(f"{label} references unknown sources: {sorted(unknown_sources)}")
        note = item.get("note")
        if note is not None:
            note = require_text(note, f"{label}.note")
        if status == "observed" and (item["value"] is None or not record_sources):
            raise InputError(f"{label} observed claims require a value and source")
        if status == "inferred" and (item["value"] is None or not record_sources or not note):
            raise InputError(f"{label} inferred claims require a value, source, and note")
        if status == "unknown" and (item["value"] is not None or record_sources or not note):
            raise InputError(f"{label} unknown claims require null value, no sources, and a note")
        referenced_sources.update(record_sources)
        records.append({"id": record_id, "subject": subject, "attribute": attribute, "value": item["value"], "status": status, "sources": record_sources, **({"note": note} if note else {})})

    unreferenced = source_ids - referenced_sources
    if unreferenced:
        raise InputError(f"unreferenced sources: {sorted(unreferenced)}")
    return {
        "artifact_type": artifact_type,
        "query_authorized": query_authorized,
        "target": target,
        "sources": sources,
        "records": records,
        "summary": {
            "records_by_status": {status: sum(item["status"] == status for item in records) for status in sorted(STATUSES)},
            "sources_by_type": {source_type: sum(item["type"] == source_type for item in sources) for source_type in sorted(set(source_type_by_id.values()))},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="evidence ledger JSON")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    args = parser.parse_args()
    try:
        with args.input.open(encoding="utf-8") as handle:
            result = validate(json.load(handle))
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    json.dump(result, sys.stdout, indent=2 if args.pretty else None, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

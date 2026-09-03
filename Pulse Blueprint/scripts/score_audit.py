#!/usr/bin/env python3
"""Validate and score normalized Tableau Pulse audit findings."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

VERSION = "1.0"
STATUSES = {"assessed", "partial", "failed"}
SEVERITIES = ("low", "medium", "high", "critical")
PENALTIES = {"low": 0.5, "medium": 2, "high": 5, "critical": 10}
TOP_KEYS = {"methodology_version", "definitions", "findings"}
REQUIRED_FINDING = {"definition_id", "rule_id", "evidence_key", "severity", "summary"}


class InputError(ValueError):
    """Raised when an audit document violates the contract."""


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label} must be a non-empty string")
    return value.strip()


def grade(score: float) -> str:
    bands = ((97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"),
             (80, "B-"), (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"),
             (63, "D"), (60, "D-"))
    return next((label for threshold, label in bands if score >= threshold), "F")


def parse(payload: Any) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise InputError("input must be a JSON object")
    extra = set(payload) - TOP_KEYS
    if extra:
        raise InputError(f"unknown top-level keys: {sorted(extra)}")
    if payload.get("methodology_version") != VERSION:
        raise InputError(f"methodology_version must be {VERSION}")
    definitions_raw, findings_raw = payload.get("definitions"), payload.get("findings")
    if not isinstance(definitions_raw, list) or not isinstance(findings_raw, list):
        raise InputError("definitions and findings must be arrays")

    definitions, ids = [], set()
    for index, item in enumerate(definitions_raw):
        if not isinstance(item, dict):
            raise InputError(f"definitions[{index}] must be an object")
        extra_definition = set(item) - {"id", "name", "status"}
        if extra_definition:
            raise InputError(f"definitions[{index}] has unknown keys: {sorted(extra_definition)}")
        definition_id = require_text(item.get("id"), f"definitions[{index}].id")
        if definition_id in ids:
            raise InputError(f"duplicate definition id: {definition_id}")
        status = item.get("status", "assessed")
        if status not in STATUSES:
            raise InputError(f"definitions[{index}].status must be one of {sorted(STATUSES)}")
        ids.add(definition_id)
        definitions.append({"id": definition_id, "name": require_text(item.get("name"), f"definitions[{index}].name"), "status": status})

    status_by_id = {item["id"]: item["status"] for item in definitions}
    findings = []
    for index, item in enumerate(findings_raw):
        if not isinstance(item, dict):
            raise InputError(f"findings[{index}] must be an object")
        missing = REQUIRED_FINDING - set(item)
        extra_finding = set(item) - REQUIRED_FINDING - {"observation"}
        if missing:
            raise InputError(f"findings[{index}] missing keys: {sorted(missing)}")
        if extra_finding:
            raise InputError(f"findings[{index}] has unknown keys: {sorted(extra_finding)}")
        definition_id = require_text(item["definition_id"], f"findings[{index}].definition_id")
        if definition_id not in status_by_id:
            raise InputError(f"findings[{index}] references unknown definition: {definition_id}")
        if status_by_id[definition_id] == "failed":
            raise InputError(f"findings[{index}] cannot reference a failed definition")
        severity = require_text(item["severity"], f"findings[{index}].severity").lower()
        if severity not in SEVERITIES:
            raise InputError(f"findings[{index}].severity must be one of {list(SEVERITIES)}")
        observation = item.get("observation", False)
        if not isinstance(observation, bool):
            raise InputError(f"findings[{index}].observation must be boolean")
        findings.append({
            "definition_id": definition_id,
            "rule_id": require_text(item["rule_id"], f"findings[{index}].rule_id"),
            "evidence_key": require_text(item["evidence_key"], f"findings[{index}].evidence_key"),
            "severity": severity,
            "summary": require_text(item["summary"], f"findings[{index}].summary"),
            "observation": observation,
        })
    return definitions, findings


def score(payload: Any) -> dict[str, Any]:
    definitions, findings = parse(payload)
    observations = [item for item in findings if item["observation"]]
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in (item for item in findings if not item["observation"]):
        key = (item["definition_id"], item["rule_id"], item["evidence_key"])
        current = deduped.get(key)
        if current is None or SEVERITIES.index(item["severity"]) > SEVERITIES.index(current["severity"]):
            deduped[key] = item
    scored_findings = list(deduped.values())

    results, composite_values = [], []
    for definition in definitions:
        if definition["status"] == "failed":
            results.append({**definition, "score": None, "grade": None, "provisional": False, "finding_count": 0})
            continue
        own = [item for item in scored_findings if item["definition_id"] == definition["id"]]
        value = max(0.0, 100.0 - sum(PENALTIES[item["severity"]] for item in own))
        provisional = definition["status"] == "partial"
        if not provisional:
            composite_values.append(value)
        results.append({**definition, "score": value, "grade": grade(value), "provisional": provisional, "finding_count": len(own)})

    overall = round(sum(composite_values) / len(composite_values), 2) if composite_values else None
    return {
        "methodology_version": VERSION,
        "coverage": {status: sum(item["status"] == status for item in definitions) for status in sorted(STATUSES)},
        "overall_score": overall,
        "overall_grade": grade(overall) if overall is not None else None,
        "definitions": results,
        "findings": scored_findings,
        "observations": observations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="normalized Pulse audit JSON")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    args = parser.parse_args()
    try:
        with args.input.open(encoding="utf-8") as handle:
            result = score(json.load(handle))
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    json.dump(result, sys.stdout, indent=2 if args.pretty else None, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

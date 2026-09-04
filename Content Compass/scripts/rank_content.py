#!/usr/bin/env python3
"""Rank normalized Tableau content metadata against a business query."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


CONTENT_TYPES = {"view", "workbook", "datasource", "project", "pulse_metric"}
TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize(value: str) -> str:
    return " ".join(TOKEN_RE.findall(value.casefold()))


def phrases(values: Any, label: str, required: bool = False) -> list[str]:
    if values is None and not required:
        return []
    if not isinstance(values, list) or any(not isinstance(item, str) or not normalize(item) for item in values):
        raise ValueError(f"{label} must be a list of non-empty strings")
    normalized = list(dict.fromkeys(normalize(item) for item in values))
    if required and not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def word_match(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {normalize(text)} "


def substring_match(text: str, phrase: str) -> bool:
    return phrase.replace(" ", "") in normalize(text).replace(" ", "")


def parse_timestamp(value: Any, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 string") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def field_names(candidate: dict[str, Any], label: str) -> list[str]:
    values = candidate.get("fields", [])
    if not isinstance(values, list):
        raise ValueError(f"{label}.fields must be a list")
    names = []
    for index, value in enumerate(values):
        if isinstance(value, str):
            name = value
        elif isinstance(value, dict) and isinstance(value.get("name"), str):
            name = value["name"]
        else:
            raise ValueError(f"{label}.fields[{index}] must be a string or object with a string name")
        if normalize(name):
            names.append(name)
    return names


def validate_candidate(candidate: Any, index: int) -> dict[str, Any]:
    label = f"candidates[{index}]"
    if not isinstance(candidate, dict):
        raise ValueError(f"{label} must be an object")
    for key in ("id", "type", "name"):
        if not isinstance(candidate.get(key), str) or not candidate[key].strip():
            raise ValueError(f"{label}.{key} must be a non-empty string")
    if candidate["type"] not in CONTENT_TYPES:
        raise ValueError(f"{label}.type must be one of {sorted(CONTENT_TYPES)}")
    for key in ("description", "project", "workbook", "owner", "url"):
        if key in candidate and candidate[key] is not None and not isinstance(candidate[key], str):
            raise ValueError(f"{label}.{key} must be a string")
    tags = candidate.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError(f"{label}.tags must be a list of strings")
    for key in ("has_date_field", "certified"):
        if key in candidate and not isinstance(candidate[key], bool):
            raise ValueError(f"{label}.{key} must be boolean")
    usage = candidate.get("usage_count")
    if usage is not None and (isinstance(usage, bool) or not isinstance(usage, int) or usage < 0):
        raise ValueError(f"{label}.usage_count must be a non-negative integer")
    candidate = dict(candidate)
    candidate["_fields"] = field_names(candidate, label)
    candidate["_updated"] = parse_timestamp(candidate.get("updated_at"), f"{label}.updated_at")
    return candidate


def usage_thresholds(candidates: list[dict[str, Any]]) -> dict[str, int]:
    groups: dict[str, list[int]] = defaultdict(list)
    for candidate in candidates:
        if candidate["type"] == "view" and candidate.get("usage_count") is not None:
            groups[candidate.get("project") or ""].append(candidate["usage_count"])
    thresholds = {}
    for project, values in groups.items():
        if len(values) >= 4:
            ordered = sorted(values, reverse=True)
            top_count = math.ceil(len(ordered) * 0.25)
            thresholds[project] = ordered[top_count - 1]
    return thresholds


def signal(signal_id: str, points: int, evidence: str) -> dict[str, Any]:
    return {"id": signal_id, "points": points, "evidence": evidence}


def rank(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("input must be an object")
    query = payload.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be an object")
    terms = phrases(query.get("terms"), "query.terms", required=True)
    synonyms = phrases(query.get("synonyms"), "query.synonyms")
    implied = phrases(query.get("implied_terms"), "query.implied_terms")
    temporal = query.get("temporal", False)
    if not isinstance(temporal, bool):
        raise ValueError("query.temporal must be boolean")

    max_per_tier = payload.get("max_per_tier", 3)
    if isinstance(max_per_tier, bool) or not isinstance(max_per_tier, int) or not 1 <= max_per_tier <= 3:
        raise ValueError("max_per_tier must be an integer from 1 to 3")

    as_of_value = payload.get("as_of")
    as_of: date | None = None
    if as_of_value is not None:
        if not isinstance(as_of_value, str):
            raise ValueError("as_of must be YYYY-MM-DD")
        try:
            as_of = date.fromisoformat(as_of_value)
        except ValueError as exc:
            raise ValueError("as_of must be YYYY-MM-DD") from exc

    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("candidates must be a list")
    candidates = [validate_candidate(item, index) for index, item in enumerate(raw_candidates)]
    ids = [candidate["id"] for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate ids must be unique; merge duplicate evidence before ranking")

    thresholds = usage_thresholds(candidates)
    ranked = []
    warnings = []
    if as_of is None and any(candidate["_updated"] is not None for candidate in candidates):
        warnings.append("as_of omitted; recency signal was not applied")

    for candidate in candidates:
        signals = []
        name = candidate["name"]
        primary_boundary = next((term for term in terms if word_match(name, term)), None)
        primary_substring = next((term for term in terms if substring_match(name, term)), None)
        synonym_boundary = next((term for term in synonyms if word_match(name, term)), None)
        if primary_boundary:
            signals.append(signal("name-primary-word", 30, f"name matches '{primary_boundary}' at a word boundary"))
        elif primary_substring:
            signals.append(signal("name-primary-substring", 15, f"name contains '{primary_substring}' as a substring"))
        elif synonym_boundary:
            signals.append(signal("name-synonym-word", 15, f"name matches related term '{synonym_boundary}'"))

        primary_field = next(
            (term for term in terms if any(word_match(field, term) for field in candidate["_fields"])),
            None,
        )
        related_field = next(
            (term for term in implied + synonyms if any(word_match(field, term) for field in candidate["_fields"])),
            None,
        )
        if primary_field:
            signals.append(signal("field-primary", 25, f"field metadata matches '{primary_field}'"))
        elif related_field:
            signals.append(signal("field-related", 15, f"field metadata matches related term '{related_field}'"))

        description = candidate.get("description") or ""
        if any(word_match(description, term) for term in terms + synonyms):
            signals.append(signal("description", 20, "description matches the query concepts"))

        tags = candidate.get("tags", [])
        if any(word_match(tag, term) for tag in tags for term in terms + synonyms):
            signals.append(signal("tag", 10, "tag metadata matches the query concepts"))

        pulse_evidence = [name, description, *candidate["_fields"]]
        if candidate["type"] == "pulse_metric" and any(
            word_match(value, term) for value in pulse_evidence for term in terms + synonyms + implied
        ):
            signals.append(signal("pulse-definition", 20, "Pulse definition matches the requested metric concept"))

        if temporal and candidate.get("has_date_field", False):
            signals.append(signal("temporal", 10, "date capability supports the temporal question"))

        project_key = candidate.get("project") or ""
        if (
            candidate["type"] == "view"
            and project_key in thresholds
            and candidate.get("usage_count") is not None
            and candidate["usage_count"] >= thresholds[project_key]
        ):
            signals.append(signal("usage-top-quartile", 5, "usage is in the top quartile of comparable project views"))

        updated = candidate["_updated"]
        if as_of is not None and updated is not None:
            age = (as_of - updated.date()).days
            if 0 <= age <= 90:
                signals.append(signal("recent", 5, f"updated {age} days before as_of"))

        score = min(100, sum(item["points"] for item in signals))
        if score < 15:
            continue
        tier = "High" if score >= 60 else "Medium" if score >= 35 else "Low"
        top_signals = sorted(signals, key=lambda item: (-item["points"], item["id"]))[:2]
        public_candidate = {key: value for key, value in candidate.items() if not key.startswith("_")}
        ranked.append({
            "candidate": public_candidate,
            "score": score,
            "tier": tier,
            "signals": signals,
            "top_signals": top_signals,
        })

    ranked.sort(key=lambda item: item["candidate"]["name"].casefold())
    ranked.sort(key=lambda item: bool(item["candidate"].get("certified", False)), reverse=True)
    ranked.sort(
        key=lambda item: (
            parse_timestamp(item["candidate"].get("updated_at"), "candidate.updated_at").timestamp()
            if item["candidate"].get("updated_at")
            else float("-inf")
        ),
        reverse=True,
    )
    ranked.sort(key=lambda item: item["candidate"].get("usage_count", -1), reverse=True)
    ranked.sort(key=lambda item: item["score"], reverse=True)
    tiers = {"High": [], "Medium": [], "Low": []}
    tier_totals = {"High": 0, "Medium": 0, "Low": 0}
    for item in ranked:
        tier_totals[item["tier"]] += 1
        if len(tiers[item["tier"]]) < max_per_tier:
            tiers[item["tier"]].append(item)

    return {
        "query": query,
        "total_candidates": len(candidates),
        "qualified_candidates": len(ranked),
        "tier_totals": tier_totals,
        "tiers": tiers,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="normalized candidate JSON")
    parser.add_argument("--output", help="optional output JSON path")
    args = parser.parse_args()
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = rank(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate and score normalized Tableau governance scan JSON."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


DOMAINS = {"modification_age", "adoption", "trust_lineage", "naming", "structure", "performance", "metadata"}
SEVERITY_SCORE = {"LOW": 90.0, "MEDIUM": 75.0, "HIGH": 50.0, "CRITICAL": 0.0}
STATUSES = {"assessed", "partial", "failed"}


def grade(score: float) -> str:
    bands = [(97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
             (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"), (63, "D"), (60, "D-"), (0, "F")]
    return next(label for minimum, label in bands if score >= minimum)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def score_scan(payload: dict[str, Any]) -> dict[str, Any]:
    entities, findings = payload.get("entities"), payload.get("findings")
    require(isinstance(entities, list), "entities must be an array")
    require(isinstance(findings, list), "findings must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    status_counts = defaultdict(int)
    for index, entity in enumerate(entities):
        require(isinstance(entity, dict), f"entities[{index}] must be an object")
        entity_id = entity.get("id")
        require(isinstance(entity_id, str) and entity_id, f"entities[{index}].id is required")
        require(entity_id not in by_id, f"duplicate entity id: {entity_id}")
        status = entity.get("status")
        require(status in STATUSES, f"invalid status for {entity_id}: {status}")
        applicable = entity.get("applicable_domains")
        require(isinstance(applicable, list) and applicable, f"applicable_domains required for {entity_id}")
        require(set(applicable) <= DOMAINS, f"unknown domain for {entity_id}")
        require(len(applicable) == len(set(applicable)), f"duplicate applicable domain for {entity_id}")
        include = entity.get("include_in_score")
        require(isinstance(include, bool), f"include_in_score must be boolean for {entity_id}")
        if include:
            require(status == "assessed", f"only assessed entities may be included: {entity_id}")
        by_id[entity_id], status_counts[status] = entity, status_counts[status] + 1

    worst: dict[tuple[str, str], float] = {}
    seen, severity_counts = set(), defaultdict(int)
    for index, finding in enumerate(findings):
        require(isinstance(finding, dict), f"findings[{index}] must be an object")
        entity_id, domain = finding.get("entity_id"), finding.get("domain")
        rule_id, severity = finding.get("rule_id"), finding.get("severity")
        require(entity_id in by_id, f"finding references unknown entity: {entity_id}")
        require(domain in DOMAINS, f"invalid finding domain: {domain}")
        require(domain in by_id[entity_id]["applicable_domains"], f"domain not applicable to {entity_id}: {domain}")
        require(isinstance(rule_id, str) and rule_id, f"rule_id required at finding {index}")
        require(severity in SEVERITY_SCORE, f"invalid severity at finding {index}: {severity}")
        key = (entity_id, domain, rule_id)
        require(key not in seen, f"duplicate finding: {key}")
        seen.add(key)
        severity_counts[severity] += 1
        pair = (entity_id, domain)
        worst[pair] = min(worst.get(pair, 100.0), SEVERITY_SCORE[severity])

    included = [entity for entity in entities if entity["include_in_score"]]
    entity_results, domain_values = [], defaultdict(list)
    for entity in included:
        values = []
        for domain in entity["applicable_domains"]:
            value = worst.get((entity["id"], domain), 100.0)
            values.append(value)
            domain_values[domain].append(value)
        score = round(sum(values) / len(values), 2)
        entity_results.append({"id": entity["id"], "score": score, "grade": grade(score)})
    overall = None if not entity_results else round(sum(item["score"] for item in entity_results) / len(entity_results), 2)
    domain_scores = {domain: {"score": round(sum(values) / len(values), 2),
                              "grade": grade(sum(values) / len(values)),
                              "assessed_entities": len(values)}
                     for domain, values in sorted(domain_values.items())}
    return {"score": overall, "grade": None if overall is None else grade(overall),
            "included_entities": len(entity_results), "coverage": dict(sorted(status_counts.items())),
            "severity_counts": {key: severity_counts[key] for key in ("CRITICAL", "HIGH", "MEDIUM", "LOW")},
            "domain_scores": domain_scores, "entity_scores": entity_results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Normalized scan JSON")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print output")
    args = parser.parse_args()
    try:
        result = score_scan(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

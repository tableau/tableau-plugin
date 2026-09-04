#!/usr/bin/env python3
"""Validate an exported TableauQuest state document."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


MODES = {"single", "campaign", "field"}
DEPTHS = {"blitz": (3, 5), "quick": (6, 10), "standard": (15, 20), "deep": (30, None)}
EXPERIENCE = {"beginner", "intermediate", "advanced", "expert"}
TRAITS = {
    "risk": {"reckless", "impatient", "cautious", "balanced"},
    "governance": {"low", "medium", "high"},
    "empathy": {"low", "medium", "high"},
    "evidence": {"weak", "moderate", "strong"},
    "repair": {"avoids", "partial", "consistent"},
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(state: dict[str, Any]) -> dict[str, Any]:
    require(isinstance(state, dict), "state must be an object")
    require(state.get("mode") in MODES, "mode must be single, campaign, or field")
    depth = state.get("depth")
    require(depth in DEPTHS, "invalid depth")
    require(isinstance(state.get("lite"), bool), "lite must be boolean")
    require(not (state["mode"] == "campaign" and state["lite"]), "campaign and lite are incompatible")
    require(state.get("experience") in EXPERIENCE, "invalid experience")
    for key in ("tone", "focus", "audience", "current_beat"):
        require(isinstance(state.get(key), str) and state[key].strip(), f"{key} is required")
    decisions = state.get("decision_count")
    require(isinstance(decisions, int) and not isinstance(decisions, bool) and decisions >= 0,
            "decision_count must be a non-negative integer")
    require(isinstance(state.get("ended"), bool), "ended must be boolean")
    scars, deferred = state.get("scars"), state.get("deferred_consequences")
    require(isinstance(scars, list) and all(isinstance(item, str) for item in scars), "scars must be strings")
    require(isinstance(deferred, list) and len(deferred) <= 3, "deferred_consequences must contain at most 3 items")
    require(all(isinstance(item, dict) and isinstance(item.get("summary"), str) and
                isinstance(item.get("trigger_decision"), int) for item in deferred),
            "each deferred consequence needs summary and trigger_decision")
    traits = state.get("judgment_signals")
    require(isinstance(traits, dict), "judgment_signals must be an object")
    for key, allowed in TRAITS.items():
        require(traits.get(key) in allowed, f"invalid judgment signal: {key}")
    minimum, maximum = DEPTHS[depth]
    if state["ended"]:
        require(decisions >= minimum, "completed scenario ended before its depth minimum")
        if maximum is not None:
            require(decisions <= maximum, "completed scenario exceeded its depth range")
    return {"valid": True, "minimum_decisions": minimum, "maximum_decisions": maximum}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    args = parser.parse_args()
    try:
        result = validate(json.loads(args.state.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

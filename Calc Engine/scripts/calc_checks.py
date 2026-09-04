#!/usr/bin/env python3
"""Local, side-effect-free checks for Tableau calculation text."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


DOUBLE_ESCAPED = re.compile(r"&amp;(?:lt|gt|amp|quot);", re.IGNORECASE)
FUNCTION_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*")


def strip_line_comments(formula: str) -> str:
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(formula):
        char = formula[index]
        if quote:
            output.append(char)
            if char == "\\" and index + 1 < len(formula):
                index += 1
                output.append(formula[index])
            elif char == quote:
                if index + 1 < len(formula) and formula[index + 1] == quote:
                    index += 1
                    output.append(formula[index])
                else:
                    quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            output.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(formula) and formula[index + 1] == "/":
            while index < len(formula) and formula[index] not in "\r\n":
                index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def normalize_unquoted_segments(formula: str) -> str:
    parts: list[str] = []
    start = 0
    index = 0
    while index < len(formula):
        if formula[index] not in {"'", '"'}:
            index += 1
            continue
        if start < index:
            segment = re.sub(r"\s+", " ", formula[start:index])
            parts.append(FUNCTION_CALL.sub(lambda match: match.group(1).lower() + "(", segment))
        quote = formula[index]
        quoted_start = index
        index += 1
        while index < len(formula):
            if formula[index] == "\\" and index + 1 < len(formula):
                index += 2
                continue
            if formula[index] == quote:
                if index + 1 < len(formula) and formula[index + 1] == quote:
                    index += 2
                    continue
                index += 1
                break
            index += 1
        parts.append(formula[quoted_start:index])
        start = index
    segment = re.sub(r"\s+", " ", formula[start:])
    parts.append(FUNCTION_CALL.sub(lambda match: match.group(1).lower() + "(", segment))
    return "".join(parts).strip()


def normalize(formula: str) -> str:
    """Normalize comments, whitespace, and function-name case for comparison."""
    return normalize_unquoted_segments(strip_line_comments(formula))


def check_stored_formula(stored: str, expected_operators: list[str]) -> dict[str, object]:
    issues: list[str] = []
    stripped = stored.strip()
    if not stripped:
        issues.append("stored formula is empty")
    if DOUBLE_ESCAPED.search(stored):
        issues.append("double-escaped XML entity found")
    if "[Parameters].[Parameters]." in stored:
        issues.append("double-qualified parameter reference found")
    if stripped.startswith("//") and "\n" not in stripped:
        issues.append("single-line leading comment may have swallowed the formula")
    for operator in expected_operators:
        if operator not in stored:
            issues.append(f"missing expected operator: {operator}")
    return {"ok": not issues, "issues": issues, "normalized": normalize(stored)}


def read_text(path: str | None) -> str:
    return Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser("normalize", help="print normalized formula text")
    normalize_parser.add_argument("--file", help="formula file; stdin when omitted")

    check_parser = subparsers.add_parser("check", help="emit JSON checks for stored formula text")
    check_parser.add_argument("--file", help="stored formula file; stdin when omitted")
    check_parser.add_argument("--expect-operator", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    formula = read_text(args.file)
    if args.command == "normalize":
        print(normalize(formula))
        return 0
    result = check_stored_formula(formula, args.expect_operator)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

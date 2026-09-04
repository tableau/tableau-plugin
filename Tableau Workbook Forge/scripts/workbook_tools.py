#!/usr/bin/env python3
"""Safe local helpers for inspecting and packaging Tableau workbooks."""

from __future__ import annotations

import argparse
from collections import Counter
import difflib
import hashlib
import json
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from lxml import etree


MAX_MEMBERS = 10_000
MAX_UNCOMPRESSED_BYTES = 2_000_000_000


def secure_parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, recover=False)


def safe_extract(twbx_path: str, run_dir: str) -> dict[str, str]:
    source = Path(twbx_path).resolve()
    run = Path(run_dir).resolve()
    run.mkdir(parents=True, exist_ok=False)
    destination = run / "extracted"
    destination.mkdir()

    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise ValueError("archive exceeds member-count limit")
        if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("archive exceeds uncompressed-size limit")

        for member in members:
            relative = PurePosixPath(member.filename)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError(f"unsafe archive member: {member.filename}")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"archive link is not allowed: {member.filename}")
            target = (destination / Path(*relative.parts)).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError(f"archive member escapes destination: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source_stream, target.open("wb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream)

    candidates = sorted(destination.rglob("*.twb"))
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one .twb, found {len(candidates)}")
    original = candidates[0]
    working = run / "working.forge.twb"
    shutil.copy2(original, working)
    return {
        "extracted_dir": str(destination),
        "working_twb": str(working),
        "original_member": original.relative_to(destination).as_posix(),
    }


def local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_workbook(twb_path: str) -> etree._ElementTree:
    return etree.parse(twb_path, secure_parser())


def duplicate_values(values: list[str]) -> list[str]:
    counts = Counter(value for value in values if value)
    return sorted(value for value, count in counts.items() if count > 1)


def workbook_inventory(twb_path: str) -> dict[str, object]:
    tree = parse_workbook(twb_path)
    root = tree.getroot()
    worksheets = [
        {
            "name": worksheet.get("name", ""),
            "run_count": len(worksheet.xpath(".//*[local-name()='run']")),
        }
        for worksheet in root.xpath(".//*[local-name()='worksheets']/*[local-name()='worksheet']")
    ]
    dashboards = [
        {
            "name": dashboard.get("name", ""),
            "zone_count": len(dashboard.xpath(".//*[local-name()='zone']")),
        }
        for dashboard in root.xpath(".//*[local-name()='dashboards']/*[local-name()='dashboard']")
    ]
    datasources = [
        datasource.get("caption") or datasource.get("name", "")
        for datasource in root.xpath(".//*[local-name()='datasources']/*[local-name()='datasource']")
    ]
    fonts = Counter()
    colors = Counter()
    for element in root.iter():
        for attribute, value in element.attrib.items():
            lowered = attribute.casefold()
            if lowered in {"fontname", "font-family"} and value:
                fonts[value] += 1
            if "color" in lowered and value:
                colors[value] += 1
    return {
        "path": str(Path(twb_path).resolve()),
        "sha256": file_sha256(twb_path),
        "root": local_name(root),
        "source_build": root.get("source-build"),
        "worksheets": worksheets,
        "dashboards": dashboards,
        "datasources": datasources,
        "fonts": dict(sorted(fonts.items())),
        "colors": dict(sorted(colors.items())),
        "element_count": sum(1 for _ in root.iter()),
    }


def validate(twb_path: str) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    try:
        tree = etree.parse(twb_path, secure_parser())
    except (OSError, etree.XMLSyntaxError) as exc:
        return {"ok": False, "checks": [{"id": "xml", "ok": False, "detail": str(exc)}]}

    root = tree.getroot()
    checks.append({"id": "xml", "ok": True, "detail": "well-formed XML"})

    no_doctype = not bool(tree.docinfo.doctype)
    checks.append({
        "id": "doctype",
        "ok": no_doctype,
        "detail": "no document type declaration" if no_doctype else "document type declarations are not allowed",
    })

    root_ok = local_name(root) == "workbook"
    checks.append({
        "id": "workbook-root",
        "ok": root_ok,
        "detail": f"root element: {local_name(root)}",
    })

    forbidden_font_formats = root.xpath(".//*[local-name()='format'][@attr='font-color']")
    checks.append({
        "id": "font-color-location",
        "ok": not forbidden_font_formats,
        "detail": f"forbidden font-color format elements: {len(forbidden_font_formats)}",
    })

    empty_external = root.xpath(".//*[local-name()='external'][not(*) and not(normalize-space())]")
    checks.append({
        "id": "empty-external",
        "ok": not empty_external,
        "detail": f"empty external elements: {len(empty_external)}",
    })

    child_names = [local_name(child) for child in root]
    worksheets_present = "worksheets" in child_names
    actions_index = child_names.index("actions") if "actions" in child_names else None
    worksheets_index = child_names.index("worksheets") if worksheets_present else None
    order_ok = worksheets_present and (actions_index is None or actions_index < worksheets_index)
    checks.append({
        "id": "workbook-collections",
        "ok": order_ok,
        "detail": "worksheets present and actions ordering is valid" if order_ok else "missing worksheets or actions follow worksheets",
    })

    worksheet_names = [
        item.get("name", "")
        for item in root.xpath(".//*[local-name()='worksheets']/*[local-name()='worksheet']")
    ]
    worksheet_names_ok = all(worksheet_names) and not duplicate_values(worksheet_names)
    checks.append({
        "id": "worksheet-names",
        "ok": worksheet_names_ok,
        "detail": f"worksheets: {len(worksheet_names)}; duplicates: {duplicate_values(worksheet_names)}",
    })

    dashboard_names = [
        item.get("name", "")
        for item in root.xpath(".//*[local-name()='dashboards']/*[local-name()='dashboard']")
    ]
    dashboard_names_ok = all(dashboard_names) and not duplicate_values(dashboard_names)
    checks.append({
        "id": "dashboard-names",
        "ok": dashboard_names_ok,
        "detail": f"dashboards: {len(dashboard_names)}; duplicates: {duplicate_values(dashboard_names)}",
    })

    known_worksheets = set(worksheet_names)
    references: list[str] = []
    for zone in root.xpath(".//*[local-name()='zone'][@name]"):
        zone_type = (zone.get("type-v2") or zone.get("type") or "").casefold()
        if zone_type == "worksheet":
            references.append(zone.get("name", ""))
    for window in root.xpath(".//*[local-name()='window'][@name]"):
        if (window.get("class") or "").casefold() == "worksheet":
            references.append(window.get("name", ""))
    unresolved = sorted(set(reference for reference in references if reference not in known_worksheets))
    checks.append({
        "id": "worksheet-references",
        "ok": not unresolved,
        "detail": f"known references: {len(references)}; unresolved: {unresolved}",
    })

    duplicate_zone_ids: dict[str, list[str]] = {}
    for dashboard in root.xpath(".//*[local-name()='dashboards']/*[local-name()='dashboard']"):
        ids = [zone.get("id", "") for zone in dashboard.xpath(".//*[local-name()='zone'][@id]")]
        duplicates = duplicate_values(ids)
        if duplicates:
            duplicate_zone_ids[dashboard.get("name", "")] = duplicates
    checks.append({
        "id": "dashboard-zone-ids",
        "ok": not duplicate_zone_ids,
        "detail": f"duplicate zone ids: {duplicate_zone_ids}",
    })

    return {"ok": all(bool(check["ok"]) for check in checks), "checks": checks}


RUN_STYLE_ATTRIBUTES = {"fontcolor", "fontname", "fontsize", "bold", "italic", "underline"}


def worksheet_runs(root: etree._Element, worksheet_name: str | None) -> list[etree._Element]:
    if worksheet_name is None:
        return list(root.xpath(".//*[local-name()='run']"))
    worksheets = [
        node
        for node in root.xpath(".//*[local-name()='worksheets']/*[local-name()='worksheet']")
        if node.get("name") == worksheet_name
    ]
    if len(worksheets) != 1:
        raise ValueError(f"expected one worksheet named {worksheet_name!r}, found {len(worksheets)}")
    return list(worksheets[0].xpath(".//*[local-name()='run']"))


def replace_run_style(root: etree._Element, operation: dict[str, object]) -> dict[str, object]:
    worksheet = operation.get("worksheet")
    if worksheet is not None and not isinstance(worksheet, str):
        raise ValueError("replace_run_style worksheet must be a string")
    match = operation.get("match")
    set_values = operation.get("set")
    if not isinstance(match, dict) or not match:
        raise ValueError("replace_run_style requires a non-empty match object")
    if not isinstance(set_values, dict) or not set_values:
        raise ValueError("replace_run_style requires a non-empty set object")
    unknown = (set(match) | set(set_values)) - RUN_STYLE_ATTRIBUTES
    if unknown:
        raise ValueError(f"unsupported run style attributes: {sorted(unknown)}")
    candidates = worksheet_runs(root, worksheet)
    selected = [run for run in candidates if all(run.get(key) == str(value) for key, value in match.items())]
    expected = operation.get("expected")
    if expected is not None and (not isinstance(expected, int) or expected < 0):
        raise ValueError("expected must be a non-negative integer")
    if expected is not None and len(selected) != expected:
        raise ValueError(f"replace_run_style expected {expected} matches, found {len(selected)}")
    if not selected:
        raise ValueError("replace_run_style matched no run elements")
    for run in selected:
        for key, value in set_values.items():
            run.set(key, str(value))
    return {
        "op": "replace_run_style",
        "worksheet": worksheet,
        "matched": len(selected),
        "match": match,
        "set": set_values,
    }


def replace_run_text(root: etree._Element, operation: dict[str, object]) -> dict[str, object]:
    worksheet = operation.get("worksheet")
    if worksheet is not None and not isinstance(worksheet, str):
        raise ValueError("replace_run_text worksheet must be a string")
    source = operation.get("from")
    target = operation.get("to")
    if not isinstance(source, str) or not isinstance(target, str):
        raise ValueError("replace_run_text requires string from and to values")
    selected = [run for run in worksheet_runs(root, worksheet) if (run.text or "") == source]
    expected = operation.get("expected")
    if expected is not None and (not isinstance(expected, int) or expected < 0):
        raise ValueError("expected must be a non-negative integer")
    if expected is not None and len(selected) != expected:
        raise ValueError(f"replace_run_text expected {expected} matches, found {len(selected)}")
    if not selected:
        raise ValueError("replace_run_text matched no run elements")
    for run in selected:
        run.text = target
    return {
        "op": "replace_run_text",
        "worksheet": worksheet,
        "matched": len(selected),
        "from": source,
        "to": target,
    }


def set_zone_geometry(root: etree._Element, operation: dict[str, object]) -> dict[str, object]:
    dashboard_name = operation.get("dashboard")
    zone_id = operation.get("zone_id")
    set_values = operation.get("set")
    if not isinstance(dashboard_name, str) or not dashboard_name:
        raise ValueError("set_zone_geometry requires a dashboard name")
    if not isinstance(zone_id, (str, int)) or str(zone_id) == "":
        raise ValueError("set_zone_geometry requires a zone_id")
    if not isinstance(set_values, dict) or not set_values:
        raise ValueError("set_zone_geometry requires a non-empty set object")
    unknown = set(set_values) - {"x", "y", "w", "h"}
    if unknown:
        raise ValueError(f"unsupported zone geometry attributes: {sorted(unknown)}")
    normalized: dict[str, str] = {}
    for key, value in set_values.items():
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"zone geometry {key} must be an integer") from exc
        if number < 0 or (key in {"w", "h"} and number == 0):
            raise ValueError(f"zone geometry {key} is outside the supported range")
        normalized[key] = str(number)
    dashboards = [
        dashboard
        for dashboard in root.xpath(".//*[local-name()='dashboards']/*[local-name()='dashboard']")
        if dashboard.get("name") == dashboard_name
    ]
    if len(dashboards) != 1:
        raise ValueError(f"expected one dashboard named {dashboard_name!r}, found {len(dashboards)}")
    zones = [
        zone for zone in dashboards[0].xpath(".//*[local-name()='zone'][@id]")
        if zone.get("id") == str(zone_id)
    ]
    if len(zones) != 1:
        raise ValueError(f"expected one zone id {zone_id!r} in dashboard {dashboard_name!r}, found {len(zones)}")
    before = {key: zones[0].get(key) for key in normalized}
    for key, value in normalized.items():
        zones[0].set(key, value)
    return {
        "op": "set_zone_geometry",
        "dashboard": dashboard_name,
        "zone_id": str(zone_id),
        "before": before,
        "set": normalized,
    }


def rename_worksheet(root: etree._Element, operation: dict[str, object]) -> dict[str, object]:
    source = operation.get("from")
    target = operation.get("to")
    if not isinstance(source, str) or not source or not isinstance(target, str) or not target:
        raise ValueError("rename_worksheet requires non-empty from and to strings")
    worksheets = list(root.xpath(".//*[local-name()='worksheets']/*[local-name()='worksheet']"))
    matches = [worksheet for worksheet in worksheets if worksheet.get("name") == source]
    if len(matches) != 1:
        raise ValueError(f"expected one worksheet named {source!r}, found {len(matches)}")
    if any(worksheet.get("name") == target for worksheet in worksheets):
        raise ValueError(f"worksheet name already exists: {target!r}")

    known_references: list[etree._Element] = []
    unknown_references: list[str] = []
    for element in root.iter():
        for attribute, value in element.attrib.items():
            if value != source:
                continue
            name = local_name(element)
            is_target = element is matches[0] and attribute == "name"
            is_zone = name == "zone" and attribute == "name" and (element.get("type-v2") or element.get("type") or "").casefold() == "worksheet"
            is_window = name == "window" and attribute == "name" and (element.get("class") or "").casefold() == "worksheet"
            if is_target:
                continue
            if is_zone or is_window:
                known_references.append(element)
            else:
                unknown_references.append(f"{name}@{attribute}")
        if (element.text or "").strip() == source:
            unknown_references.append(f"{local_name(element)} text")
    if unknown_references:
        raise ValueError(f"unsupported worksheet references require a compatible donor: {sorted(unknown_references)}")

    matches[0].set("name", target)
    for element in known_references:
        element.set("name", target)
    return {
        "op": "rename_worksheet",
        "from": source,
        "to": target,
        "updated_known_references": len(known_references),
    }


def apply_edit_plan(twb_path: str, plan_path: str, dry_run: bool = False) -> dict[str, object]:
    workbook = Path(twb_path).resolve()
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or plan.get("version") != "1.0":
        raise ValueError("edit plan version must be '1.0'")
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("edit plan requires a non-empty operations array")
    tree = parse_workbook(str(workbook))
    root = tree.getroot()
    changes: list[dict[str, object]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("each edit operation must be an object")
        op = operation.get("op")
        if op == "replace_run_style":
            changes.append(replace_run_style(root, operation))
        elif op == "replace_run_text":
            changes.append(replace_run_text(root, operation))
        elif op == "set_zone_geometry":
            changes.append(set_zone_geometry(root, operation))
        elif op == "rename_worksheet":
            changes.append(rename_worksheet(root, operation))
        else:
            raise ValueError(f"unsupported edit operation: {op!r}")

    temporary = workbook.with_name(workbook.name + ".forge.tmp")
    if temporary.exists():
        raise FileExistsError(f"temporary output already exists: {temporary}")
    before_hash = file_sha256(workbook)
    try:
        tree.write(str(temporary), xml_declaration=True, encoding="utf-8")
        validation = validate(str(temporary))
        if not validation["ok"]:
            raise ValueError(f"edit plan produced an invalid workbook: {validation}")
        after_hash = file_sha256(temporary)
        if not dry_run:
            temporary.replace(workbook)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "ok": True,
        "dry_run": dry_run,
        "source": str(workbook),
        "before_sha256": before_hash,
        "after_sha256": after_hash,
        "changes": changes,
        "validation": validation,
    }


def diff_workbooks(before_path: str, after_path: str) -> dict[str, object]:
    before = Path(before_path).resolve()
    after = Path(after_path).resolve()
    before_lines = before.read_text(encoding="utf-8").splitlines()
    after_lines = after.read_text(encoding="utf-8").splitlines()
    diff = list(difflib.unified_diff(before_lines, after_lines, fromfile=before.name, tofile=after.name, lineterm=""))
    return {
        "changed": file_sha256(before) != file_sha256(after),
        "before_sha256": file_sha256(before),
        "after_sha256": file_sha256(after),
        "before_inventory": workbook_inventory(str(before)),
        "after_inventory": workbook_inventory(str(after)),
        "diff": diff,
    }


def validate_package(twbx_path: str, baseline_path: str | None = None) -> dict[str, object]:
    package_path = Path(twbx_path).resolve()
    with tempfile.TemporaryDirectory(prefix="vibe-package-") as directory:
        run_dir = Path(directory, "run")
        extracted = safe_extract(str(package_path), str(run_dir))
        workbook_validation = validate(extracted["working_twb"])
        with zipfile.ZipFile(package_path) as archive:
            members = sorted(member.filename for member in archive.infolist() if not member.is_dir())
            member_hashes = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in members}
        comparison = None
        if baseline_path is not None:
            baseline = Path(baseline_path).resolve()
            with zipfile.ZipFile(baseline) as archive:
                baseline_members = sorted(member.filename for member in archive.infolist() if not member.is_dir())
                baseline_hashes = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in baseline_members}
            workbook_member = extracted["original_member"]
            missing = sorted(set(baseline_members) - set(members))
            added = sorted(set(members) - set(baseline_members))
            changed_unrelated = sorted(
                name for name in set(members) & set(baseline_members)
                if name != workbook_member and member_hashes[name] != baseline_hashes[name]
            )
            comparison = {
                "baseline": str(baseline),
                "missing_members": missing,
                "added_members": added,
                "changed_unrelated_members": changed_unrelated,
                "unrelated_members_preserved": not missing and not added and not changed_unrelated,
            }
        return {
            "ok": workbook_validation["ok"] and (comparison is None or comparison["unrelated_members_preserved"]),
            "package": str(package_path),
            "sha256": file_sha256(package_path),
            "members": members,
            "member_hashes": member_hashes,
            "workbook_member": extracted["original_member"],
            "workbook_validation": workbook_validation,
            "baseline_comparison": comparison,
        }


def replace_run_color(twb_path: str, source_color: str, target_color: str) -> int:
    tree = etree.parse(twb_path, secure_parser())
    changed = 0
    for run in tree.xpath(".//*[local-name()='run']"):
        if run.get("fontcolor", "").casefold() == source_color.casefold():
            run.set("fontcolor", target_color)
            changed += 1
    tree.write(twb_path, xml_declaration=True, encoding="utf-8")
    return changed


def package(extracted_dir: str, edited_twb: str, original_member: str, out_twbx: str) -> str:
    root = Path(extracted_dir).resolve()
    member_path = PurePosixPath(original_member)
    if member_path.is_absolute() or ".." in member_path.parts or member_path.suffix.lower() != ".twb":
        raise ValueError("invalid workbook member path")
    member = (root / Path(*member_path.parts)).resolve()
    if root not in member.parents:
        raise ValueError("workbook member escapes extraction root")

    shutil.copy2(edited_twb, member)
    output = Path(out_twbx).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    temporary = output.with_suffix(output.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"temporary output already exists: {temporary}")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative = path.relative_to(root).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return str(output)


def emit_json(result: dict[str, object], json_path: str | None = None) -> None:
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if json_path:
        Path(json_path).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    extract_parser = commands.add_parser("extract", help="safely extract one workbook from a .twbx")
    extract_parser.add_argument("twbx")
    extract_parser.add_argument("run_dir")

    validate_parser = commands.add_parser("validate", help="run local XML checks")
    validate_parser.add_argument("twb")
    validate_parser.add_argument("--json", dest="json_path")

    inspect_parser = commands.add_parser("inspect", help="inventory workbook structure and style values")
    inspect_parser.add_argument("twb")
    inspect_parser.add_argument("--json", dest="json_path")

    plan_parser = commands.add_parser("apply-plan", help="apply a declarative edit plan atomically")
    plan_parser.add_argument("twb")
    plan_parser.add_argument("plan")
    plan_parser.add_argument("--dry-run", action="store_true")
    plan_parser.add_argument("--json", dest="json_path")

    diff_parser = commands.add_parser("diff", help="compare two workbook XML files")
    diff_parser.add_argument("before")
    diff_parser.add_argument("after")
    diff_parser.add_argument("--json", dest="json_path")

    color_parser = commands.add_parser("replace-run-color", help="replace one run font color in place")
    color_parser.add_argument("twb")
    color_parser.add_argument("source_color")
    color_parser.add_argument("target_color")

    package_parser = commands.add_parser("package", help="package an extracted tree as deterministic .twbx")
    package_parser.add_argument("extracted_dir")
    package_parser.add_argument("edited_twb")
    package_parser.add_argument("original_member")
    package_parser.add_argument("output")

    package_validation_parser = commands.add_parser(
        "validate-package", help="reopen and validate a .twbx, optionally against its baseline"
    )
    package_validation_parser.add_argument("twbx")
    package_validation_parser.add_argument("--baseline")
    package_validation_parser.add_argument("--json", dest="json_path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        emit_json(safe_extract(args.twbx, args.run_dir))
        return 0
    if args.command == "validate":
        result = validate(args.twb)
        emit_json(result, args.json_path)
        return 0 if result["ok"] else 1
    if args.command == "inspect":
        emit_json(workbook_inventory(args.twb), args.json_path)
        return 0
    if args.command == "apply-plan":
        emit_json(apply_edit_plan(args.twb, args.plan, args.dry_run), args.json_path)
        return 0
    if args.command == "diff":
        emit_json(diff_workbooks(args.before, args.after), args.json_path)
        return 0
    if args.command == "replace-run-color":
        emit_json({"changed": replace_run_color(args.twb, args.source_color, args.target_color)})
        return 0
    if args.command == "package":
        print(package(args.extracted_dir, args.edited_twb, args.original_member, args.output))
        return 0
    result = validate_package(args.twbx, args.baseline)
    emit_json(result, args.json_path)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

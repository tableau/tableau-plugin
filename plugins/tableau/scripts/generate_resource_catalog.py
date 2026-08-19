#!/usr/bin/env python3
"""Deterministic resource catalog generator for the Tableau plugin.

Scans every resource under ``resources/`` (bookmark templates, examples,
references, and starters), classifies each ``.tbm`` bookmark as
``executable`` or ``reference`` based on static portability checks, and
produces a single deterministic ``resources/catalog.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

BLOCKERS = {
    "multiple-datasources",
    "inline-datasource",
    "connection-dependency",
    "viz-extension",
    "missing-column-metadata",
    "unresolved-field-reference",
    "external-calculation-dependency",
    "invalid-bookmark-shape",
}

# Tableau pseudo-fields that never resolve to a column or column-instance.
PSEUDO_FIELDS = {":Measure Names", "Multiple Values", "Multiple Names"}

# Tableau pseudo-datasource names that are never real, rewritable donors.
# "Parameters" is the workbook-level parameter pseudo-datasource; internal
# object IDs are hidden per-table row-count namespaces inside inline
# relational datasources. Both show up as the first bracket segment of a
# "[Name].[Field]" reference but must not count toward donor-datasource
# discovery or the multiple-datasources blocker.
PSEUDO_DATASOURCE_NAMES = {"Parameters", "__tableau_internal_object_id__"}

# Attributes/tags that may carry a "[Datasource].[Field]" qualified reference
# anywhere in the document. Used only to discover donor datasource names, so
# false positives (e.g. a field placed only in a tooltip) are harmless here.
_BROAD_REF_ATTRS = (
    "column",
    "axis-column",
    "value-column",
    "dimension-to-sort",
    "measure-to-sort-by",
    "using",
    "param",
    "field",
    "y-axis-name",
    "x-axis-name",
    "ordering-field",
)
_BROAD_REF_TEXT_TAGS = ("rows", "cols", "field")

QUALIFIED_REF_RE = re.compile(r"\[([^\[\]]+)\]\.\[([^\[\]]+)\]")
PARAMETER_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
FIELD_BASE_RE = re.compile(r"^field_base_\d+$")

TEMPLATE_TIERS = ("unclassified", "executable", "reference")

# Parameter types a reviewed contract may declare. Every explicit
# {{PARAMETER}} token must map to one of these in the generated catalog.
PARAMETER_TYPES = frozenset({"date", "enum", "number", "string"})

PLAIN_RESOURCE_DIRS = {
    "examples": "example",
    "references": "reference",
    "starters": "starter",
}


def sha256(path: Path) -> str:
    """Return the hex sha256 digest of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strip_brackets(value: str) -> str:
    """Strip a single pair of surrounding square brackets, if present."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]") and len(value) >= 2:
        return value[1:-1]
    return value


def extract_parameters(text: str) -> list[str]:
    """Return sorted, unique explicit ``{{PARAMETER}}`` names in ``text``.

    ``{{DATASOURCE}}`` and ``{{field_base_N}}`` are template-substitution
    tokens, not caller-supplied parameters, and are excluded.
    """
    names: set[str] = set()
    for token in PARAMETER_RE.findall(text):
        if token == "DATASOURCE":
            continue
        if FIELD_BASE_RE.match(token):
            continue
        if token != token.upper():
            continue
        names.add(token)
    return sorted(names)


def _broad_qualified_refs(root: ET.Element) -> list[tuple[str, str]]:
    """Find every ``[Datasource].[Field]`` reference anywhere in the tree.

    Deliberately permissive: used only to discover donor datasource names,
    never to decide whether a specific field is "placed" on the view.
    """
    refs: list[tuple[str, str]] = []
    for element in root.iter():
        for attr in _BROAD_REF_ATTRS:
            value = element.get(attr)
            if value:
                refs.extend(QUALIFIED_REF_RE.findall(value))
        if element.tag in _BROAD_REF_TEXT_TAGS and element.text:
            refs.extend(QUALIFIED_REF_RE.findall(element.text))
        if element.tag == "groupfilter":
            member = element.get("member")
            if member:
                refs.extend(QUALIFIED_REF_RE.findall(member.strip('"')))
    return refs


def _strict_placed_refs(
    root: ET.Element, table: ET.Element
) -> list[tuple[str, str, str]]:
    """Find field references actually placed on the view.

    Restricted to rows, columns, marks encodings, filters (including slices
    and group-filter members), titles, and reference lines, per the resource
    catalog design's executable-eligibility rules.
    """
    refs: list[tuple[str, str, str]] = []

    rows_text = table.findtext("rows")
    if rows_text:
        refs.extend(
            (ds, field, "rows") for ds, field in QUALIFIED_REF_RE.findall(rows_text)
        )
    cols_text = table.findtext("cols")
    if cols_text:
        refs.extend(
            (ds, field, "columns") for ds, field in QUALIFIED_REF_RE.findall(cols_text)
        )

    for encodings in table.iter("encodings"):
        for encoding in encodings:
            value = encoding.get("column")
            if value:
                refs.extend(
                    (ds, field, "marks") for ds, field in QUALIFIED_REF_RE.findall(value)
                )

    for filt in table.iter("filter"):
        value = filt.get("column")
        if value:
            refs.extend(
                (ds, field, "filters") for ds, field in QUALIFIED_REF_RE.findall(value)
            )
    for group_filter in table.iter("groupfilter"):
        member = group_filter.get("member")
        if member:
            refs.extend(
                (ds, field, "filters")
                for ds, field in QUALIFIED_REF_RE.findall(member.strip('"'))
            )
    for slices in table.iter("slices"):
        for column in slices.findall("column"):
            if column.text:
                refs.extend(
                    (ds, field, "filters")
                    for ds, field in QUALIFIED_REF_RE.findall(column.text)
                )

    for reference_line in table.iter("reference-line"):
        for attr in ("axis-column", "value-column"):
            value = reference_line.get(attr)
            if value:
                refs.extend(
                    (ds, field, "reference-line")
                    for ds, field in QUALIFIED_REF_RE.findall(value)
                )

    layout_options = root.find("layout-options")
    if layout_options is not None:
        title = layout_options.find("title")
        if title is not None:
            for field_element in title.iter("field"):
                if field_element.text:
                    refs.extend(
                        (ds, field, "title")
                        for ds, field in QUALIFIED_REF_RE.findall(field_element.text)
                    )

    return refs


def extract_bookmark(path: Path) -> dict[str, object]:
    """Parse a ``.tbm`` bookmark and extract its classification-relevant facts."""
    text = path.read_text(encoding="utf-8")

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {
            "datasources": [],
            "fields": [],
            "parameters": [],
            "blockers": ["invalid-bookmark-shape"],
        }

    blockers: set[str] = set()

    windows = root.findall("window")
    tables = root.findall("table")
    if len(windows) != 1 or len(tables) != 1:
        blockers.add("invalid-bookmark-shape")
    table = tables[0] if tables else None

    datasource_elements = list(root.iter("datasource"))
    datasource_names: set[str] = {
        ds.get("name")
        for ds in datasource_elements
        if ds.get("name") and ds.get("name") not in PSEUDO_DATASOURCE_NAMES
    }
    if any(ds.get("inline") == "true" for ds in datasource_elements):
        blockers.add("inline-datasource")

    for dependencies in root.iter("datasource-dependencies"):
        name = dependencies.get("datasource")
        if name and name not in PSEUDO_DATASOURCE_NAMES:
            datasource_names.add(name)

    for ds_name, _field in _broad_qualified_refs(root):
        if ds_name not in PSEUDO_DATASOURCE_NAMES:
            datasource_names.add(ds_name)

    connection_dependency = False
    for ds in datasource_elements:
        if ds.get("inline") == "true":
            continue
        name = ds.get("name") or ""
        if name in PSEUDO_DATASOURCE_NAMES:
            continue
        if name.startswith("federated.") or ds.find("connection") is not None:
            connection_dependency = True
    if connection_dependency:
        blockers.add("connection-dependency")

    if len(datasource_names) > 1:
        blockers.add("multiple-datasources")

    viz_extension = any(
        mark.get("class") == "VizExtension" for mark in root.iter("mark")
    )
    if root.find(".//add-in") is not None:
        viz_extension = True
    if viz_extension:
        blockers.add("viz-extension")

    columns: dict[str, ET.Element] = {}
    instances: dict[str, ET.Element] = {}
    for dependencies in root.iter("datasource-dependencies"):
        for column in dependencies.findall("column"):
            name = column.get("name")
            if name:
                columns[name] = column
        for instance in dependencies.findall("column-instance"):
            name = instance.get("name")
            if name:
                instances[name] = instance

    if any(column.find("calculation") is not None for column in columns.values()):
        blockers.add("external-calculation-dependency")

    placed_refs = _strict_placed_refs(root, table) if table is not None else []

    fields: list[dict[str, object]] = []
    seen_field_keys: set[tuple[str, str, str, str | None]] = set()
    unresolved: list[str] = []
    missing_metadata: list[str] = []

    for ds_name, field_name, shelf in placed_refs:
        if field_name in PSEUDO_FIELDS:
            continue
        bracketed = f"[{field_name}]"

        if bracketed in instances:
            instance = instances[bracketed]
            base_name = instance.get("column")
            base_column = columns.get(base_name) if base_name else None
            if base_column is None:
                missing_metadata.append(bracketed)
                continue
            derivation = instance.get("derivation")
        elif bracketed in columns:
            base_column = columns[bracketed]
            base_name = bracketed
            derivation = None
        else:
            unresolved.append(bracketed)
            continue

        source_field = strip_brackets(base_name)
        # Include derivation in the dedup key: two column-instances on the
        # same shelf can derive the same base field differently (e.g. Sum vs
        # Avg), and both are distinct, real placements worth keeping.
        key = (ds_name, source_field, shelf, derivation)
        if key in seen_field_keys:
            continue
        seen_field_keys.add(key)
        fields.append(
            {
                "sourceField": source_field,
                "datasource": ds_name,
                "datatype": base_column.get("datatype"),
                "role": base_column.get("role"),
                "derivation": derivation,
                "shelf": shelf,
            }
        )

    if unresolved:
        blockers.add("unresolved-field-reference")
    if missing_metadata:
        blockers.add("missing-column-metadata")

    fields.sort(
        key=lambda item: (
            item["sourceField"],
            item["shelf"],
            item["datasource"],
            item["derivation"] or "",
        )
    )

    return {
        "datasources": sorted(datasource_names),
        "fields": fields,
        "parameters": extract_parameters(text),
        "blockers": sorted(blockers),
    }


def classify_bookmark(metadata: dict[str, object]) -> tuple[str, list[str]]:
    """Classify a bookmark as ``executable`` or ``reference``.

    Any recorded blocker forces ``reference`` with stable, sorted reason IDs.
    """
    reasons = sorted(metadata.get("blockers", []))
    tier = "reference" if reasons else "executable"
    return tier, reasons


def _infer_family_and_intent(resource_id: str) -> tuple[str | None, str | None]:
    """Derive a family/intent guess from a resource's filename.

    File names provide discovery keywords and intent, never runtime field
    semantics; explicit catalog overrides take precedence over this guess.
    """
    if "__" in resource_id:
        parts = resource_id.split("__")
        family = parts[0]
        intent = parts[-1].replace("-", " ").replace("_", " ").strip()
        return family, intent or None
    intent = resource_id.replace("-", " ").replace("_", " ").strip()
    return None, intent or None


def _keywords(resource_id: str, extra: tuple[str, ...] = ()) -> list[str]:
    tokens = {token for token in re.split(r"[-_]+", resource_id.lower()) if token}
    tokens.update(extra)
    return sorted(tokens)


def _relative_path(path: Path, resources_dir: Path) -> str:
    relative = path.resolve().relative_to(resources_dir.resolve())
    return "./" + relative.as_posix()


def _load_overrides(resources_dir: Path) -> dict[str, dict[str, object]]:
    overrides_path = resources_dir / "catalog-overrides.json"
    if not overrides_path.exists():
        return {}
    data = json.loads(overrides_path.read_text(encoding="utf-8"))
    return data.get("resources", {})


def _parameter_contracts(
    resource_id: str, override: dict[str, object], metadata: dict[str, object]
) -> list[dict[str, object]]:
    """Build one complete typed contract per inferred ``{{PARAMETER}}`` token.

    Parameter types are reviewed in ``catalog-overrides.json`` but are copied
    into the generated catalog so runtime validation never depends on the
    overrides file being present or readable. Generation fails when a token
    has no reviewed contract, when a contract names an unknown token, or when
    a type is missing or unrecognized, so an untyped parameter can never reach
    the catalog and be validated loosely later.

    Overrides still never remove a blocker or promote a failed resource to
    executable.
    """
    declared = override.get("parameters")
    declared = {} if declared is None else declared
    inferred = set(metadata["parameters"])
    if set(declared) != inferred:
        raise ValueError(
            f"catalog override parameters for {resource_id!r} do not match "
            f"inferred parameters: declared={sorted(declared)} "
            f"inferred={sorted(inferred)}"
        )

    contracts: list[dict[str, object]] = []
    for name in sorted(inferred):
        spec = declared[name] or {}
        kind = spec.get("type")
        if kind not in PARAMETER_TYPES:
            raise ValueError(
                f"catalog override parameter {name!r} for {resource_id!r} must "
                f"declare a type from {', '.join(sorted(PARAMETER_TYPES))}, "
                f"got: {kind!r}"
            )
        contract: dict[str, object] = {
            "name": name,
            "type": kind,
            "required": bool(spec.get("required", True)),
        }
        if kind == "enum":
            allowed = [str(value) for value in spec.get("allowed") or []]
            if not allowed:
                raise ValueError(
                    f"catalog override parameter {name!r} for {resource_id!r} is "
                    "an enum and must declare a non-empty 'allowed' list"
                )
            contract["allowed"] = allowed
        contracts.append(contract)
    return contracts


def _iter_template_files(resources_dir: Path) -> list[Path]:
    templates_root = resources_dir / "templates"
    seen: dict[str, Path] = {}
    files: list[Path] = []
    for tier in TEMPLATE_TIERS:
        tier_dir = templates_root / tier
        if not tier_dir.exists():
            continue
        for path in sorted(tier_dir.glob("*.tbm")):
            # pathlib's glob (unlike shell globbing) matches dotfiles too;
            # skip them explicitly so stray hidden files never become
            # catalog entries or get moved between tiers.
            if path.name.startswith("."):
                continue
            if path.name in seen:
                raise ValueError(
                    f"duplicate template filename across tiers: {path.name} "
                    f"found at both {seen[path.name]} and {path}"
                )
            seen[path.name] = path
            files.append(path)
    return files


def _iter_plain_resource_files(resources_dir: Path) -> list[Path]:
    files: list[Path] = []
    for dirname in sorted(PLAIN_RESOURCE_DIRS):
        directory = resources_dir / dirname
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            # Skip dotfiles (e.g. macOS ".DS_Store") and any stray cache
            # directories; they are filesystem noise, not corpus resources.
            if path.name.startswith("."):
                continue
            if path.is_file():
                files.append(path)
    return files


def _build_template_entry(
    path: Path,
    resources_dir: Path,
    overrides: dict[str, dict[str, object]],
) -> dict[str, object]:
    resource_id = path.stem
    metadata = extract_bookmark(path)
    tier, reasons = classify_bookmark(metadata)

    override = overrides.get(resource_id, {})
    parameters = _parameter_contracts(resource_id, override, metadata)

    inferred_family, inferred_intent = _infer_family_and_intent(resource_id)
    family = override.get("family", inferred_family)
    intent = override.get("intent", inferred_intent)

    canonical_path = resources_dir / "templates" / tier / path.name

    return {
        "id": resource_id,
        "type": "template",
        "family": family,
        "intent": intent,
        "path": _relative_path(canonical_path, resources_dir),
        "tier": tier,
        "classificationReasons": reasons,
        "datasources": sorted(metadata["datasources"]),
        "fields": metadata["fields"],
        "parameters": parameters,
        "keywords": _keywords(resource_id, extra=("template", tier)),
        "sha256": sha256(path),
    }


def _build_plain_entry(path: Path, resources_dir: Path) -> dict[str, object]:
    resource_id = path.stem
    resource_type = PLAIN_RESOURCE_DIRS.get(path.parent.name, path.parent.name)
    family, intent = _infer_family_and_intent(resource_id)

    return {
        "id": resource_id,
        "type": resource_type,
        "family": family,
        "intent": intent,
        "path": _relative_path(path, resources_dir),
        "tier": "reference",
        "classificationReasons": [],
        "datasources": [],
        "fields": [],
        "parameters": [],
        "keywords": _keywords(resource_id, extra=(resource_type,)),
        "sha256": sha256(path),
    }


def _validate_unique_ids(entries: list[dict[str, object]]) -> None:
    """Raise a clear error if any resource id collides across resource kinds.

    Resource IDs are derived from filename stems independently per directory
    (templates/unclassified|executable|reference, examples, references,
    starters), so a stem shared across two directories (e.g. a template and
    an example with the same name) would otherwise silently collide.
    """
    seen: dict[str, str] = {}
    for entry in entries:
        resource_id = entry["id"]
        if resource_id in seen:
            raise ValueError(
                f"duplicate resource id {resource_id!r}: "
                f"{seen[resource_id]} and {entry['path']} both resolve to "
                "the same catalog id"
            )
        seen[resource_id] = entry["path"]


def generate_catalog(plugin_root: Path) -> dict[str, object]:
    """Generate the full, deterministic resource catalog for a plugin root."""
    plugin_root = Path(plugin_root)
    resources_dir = plugin_root / "resources"
    overrides = _load_overrides(resources_dir)

    entries: list[dict[str, object]] = []
    for path in _iter_template_files(resources_dir):
        entries.append(_build_template_entry(path, resources_dir, overrides))
    for path in _iter_plain_resource_files(resources_dir):
        entries.append(_build_plain_entry(path, resources_dir))

    entries.sort(key=lambda entry: entry["id"])
    _validate_unique_ids(entries)

    return {
        "schemaVersion": 1,
        "generatedFrom": {
            "provenance": "./provenance.json",
            "overrides": "./catalog-overrides.json",
        },
        "resources": entries,
    }


def _apply_moves(resources_dir: Path, catalog: dict[str, object]) -> None:
    """Move each template into its canonical tier directory, preserving bytes."""
    templates_root = resources_dir / "templates"
    for entry in catalog["resources"]:
        if entry["type"] != "template":
            continue
        target = resources_dir / Path(entry["path"][2:])
        filename = target.name
        current = None
        for tier in TEMPLATE_TIERS:
            candidate = templates_root / tier / filename
            if candidate.exists():
                current = candidate
                break
        if current is None:
            raise FileNotFoundError(
                f"template file not found for resource {entry['id']!r}"
            )
        if current != target:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(target))


def _detect_drift(resources_dir: Path, catalog: dict[str, object]) -> list[str]:
    """Report templates whose physical location disagrees with the catalog."""
    problems: list[str] = []
    for entry in catalog["resources"]:
        if entry["type"] != "template":
            continue
        target = resources_dir / Path(entry["path"][2:])
        if not target.exists():
            problems.append(
                f"{entry['id']} expected at {entry['path']} but the file is "
                "not there (run --write to move it)"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic Tableau resource catalog."
    )
    parser.add_argument(
        "--plugin-root",
        type=Path,
        required=True,
        help="Path to the plugin root directory (containing resources/).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--write",
        action="store_true",
        help="Regenerate catalog.json and move templates into their tier.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Verify catalog.json and template locations are up to date.",
    )
    args = parser.parse_args(argv)

    plugin_root = Path(args.plugin_root)
    resources_dir = plugin_root / "resources"
    catalog_path = resources_dir / "catalog.json"

    try:
        catalog = generate_catalog(plugin_root)
    except ValueError as error:
        # Raised for duplicate resource ids or override/parameter mismatches.
        # Fail before any write or move happens in either mode.
        print(f"error: {error}", file=sys.stderr)
        return 1
    serialized = json.dumps(catalog, indent=2) + "\n"

    if args.write:
        _apply_moves(resources_dir, catalog)
        catalog_path.write_text(serialized, encoding="utf-8")
        print(f"wrote {catalog_path} with {len(catalog['resources'])} resources")
        return 0

    errors: list[str] = []
    if not catalog_path.exists():
        errors.append(f"{catalog_path} does not exist")
    else:
        existing = catalog_path.read_text(encoding="utf-8")
        if existing != serialized:
            errors.append(f"{catalog_path} is stale relative to generated output")
    errors.extend(_detect_drift(resources_dir, catalog))

    if errors:
        for message in errors:
            print(f"error: {message}", file=sys.stderr)
        return 1

    print("catalog.json is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())

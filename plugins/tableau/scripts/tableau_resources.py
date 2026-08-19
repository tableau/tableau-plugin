#!/usr/bin/env python3
"""Discovery, inspection, rendering, validation, and workbook transformation.

Provides ``list`` and ``inspect`` commands against ``resources/catalog.json``,
:func:`render_bookmark`, which converts one executable ``.tbm`` bookmark into a
worksheet/window fragment pair against caller-supplied datasource, field, and
parameter mappings, the ``instantiate`` and ``inject`` commands, which put that
pair into a starter or an existing ``.twb``, and the ``validate`` command,
which reports a workbook's structural errors.

Neither rendering nor injection guesses a mapping, and neither serializes a
donor bookmark or a caller's workbook through ``ElementTree``: both parse to
confirm structure and then perform bounded text splices so unrelated Tableau
XML survives byte-for-byte. A generated workbook is validated against the
input workbook's own validation result before it is written, so a run that
would introduce a new structural error leaves no output behind while a
workbook that arrived with errors can still be extended.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import NamedTuple
from xml.etree import ElementTree as ET
from xml.parsers import expat
from xml.sax.saxutils import escape as xml_escape

TOKEN_RE = re.compile(r"[a-z0-9]+")

# Bracketed Tableau identifiers escape a literal "]" by doubling it.
_BRACKET_CONTENT = r"(?:\]\]|[^\[\]])+"
QUALIFIED_REF_RE = re.compile(
    rf"\[({_BRACKET_CONTENT})\]\.\[({_BRACKET_CONTENT})\]"
)
# Column-instance names encode "derivation:field:role", e.g. [sum:ARR:qk].
DERIVED_SEGMENT_RE = re.compile(r"^([^:]+):(.+):([^:]+)$")
TEMPLATE_TOKEN_RE = re.compile(r"\{\{[^}]+\}\}")
# Tableau names a real workbook connection "federated.<hash>", so a rendered
# fragment legitimately carries the validated target's federated name. Any
# other federated token is donor residue or an unresolved placeholder.
FEDERATED_RE = re.compile(r"federated\.[\w.\-]*")
SIMPLE_ID_RE = re.compile(r"(<simple-id\b[^>]*?\buuid=)(['\"])[^'\"]*\2")
ATTRIBUTE_RE = re.compile(r"([\w:.\-]+)\s*=\s*(['\"])(.*?)\2", re.DOTALL)
NAMESPACE_DECLARATION_RE = re.compile(
    r"xmlns(?::[\w.\-]+)?\s*=\s*(['\"]).*?\1", re.DOTALL
)

# Tableau pseudo-fields and generated geographic fields are never donor
# columns, so they neither require nor accept a caller mapping.
PSEUDO_FIELD_NAMES = frozenset({"Multiple Values", "Multiple Names"})
GENERATED_FIELD_RE = re.compile(r"^(Latitude|Longitude) \(generated\)$")

# Attribute names whose value addresses the datasource: Tableau resolves them
# against the workbook's declared datasources, so one still holding the donor's
# name is genuine residue.
DATASOURCE_ADDRESS_ATTRIBUTES = ("name", "datasource")

# Attribute names whose value is the datasource's own name rather than a
# reference into it. ``caption`` joins the addressing pair here because it too
# is rewritten when a fragment is retargeted, but it labels the datasource
# rather than addressing it.
DATASOURCE_NAME_ATTRIBUTES = DATASOURCE_ADDRESS_ATTRIBUTES + ("caption",)

# Elements whose bracketed name attribute defines a field a view may reference.
FIELD_DEFINITION_TAGS = ("column", "column-instance", "group")

# A connection's physical columns are declared as <metadata-record> entries of
# this class; other classes describe the connection itself, not a field.
METADATA_RECORD_COLUMN_CLASS = "column"

# Tableau datatypes grouped into the families this module treats as
# interchangeable. Within a family a template survives being repointed at
# another field: the derivation, the shelf role, and the mark type all remain
# valid, so only the declared type has to change. Across families it does not,
# so a cross-family mapping is refused rather than rendered.
DATATYPE_FAMILIES = {
    "integer": "numeric",
    "real": "numeric",
    "date": "temporal",
    "datetime": "temporal",
    "string": "string",
    "boolean": "boolean",
    "spatial": "spatial",
}
NUMERIC_FAMILY = "numeric"

# Declared metadata of a mapped target field, rewritten onto the rendered
# dependency declaration so it describes the field it now names.
DEPENDENCY_METADATA_ATTRIBUTES = ("datatype", "user-datatype", "role")

# Tableau types a geographic role and a field reference identically, as
# QualifiedName-ST, so both are written "[a].[b]". These name a role in the
# geocoding hierarchy — semantic-role='[State].[Name]' on a column, and a
# <semantic-value key='[Country].[Name]'> geocoding default — and neither
# names a datasource. Field definitions are listed here too because their own
# attributes describe the field rather than pointing at another one.
NON_REFERENCE_TAGS = frozenset(FIELD_DEFINITION_TAGS) | {"semantic-value"}
NON_REFERENCE_ATTRIBUTES = frozenset({"semantic-role"})

# Containers whose contents reference datasource fields. Physical relation
# metadata inside <datasources> uses the same "[name].[name]" shape to name a
# table's column, so it is deliberately outside the reference scan.
FIELD_REFERENCE_CONTAINERS = ("worksheets", "dashboards", "windows")

# Containers a Tableau workbook must declare for a fragment to have anywhere
# to land, in the order they are reported.
REQUIRED_CONTAINERS = ("datasources", "worksheets", "windows")

# Donor-only provenance metadata: attributes that name a donor column without
# qualifying it with the datasource, so qualified-reference discovery cannot
# see them. They record where a column's aggregate role came from rather than
# taking part in the viz definition, so an unmapped one is dropped.
DONOR_METADATA_ATTRIBUTES = (("column", "aggregate-role-from"),)

# Parameter types a generated contract may declare. A declared token with any
# other type has no usable contract and is rejected rather than guessed.
PARAMETER_TYPES = frozenset({"date", "enum", "number", "string"})

FRAGMENT_UUID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://tableau.com/plugin-codex/bookmark-fragment"
)
WRAPPER_TAG = "codex-fragment-wrapper"

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
STARTER_RELATIVE_PATH = "starters/minimal-workbook.twb"


class ResourceError(ValueError):
    """Raised for an invalid resource request or an unsafe rendering result."""


class FieldMetadata(NamedTuple):
    """One target field's declared type and role.

    Any member is ``None`` when the workbook does not declare it; a caller
    that needs a value must decide for itself whether to fail rather than
    substitute one.
    """

    datatype: str | None
    user_datatype: str | None
    role: str | None


class DatasourceMetadata(NamedTuple):
    """One global datasource's display caption and fields.

    ``caption`` is the label Tableau shows; the internal name, which may be a
    ``federated.<hash>`` string, stays the key this is looked up by.
    """

    caption: str
    fields: dict[str, FieldMetadata]


def _datatype_family(datatype: str | None) -> str | None:
    """Return the compatibility family of a Tableau datatype, if it has one."""
    return DATATYPE_FAMILIES.get((datatype or "").strip().lower())


def load_catalog(plugin_root: Path) -> dict[str, object]:
    """Load and parse ``resources/catalog.json`` under ``plugin_root``."""
    catalog_path = Path(plugin_root) / "resources" / "catalog.json"
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def find_resource(catalog: dict[str, object], resource_id: str) -> dict[str, object]:
    """Return the catalog entry with ``id == resource_id``.

    Raises ``KeyError`` if no such resource exists.
    """
    for entry in catalog["resources"]:
        if entry["id"] == resource_id:
            return entry
    raise KeyError(resource_id)


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _searchable_text(entry: dict[str, object]) -> str:
    parts = [
        entry.get("id") or "",
        entry.get("intent") or "",
        entry.get("family") or "",
        " ".join(entry.get("keywords") or []),
    ]
    return " ".join(parts).lower()


def search_resources(
    catalog: dict[str, object],
    *,
    query: str | None = None,
    family: str | None = None,
    resource_type: str | None = None,
    tier: str | None = None,
) -> list[dict[str, object]]:
    """Filter and rank catalog entries by query terms and exact-match filters.

    Search splits ``query`` into lowercase alphanumeric terms. An entry
    matches only when every term appears in its ID, intent, family, or
    keywords. Results are sorted with exact ID matches first, then entries
    whose intent contains a query term, then by ID.
    """
    entries = list(catalog["resources"])

    if family is not None:
        entries = [entry for entry in entries if entry.get("family") == family]
    if resource_type is not None:
        entries = [entry for entry in entries if entry.get("type") == resource_type]
    if tier is not None:
        entries = [entry for entry in entries if entry.get("tier") == tier]

    terms = _tokenize(query) if query else []
    if terms:
        matched = []
        for entry in entries:
            haystack = _searchable_text(entry)
            if all(term in haystack for term in terms):
                matched.append(entry)
        entries = matched

    def sort_key(entry: dict[str, object]) -> tuple[int, int, str]:
        resource_id = entry["id"]
        exact_id_match = 0 if terms and _tokenize(resource_id) == terms else 1
        intent_text = (entry.get("intent") or "").lower()
        intent_match = 0 if terms and any(term in intent_text for term in terms) else 1
        return (exact_id_match, intent_match, resource_id)

    entries.sort(key=sort_key)
    return entries


def parse_assignments(values: list[str]) -> dict[str, str]:
    """Parse ``NAME=VALUE`` CLI assignments into a mapping.

    Rejects a missing separator, a blank name or value, and a repeated name so
    a mistyped flag can never silently drop or override an earlier mapping.
    """
    assignments: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ResourceError(f"Expected NAME=VALUE, got: {value}")
        name, mapped = value.split("=", 1)
        normalized_name = name.strip()
        normalized_value = mapped.strip()
        if (
            not normalized_name
            or not normalized_value
            or normalized_name in assignments
        ):
            raise ResourceError(f"Invalid or duplicate assignment: {value}")
        assignments[normalized_name] = normalized_value
    return assignments


def escape_bracket(name: str) -> str:
    """Escape a Tableau identifier for use inside ``[...]``."""
    return name.replace("]", "]]")


def unescape_bracket(name: str) -> str:
    """Decode Tableau's doubled closing brackets in an identifier."""
    return name.replace("]]", "]")


def escape_attribute(value: str) -> str:
    """XML-escape a value for use inside a single- or double-quoted attribute."""
    return xml_escape(value, {"'": "&apos;", '"': "&quot;"})


def _unescape(value: str) -> str:
    return html.unescape(value)


def _logical_field_name(raw: str) -> str:
    """Decode a raw bracket-content field name into its catalog form."""
    return unescape_bracket(_unescape(raw))


def _bracket_reference(name: str) -> str:
    """Render ``name`` as it must appear inside a bracketed XML reference."""
    return escape_attribute(escape_bracket(name))


def _tag_end(data: bytes, index: int) -> int:
    """Return the offset just past the ``>`` closing the tag at ``index``.

    Quote-aware so a ``>`` inside an attribute value is not mistaken for the
    end of the tag.
    """
    quote = b""
    position = index
    while position < len(data):
        char = data[position : position + 1]
        if quote:
            if char == quote:
                quote = b""
        elif char in (b"'", b'"'):
            quote = char
        elif char == b">":
            return position + 1
        position += 1
    raise ResourceError("Malformed bookmark: unterminated XML tag")


def _scan_elements(data: bytes) -> list[tuple[str, int, int, int]]:
    """Return ``(tag, depth, start, end)`` byte spans for every element.

    Offsets come from the expat parser, so a span is only ever reported for
    structure the parser itself confirmed.
    """
    parser = expat.ParserCreate()
    elements: list[tuple[str, int, int, int]] = []
    stack: list[tuple[str, int, int, int, bool]] = []

    def start(name: str, _attributes: dict[str, str]) -> None:
        start_offset = parser.CurrentByteIndex
        start_tag_end = _tag_end(data, start_offset)
        stack.append(
            (
                name,
                len(stack),
                start_offset,
                start_tag_end,
                data[start_tag_end - 2 : start_tag_end] == b"/>",
            )
        )

    def end(name: str) -> None:
        tag, depth, start_offset, start_tag_end, self_closing = stack.pop()
        end_offset = (
            start_tag_end
            if self_closing
            else _tag_end(data, parser.CurrentByteIndex)
        )
        elements.append((tag, depth, start_offset, end_offset))

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise ResourceError(f"Malformed bookmark XML: {error}") from error
    return elements


def _tag_attribute_spans(data: bytes, start: int) -> list[tuple[str, str, int, int]]:
    """Return ``(name, raw value, byte start, byte end)`` per attribute.

    The spans are absolute byte offsets into ``data`` so an attribute can be
    spliced out without reserializing its element.
    """
    start_tag = data[start : _tag_end(data, start)].decode("utf-8")
    spans: list[tuple[str, str, int, int]] = []
    for match in ATTRIBUTE_RE.finditer(start_tag):
        offset = start + len(start_tag[: match.start()].encode("utf-8"))
        spans.append(
            (
                match.group(1),
                match.group(3),
                offset,
                offset + len(match.group(0).encode("utf-8")),
            )
        )
    return spans


def _tag_attributes(data: bytes, start: int) -> dict[str, str]:
    """Return raw, still XML-escaped attributes of the tag at ``start``."""
    return {
        name: value for name, value, _start, _end in _tag_attribute_spans(data, start)
    }


def _remove_elements(text: str, tag: str) -> str:
    """Delete every outermost ``<tag>`` element from a fragment."""
    data = text.encode("utf-8")
    candidates = [
        (start, end)
        for element_tag, _depth, start, end in _scan_elements(data)
        if element_tag == tag
    ]
    spans: list[tuple[int, int]] = []
    for start, end in sorted(candidates, key=lambda span: (span[0], -span[1])):
        if any(
            outer_start <= start and end <= outer_end
            for outer_start, outer_end in spans
        ):
            continue
        spans.append((start, end))

    for start, end in sorted(spans, reverse=True):
        line_start = start
        while line_start > 0 and data[line_start - 1 : line_start] in (b" ", b"\t"):
            line_start -= 1
        if data[line_start - 1 : line_start] != b"\n":
            line_start = start
        stop = end
        if data[stop : stop + 1] == b"\n":
            stop += 1
        data = data[:line_start] + data[stop:]
    return data.decode("utf-8")


def _namespace_declarations(root_start_tag: str) -> str:
    return " ".join(
        match.group(0) for match in NAMESPACE_DECLARATION_RE.finditer(root_start_tag)
    )


def _wrap_fragment(fragment: str, namespaces: str) -> str:
    opening = f"<{WRAPPER_TAG} {namespaces}>" if namespaces else f"<{WRAPPER_TAG}>"
    return f"{opening}\n{fragment}\n</{WRAPPER_TAG}>"


def _parse_wrapped(fragment: str, namespaces: str, kind: str) -> ET.Element:
    try:
        wrapper = ET.fromstring(_wrap_fragment(fragment, namespaces))
    except ET.ParseError as error:
        raise ResourceError(
            f"Rendered {kind} fragment is not well-formed XML: {error}"
        ) from error
    children = list(wrapper)
    if len(children) != 1:
        raise ResourceError(
            f"Rendered {kind} fragment must contain exactly one root element"
        )
    return children[0]


def _confirm_fragment(fragment: str, expected: ET.Element, namespaces: str) -> None:
    """Verify a spliced fragment reparses to the element the parser reported."""
    extracted = _parse_wrapped(fragment, namespaces, expected.tag)
    if extracted.tag != expected.tag or extracted.attrib != expected.attrib:
        raise ResourceError(
            f"Extracted <{expected.tag}> fragment does not match the parsed bookmark"
        )
    if [child.tag for child in extracted] != [child.tag for child in expected]:
        raise ResourceError(
            f"Extracted <{expected.tag}> fragment lost or gained child elements"
        )


def _template_path(plugin_root: Path, entry: dict[str, object]) -> Path:
    relative = str(entry["path"])
    if relative.startswith("./"):
        relative = relative[2:]
    return Path(plugin_root) / "resources" / relative


def _executable_entry(
    catalog: dict[str, object], resource_id: str
) -> dict[str, object]:
    try:
        entry = find_resource(catalog, resource_id)
    except KeyError:
        raise ResourceError(f"Unknown resource: {resource_id}") from None
    if entry.get("tier") != "executable":
        reasons = (
            ", ".join(entry.get("classificationReasons") or []) or "not executable"
        )
        raise ResourceError(
            f"Resource {resource_id} is reference-only and cannot be rendered "
            f"({reasons})"
        )
    return entry


def _read_verified_bookmark(plugin_root: Path, entry: dict[str, object]) -> bytes:
    path = _template_path(plugin_root, entry)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ResourceError(f"Cannot read template {entry['path']}: {error}") from error
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry.get("sha256"):
        raise ResourceError(
            f"Template {entry['path']} does not match the catalog hash "
            f"(expected {entry.get('sha256')}, found {digest}); regenerate the catalog"
        )
    return data


def _single_span(
    elements: list[tuple[str, int, int, int]], tag: str
) -> tuple[int, int] | None:
    spans = [
        (start, end)
        for element_tag, depth, start, end in elements
        if depth == 1 and element_tag == tag
    ]
    if len(spans) > 1:
        return None
    return spans[0] if spans else None


def _extract_fragments(data: bytes) -> tuple[str, str, str | None, ET.Element, str]:
    """Extract the ``<window>``, ``<table>``, and root ``<cards>`` fragments.

    Offsets come from expat and every fragment is reparsed and compared with
    the element ``ElementTree`` reported, so a text splice can never silently
    disagree with the document's real structure.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ResourceError(f"Malformed bookmark XML: {error}") from error
    if root.tag != "bookmark":
        raise ResourceError(
            f"Template root element must be <bookmark>, found <{root.tag}>"
        )

    elements = _scan_elements(data)
    root_start = next(
        start
        for tag, depth, start, _end in elements
        if depth == 0 and tag == "bookmark"
    )
    namespaces = _namespace_declarations(
        data[root_start : _tag_end(data, root_start)].decode("utf-8")
    )

    window_span = _single_span(elements, "window")
    table_span = _single_span(elements, "table")
    if (
        window_span is None
        or table_span is None
        or len(root.findall("window")) != 1
        or len(root.findall("table")) != 1
    ):
        raise ResourceError(
            "Template must contain exactly one <window> and one <table> element"
        )
    cards_span = _single_span(elements, "cards")

    window = data[window_span[0] : window_span[1]].decode("utf-8")
    table = data[table_span[0] : table_span[1]].decode("utf-8")
    _confirm_fragment(window, root.find("window"), namespaces)
    _confirm_fragment(table, root.find("table"), namespaces)
    cards_spans = [
        (start, end)
        for tag, depth, start, end in elements
        if depth == 1 and tag == "cards"
    ]
    if len(cards_spans) > 1:
        raise ResourceError(
            "Template contains more than one root-level <cards> element"
        )
    cards = (
        data[cards_span[0] : cards_span[1]].decode("utf-8")
        if cards_span is not None
        else None
    )
    return window, table, cards, root, namespaces


def _hoist_cards(window: str, cards: str | None) -> str:
    """Move a root-level ``<cards>`` block into a window that lacks one."""
    if cards is None:
        return window
    data = window.encode("utf-8")
    existing = [
        tag
        for tag, depth, _start, _end in _scan_elements(data)
        if depth == 1 and tag == "cards"
    ]
    if existing:
        return window
    insert_at = _tag_end(data, 0)
    if data[insert_at - 2 : insert_at] == b"/>":
        raise ResourceError("Cannot hoist <cards> into a self-closing <window>")
    return (
        data[:insert_at].decode("utf-8")
        + "\n"
        + cards
        + data[insert_at:].decode("utf-8")
    )


def _donor_dependency_spans(
    data: bytes, elements: list[tuple[str, int, int, int]], donor: str
) -> list[tuple[int, int]]:
    """Return the byte spans of ``<datasource-dependencies>`` for the donor."""
    return [
        (start, end)
        for tag, _depth, start, end in elements
        if tag == "datasource-dependencies"
        and _unescape(_tag_attributes(data, start).get("datasource") or "") == donor
    ]


def _declared_fields(table: str, donor: str) -> tuple[dict[str, str], set[str]]:
    """Return the donor's column-instance-to-base map and declared base fields.

    Scoped to ``<datasource-dependencies>`` blocks belonging to the donor so a
    pseudo-datasource block (for example workbook parameters) is never treated
    as a mappable donor column.
    """
    data = table.encode("utf-8")
    elements = _scan_elements(data)
    scopes = _donor_dependency_spans(data, elements, donor)
    if not scopes:
        raise ResourceError(
            f"Template does not contain datasource dependencies for donor {donor}"
        )

    instances: dict[str, str] = {}
    columns: set[str] = set()
    for tag, _depth, start, _end in elements:
        if tag not in ("column", "column-instance"):
            continue
        if not any(begin <= start < finish for begin, finish in scopes):
            continue
        attributes = _tag_attributes(data, start)
        name = attributes.get("name") or ""
        if not (name.startswith("[") and name.endswith("]")):
            continue
        bare = name[1:-1]
        if tag == "column-instance":
            base = attributes.get("column") or ""
            if base.startswith("[") and base.endswith("]"):
                instances[bare] = base[1:-1]
        elif attributes.get("datatype"):
            columns.add(bare)
    return instances, columns


def _remove_unused_donor_declarations(
    table: str, donor: str, required_fields: set[str]
) -> str:
    """Drop donor column metadata that has no explicit mapping contract."""
    data = table.encode("utf-8")
    elements = _scan_elements(data)
    scopes = _donor_dependency_spans(data, elements, donor)
    spans: list[tuple[int, int]] = []
    for tag, _depth, start, end in elements:
        if tag not in ("column", "column-instance"):
            continue
        if not any(begin <= start < finish for begin, finish in scopes):
            continue
        attributes = _tag_attributes(data, start)
        reference = (
            attributes.get("name") if tag == "column" else attributes.get("column")
        ) or ""
        if not (reference.startswith("[") and reference.endswith("]")):
            continue
        logical_name = _logical_field_name(reference[1:-1])
        if logical_name in required_fields or _is_exempt_field(logical_name):
            continue
        spans.append((start, end))

    for start, end in sorted(spans, reverse=True):
        line_start = start
        while line_start > 0 and data[line_start - 1 : line_start] in (b" ", b"\t"):
            line_start -= 1
        if data[line_start - 1 : line_start] != b"\n":
            line_start = start
        stop = end
        if data[stop : stop + 1] == b"\n":
            stop += 1
        data = data[:line_start] + data[stop:]
    return data.decode("utf-8")


def _catalog_source_datatypes(entry: dict) -> dict[str, str]:
    """Return the datatype the catalog records for each donor source field."""
    return {
        str(field["sourceField"]): str(field["datatype"])
        for field in entry.get("fields") or []
        if field.get("sourceField") and field.get("datatype")
    }


def _donor_column_datatypes(table: str, donor: str) -> dict[str, str]:
    """Return the datatype each donor dependency ``<column>`` declares.

    Used only as a fallback source contract: the catalog records the same
    datatypes and is authoritative, but a template whose catalog entry predates
    that field still declares it here.
    """
    data = table.encode("utf-8")
    elements = _scan_elements(data)
    scopes = _donor_dependency_spans(data, elements, donor)
    declared: dict[str, str] = {}
    for tag, _depth, start, _end in elements:
        if tag != "column" or not any(
            begin <= start < finish for begin, finish in scopes
        ):
            continue
        attributes = _tag_attributes(data, start)
        name = attributes.get("name") or ""
        datatype = attributes.get("datatype")
        if datatype and name.startswith("[") and name.endswith("]"):
            declared.setdefault(_logical_field_name(name[1:-1]), _unescape(datatype))
    return declared


def _attribute_quote(data: bytes, start: int, end: int) -> str:
    """Return the quote character an attribute's value is written with."""
    text = data[start:end].decode("utf-8")
    return text[text.index("=") + 1 :].lstrip()[0]


def _retype_mapped_columns(
    table: str,
    donor: str,
    field_mappings: dict[str, str],
    target_fields: dict[str, FieldMetadata],
) -> str:
    """Restate a mapped dependency column's type from the target's metadata.

    Once a declaration's name has been rewritten to a target field, the
    donor's ``datatype``, ``user-datatype``, and ``role`` describe a field that
    is no longer there, so they are replaced with the target's own. Nothing
    else on the declaration is touched: the aggregation, the pivot, the
    nominal/ordinal/quantitative pair and the rest all stay correct because a
    mapping may not cross a datatype family. An attribute the donor did not
    declare is not added, and a value the workbook does not declare is not
    invented — for ``user-datatype`` the target's datatype stands in, which is
    what Tableau writes for a field whose display type is its storage type.

    Each replacement is spliced over the attribute's own byte span, so no
    other byte of the fragment moves.
    """
    if not field_mappings or not target_fields:
        return table
    data = table.encode("utf-8")
    elements = _scan_elements(data)
    scopes = _donor_dependency_spans(data, elements, donor)
    edits: list[tuple[int, int, bytes]] = []
    for tag, _depth, start, _end in elements:
        if tag != "column" or not any(
            begin <= start < finish for begin, finish in scopes
        ):
            continue
        spans = _tag_attribute_spans(data, start)
        raw = next((value for name, value, _s, _e in spans if name == "name"), "")
        if not (raw.startswith("[") and raw.endswith("]")):
            continue
        metadata = target_fields.get(
            field_mappings.get(_logical_field_name(raw[1:-1]), "")
        )
        if metadata is None:
            continue
        wanted = {
            "datatype": metadata.datatype,
            "user-datatype": metadata.user_datatype or metadata.datatype,
            "role": metadata.role,
        }
        for name, value, span_start, span_end in spans:
            if name not in DEPENDENCY_METADATA_ATTRIBUTES:
                continue
            replacement = wanted[name]
            if replacement is None or _unescape(value) == replacement:
                continue
            quote = _attribute_quote(data, span_start, span_end)
            edits.append(
                (
                    span_start,
                    span_end,
                    f"{name}={quote}{escape_attribute(replacement)}{quote}".encode(
                        "utf-8"
                    ),
                )
            )
    for start, end, replacement in sorted(edits, reverse=True):
        data = data[:start] + replacement + data[end:]
    return data.decode("utf-8")


def _donor_metadata_references(
    table: str, donor: str
) -> list[tuple[str, str, int, int]]:
    """Return donor-only metadata references as ``(logical, raw, start, end)``.

    Each entry is one occurrence of a :data:`DONOR_METADATA_ATTRIBUTES`
    attribute whose value is a single bracketed donor field, with the byte span
    of the whole attribute so it can be stripped when the caller omits it.
    """
    data = table.encode("utf-8")
    elements = _scan_elements(data)
    scopes = _donor_dependency_spans(data, elements, donor)
    found: list[tuple[str, str, int, int]] = []
    for tag, _depth, start, _end in elements:
        if not any(tag == element for element, _attribute in DONOR_METADATA_ATTRIBUTES):
            continue
        if not any(begin <= start < finish for begin, finish in scopes):
            continue
        for name, value, span_start, span_end in _tag_attribute_spans(data, start):
            if (tag, name) not in DONOR_METADATA_ATTRIBUTES:
                continue
            if not (value.startswith("[") and value.endswith("]")):
                raise ResourceError(
                    f"Template metadata attribute {name} is not a single field "
                    f"reference: {value}"
                )
            raw = value[1:-1]
            logical_name = _logical_field_name(raw)
            if _is_exempt_field(logical_name):
                continue
            found.append((logical_name, raw, span_start, span_end))
    return found


def _donor_metadata_fields(table: str, donor: str) -> dict[str, set[str]]:
    """Map each metadata-only donor field to the raw forms naming it."""
    discovered: dict[str, set[str]] = {}
    for logical_name, raw, _start, _end in _donor_metadata_references(table, donor):
        discovered.setdefault(logical_name, set()).add(raw)
    return discovered


def _strip_unmapped_donor_metadata(table: str, donor: str, mapped: set[str]) -> str:
    """Delete donor-only metadata attributes the caller did not map.

    Dropping provenance metadata is safe — Tableau re-derives it from the
    target datasource — and it is the only alternative to emitting a donor
    field name the target datasource may not have.
    """
    data = table.encode("utf-8")
    spans = sorted(
        (
            (start, end)
            for logical_name, _raw, start, end in _donor_metadata_references(
                table, donor
            )
            if logical_name not in mapped
        ),
        reverse=True,
    )
    for start, end in spans:
        while start > 0 and data[start - 1 : start] in (b" ", b"\t"):
            start -= 1
        data = data[:start] + data[end:]
    return data.decode("utf-8")


def _is_exempt_field(logical_name: str) -> bool:
    return (
        logical_name.startswith(":")
        or logical_name in PSEUDO_FIELD_NAMES
        or bool(GENERATED_FIELD_RE.match(logical_name))
    )


def _donor_source_fields(
    text: str, donor: str, instances: dict[str, str], columns: set[str]
) -> dict[str, set[str]]:
    """Map each donor field logical name to the raw forms found in ``text``.

    Every donor-qualified reference in the raw XML is resolved, not only the
    fields the catalog recorded as placed on a shelf, so a reference hiding in
    a card, style rule, or sort can never survive unmapped.
    """
    discovered: dict[str, set[str]] = {}
    for datasource_raw, field_raw in QUALIFIED_REF_RE.findall(text):
        if _logical_field_name(datasource_raw) != donor:
            continue
        if _is_exempt_field(_logical_field_name(field_raw)):
            continue
        base_raw = _resolve_base_field(field_raw, instances, columns)
        if base_raw is None:
            raise ResourceError(
                f"Template contains an unresolved donor field reference: "
                f"[{donor}].[{_logical_field_name(field_raw)}]"
            )
        discovered.setdefault(_logical_field_name(base_raw), set()).add(base_raw)
    return discovered


def _resolve_base_field(
    field_raw: str, instances: dict[str, str], columns: set[str]
) -> str | None:
    if field_raw in instances:
        return instances[field_raw]
    if field_raw in columns:
        return field_raw
    derived = DERIVED_SEGMENT_RE.match(field_raw)
    if derived:
        return derived.group(2)
    return None


def _check_supplied_value(label: str, name: str, value: str) -> None:
    if not value.strip():
        raise ResourceError(f"{label} {name} must have a non-empty value")
    if TEMPLATE_TOKEN_RE.search(value) or "{{" in value:
        raise ResourceError(
            f"{label} {name} value must not contain a template token: {value}"
        )


def _validate_field_mappings(
    required: dict[str, set[str]],
    optional: dict[str, set[str]],
    field_mappings: dict[str, str] | None,
) -> dict[str, str]:
    supplied = dict(field_mappings or {})
    allowed = set(required) | set(optional)
    unknown = sorted(name for name in supplied if name not in allowed)
    if unknown:
        raise ResourceError(
            f"Unknown field mappings: {', '.join(unknown)} "
            f"(declared fields: {', '.join(sorted(allowed))})"
        )
    missing = sorted(name for name in required if name not in supplied)
    if missing:
        raise ResourceError(f"Missing field mappings: {', '.join(missing)}")
    for name, target in supplied.items():
        _check_supplied_value("Field mapping", name, target)
    return supplied


def parameter_contracts(entry: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return the resource's typed parameter contracts, keyed by name.

    The generated catalog carries a complete typed contract for every explicit
    ``{{PARAMETER}}`` token, so validation never depends on
    ``catalog-overrides.json`` being present at runtime. A declared token
    without a recognized type — a stale or hand-edited catalog — is rejected
    rather than validated loosely.
    """
    contracts: dict[str, dict[str, object]] = {}
    for declared in entry.get("parameters") or []:
        if not isinstance(declared, dict) or not declared.get("name"):
            raise ResourceError(
                f"Resource {entry['id']} declares parameter {declared!r} without a "
                "typed contract; regenerate the catalog"
            )
        name = str(declared["name"])
        kind = declared.get("type")
        if kind not in PARAMETER_TYPES:
            raise ResourceError(
                f"Parameter {name} of resource {entry['id']} has no typed contract "
                f"(type={kind!r}); regenerate the catalog"
            )
        if kind == "enum" and not (declared.get("allowed") or []):
            raise ResourceError(
                f"Enum parameter {name} of resource {entry['id']} declares no "
                "allowed values; regenerate the catalog"
            )
        contracts[name] = declared
    return contracts


def _validate_parameters(
    contracts: dict[str, dict[str, object]],
    parameters: dict[str, str] | None,
) -> dict[str, str]:
    supplied = dict(parameters or {})
    declared_names = list(contracts)
    unknown = sorted(name for name in supplied if name not in declared_names)
    if unknown:
        raise ResourceError(
            f"Unknown parameters: {', '.join(unknown)} "
            f"(declared parameters: {', '.join(sorted(declared_names)) or 'none'})"
        )

    validated: dict[str, str] = {}
    missing: list[str] = []
    for name in sorted(declared_names):
        contract = contracts[name]
        if name not in supplied:
            if contract.get("required", True):
                missing.append(name)
            continue
        value = supplied[name]
        _check_supplied_value("Parameter", name, value)
        kind = contract["type"]
        if kind == "date":
            try:
                datetime.date.fromisoformat(value)
            except ValueError:
                raise ResourceError(
                    f"Parameter {name} must be an ISO-8601 date (YYYY-MM-DD), "
                    f"got: {value}"
                ) from None
        elif kind == "enum":
            allowed = contract.get("allowed") or []
            if value not in allowed:
                raise ResourceError(
                    f"Parameter {name} must be one of: {', '.join(allowed)} "
                    f"(got: {value})"
                )
        elif kind == "number":
            try:
                float(value)
            except ValueError:
                raise ResourceError(
                    f"Parameter {name} must be a number, got: {value}"
                ) from None
        validated[name] = value
    if missing:
        raise ResourceError(f"Missing parameters: {', '.join(missing)}")
    return validated


def _replace_datasource(
    text: str, donor: str, target: str, target_caption: str | None = None
) -> str:
    """Rewrite donor datasource names in qualified references and attributes.

    ``name`` and ``datasource`` attributes address the datasource, so they take
    its internal name, and so does every qualified reference. ``caption`` is
    the label Tableau displays, so it takes ``target_caption``: a workbook's
    internal name is often a ``federated.<hash>`` string, and putting that in
    the caption would show the hash to the reader. It defaults to the internal
    name, which is the right label for a datasource that declares no caption.
    """
    text = QUALIFIED_REF_RE.sub(
        lambda match: (
            f"[{_bracket_reference(target)}].[{match.group(2)}]"
            if _logical_field_name(match.group(1)) == donor
            else match.group(0)
        ),
        text,
    )
    replacements = {
        attribute: escape_attribute(
            target if attribute != "caption" or target_caption is None
            else target_caption
        )
        for attribute in DATASOURCE_NAME_ATTRIBUTES
    }

    def replace_attribute(match: re.Match[str]) -> str:
        name, quote, value = match.groups()
        if name in DATASOURCE_NAME_ATTRIBUTES and _unescape(value) == donor:
            return f"{name}={quote}{replacements[name]}{quote}"
        return match.group(0)

    return ATTRIBUTE_RE.sub(replace_attribute, text)


def _field_patterns(raw_forms: list[str]) -> tuple[re.Pattern[str], re.Pattern[str]]:
    # Longest raw form first so a field name that is a prefix of another can
    # never win the match.
    alternation = "|".join(
        re.escape(form) for form in sorted(raw_forms, key=len, reverse=True)
    )
    base = re.compile(rf"\[({alternation})\](?!\.\[)")
    derived = re.compile(rf"\[([^\[\]:]+):({alternation}):([^\[\]:]+)\]")
    return base, derived


def _replace_fields(text: str, raw_to_target: dict[str, str]) -> str:
    """Rewrite bracketed base fields and ``derivation:field:role`` segments.

    Both replacements run as a single pass over the alternation of source
    names so mappings that swap two fields cannot chain into each other.
    """
    if not raw_to_target:
        return text
    base, derived = _field_patterns(list(raw_to_target))
    text = base.sub(lambda match: f"[{raw_to_target[match.group(1)]}]", text)
    return derived.sub(
        lambda match: (
            f"[{match.group(1)}:{raw_to_target[match.group(2)]}:{match.group(3)}]"
        ),
        text,
    )


def _replace_parameters(text: str, parameters: dict[str, str]) -> str:
    for name, value in parameters.items():
        text = text.replace("{{" + name + "}}", escape_attribute(value))
    return text


def _fragment_uuid(resource_id: str, worksheet_name: str, kind: str) -> str:
    derived = uuid.uuid5(
        FRAGMENT_UUID_NAMESPACE, f"{resource_id}\n{worksheet_name}\n{kind}"
    )
    return "{%s}" % str(derived).upper()


def _replace_simple_ids(fragment: str, kind: str, identifier: str) -> str:
    """Replace the fragment's own ``simple-id`` with a derived identifier.

    One identifier is derived per fragment, so a fragment carrying more than
    one ``<simple-id>`` is rejected rather than given duplicate identifiers.
    """
    if len(SIMPLE_ID_RE.findall(fragment)) > 1:
        raise ResourceError(
            f"Template {kind} fragment declares more than one <simple-id>"
        )
    return SIMPLE_ID_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{identifier}{match.group(2)}",
        fragment,
    )


def _set_window_identity(window: str, worksheet_name: str) -> str:
    """Force the window's class and name to the output worksheet name."""
    data = window.encode("utf-8")
    tag_end = _tag_end(data, 0)
    start_tag = data[:tag_end].decode("utf-8")
    self_closing = start_tag.endswith("/>")
    preserved = [
        f"{name}={quote}{value}{quote}"
        for name, quote, value in (
            (match.group(1), match.group(2), match.group(3))
            for match in ATTRIBUTE_RE.finditer(start_tag)
        )
        if name not in ("class", "name")
    ]
    attributes = [
        "class='worksheet'",
        f"name='{escape_attribute(worksheet_name)}'",
        *preserved,
    ]
    rebuilt = f"<window {' '.join(attributes)}{' />' if self_closing else '>'}"
    return rebuilt + data[tag_end:].decode("utf-8")


def _without_target_caption(fragment: str, target_caption: str | None) -> str:
    """Drop every ``caption`` attribute holding the target's own label.

    The donor-text scan below looks for the donor's name anywhere in the
    fragment, which is deliberately blunt: it is the check that catches donor
    residue in places this module does not enumerate. But a target datasource
    may legitimately be captioned after the donor — "Sample - Superstore" is a
    real workbook's label, not just a template's donor — and the renderer
    writes that caption itself. Removing exactly the attributes it wrote, and
    only where the value is the whole caption, keeps the scan blunt everywhere
    else: a caption on another element, or one that merely contains the
    donor's name, is left in place to be judged.
    """
    if target_caption is None:
        return fragment
    return ATTRIBUTE_RE.sub(
        lambda match: (
            ""
            if match.group(1) == "caption"
            and _unescape(match.group(3)) == target_caption
            else match.group(0)
        ),
        fragment,
    )


def _reject_unsafe_output(
    fragments: dict[str, str],
    *,
    donor: str,
    target_datasource: str,
    raw_to_logical: dict[str, str],
    field_mappings: dict[str, str],
    target_caption: str | None = None,
) -> None:
    """Fail closed on any donor residue, stale field, or unresolved token.

    ``raw_to_logical`` covers every donor field reference discovered in the
    template, mapped or not, so an unmapped donor field that escaped stripping
    is caught here rather than emitted.

    ``target_caption`` is the label the renderer gave the target datasource.
    It is exempt from the donor-name scan, because a caption displays a
    datasource rather than addressing one: no amount of donor-looking text in
    it can make the output point back at the donor. Everything that does
    address a datasource — a qualified reference, a ``name`` or ``datasource``
    attribute — is judged unchanged. Omitting it exempts nothing.
    """
    # A source name that is also somebody's mapping target legitimately
    # survives in the output, so it cannot be checked for residue.
    targets = set(field_mappings.values())
    stale_raw = [
        raw
        for raw, logical in raw_to_logical.items()
        if field_mappings.get(logical) != logical and logical not in targets
    ]
    base_pattern, derived_pattern = (
        _field_patterns(stale_raw) if stale_raw else (None, None)
    )

    for kind, fragment in fragments.items():
        if donor != target_datasource:
            donor_qualified = any(
                _logical_field_name(datasource_raw) == donor
                for datasource_raw, _field_raw in QUALIFIED_REF_RE.findall(fragment)
            )
            donor_attribute = any(
                name in DATASOURCE_ADDRESS_ATTRIBUTES and _unescape(value) == donor
                for name, _quote, value in ATTRIBUTE_RE.findall(fragment)
            )
            donor_text = donor not in target_datasource and donor in _unescape(
                _without_target_caption(fragment, target_caption)
            )
            if donor_qualified or donor_attribute or donor_text:
                raise ResourceError(
                    f"Rendered {kind} fragment still references the donor "
                    f"datasource {donor}"
                )
        if base_pattern is not None:
            stale = base_pattern.search(fragment) or derived_pattern.search(fragment)
            if stale:
                raise ResourceError(
                    f"Rendered {kind} fragment still references the unmapped donor "
                    f"field {stale.group(0)}"
                )
        token = TEMPLATE_TOKEN_RE.search(fragment)
        if token:
            raise ResourceError(
                f"Rendered {kind} fragment contains an unresolved template token: "
                f"{token.group(0)}"
            )
        foreign = next(
            (
                match.group(0)
                for match in FEDERATED_RE.finditer(fragment)
                if _unescape(match.group(0)) != target_datasource
            ),
            None,
        )
        if foreign is not None:
            raise ResourceError(
                f"Rendered {kind} fragment references the federated datasource "
                f"{foreign}, which is not the target datasource "
                f"{target_datasource}"
            )


def render_bookmark(
    plugin_root: Path,
    resource_id: str,
    worksheet_name: str,
    datasource_name: str,
    field_mappings: dict[str, str],
    parameters: dict[str, str],
    *,
    datasource_caption: str | None = None,
    target_fields: dict[str, FieldMetadata] | None = None,
) -> tuple[str, str]:
    """Render one executable bookmark into worksheet and window fragments.

    Returns the ``<worksheet>`` and ``<window>`` XML text for insertion into a
    workbook. Raises :class:`ResourceError` for a non-executable resource,
    catalog drift, an incomplete or undeclared mapping, an invalid parameter,
    a mapping the target's types cannot support, or any output that still
    carries donor state.

    ``datasource_caption`` is the label the rendered view shows for the target
    datasource, defaulting to its internal name. ``target_fields`` is the
    target's declared field metadata; supplying it enables the datatype
    compatibility check and restates each mapped dependency declaration from
    the target's own types. Both are optional so a caller holding only a
    datasource name can still render, exactly as before.
    """
    # The caption is copied into the rendered view, so it is held to the same
    # standard as the names: a workbook whose caption still carries a template
    # token would otherwise push that token into the output.
    supplied = [
        ("worksheet_name", worksheet_name),
        ("datasource_name", datasource_name),
    ]
    if datasource_caption is not None:
        supplied.append(("datasource_caption", datasource_caption))
    for label, value in supplied:
        if not value.strip():
            raise ResourceError(f"{label} must not be empty")
        if TEMPLATE_TOKEN_RE.search(value) or "{{" in value:
            raise ResourceError(
                f"{label} must not contain a template token: {value}"
            )

    plugin_root = Path(plugin_root)
    entry = _executable_entry(load_catalog(plugin_root), resource_id)
    data = _read_verified_bookmark(plugin_root, entry)

    donors = list(entry.get("datasources") or [])
    if len(donors) != 1:
        raise ResourceError(
            f"Resource {resource_id} must declare exactly one donor datasource, "
            f"found: {', '.join(donors) or 'none'}"
        )
    donor = donors[0]

    window, table, cards, _root, namespaces = _extract_fragments(data)

    window = _hoist_cards(window, cards)
    window = _remove_elements(window, "highlight")
    table = _remove_elements(table, "highlight")

    instances, columns = _declared_fields(table, donor)
    required = _donor_source_fields(window + table, donor, instances, columns)
    for field in entry.get("fields") or []:
        source = field["sourceField"]
        required.setdefault(source, set()).add(_bracket_reference(source))

    # Donor-only provenance metadata names a column without qualifying it, so
    # it is offered as an optional mapping and stripped when unmapped.
    metadata_fields = {
        logical_name: raw_forms
        for logical_name, raw_forms in _donor_metadata_fields(table, donor).items()
        if logical_name not in required
    }

    mappings = _validate_field_mappings(required, metadata_fields, field_mappings)
    validated_parameters = _validate_parameters(parameter_contracts(entry), parameters)

    table = _strip_unmapped_donor_metadata(table, donor, set(mappings))
    table = _remove_unused_donor_declarations(
        table, donor, set(required) | set(mappings)
    )

    if target_fields is not None:
        source_types = _donor_column_datatypes(table, donor)
        source_types.update(_catalog_source_datatypes(entry))
        _validate_mapping_types(source_types, target_fields, mappings)
        table = _retype_mapped_columns(table, donor, mappings, target_fields)

    discovered = {
        logical_name: set(raw_forms) for logical_name, raw_forms in required.items()
    }
    for logical_name, raw_forms in metadata_fields.items():
        discovered.setdefault(logical_name, set()).update(raw_forms)

    raw_to_logical: dict[str, str] = {}
    for logical, raw_forms in discovered.items():
        for raw in raw_forms:
            raw_to_logical[raw] = logical
    raw_to_target = {
        raw: _bracket_reference(mappings[logical])
        for raw, logical in raw_to_logical.items()
        if logical in mappings
    }

    # A datasource that declares no caption is labelled by its internal name,
    # so that is the label the output carries and the one exempt from the
    # donor-name scan below.
    caption = datasource_name if datasource_caption is None else datasource_caption

    rendered: dict[str, str] = {}
    for kind, fragment in (("worksheet", table), ("window", window)):
        fragment = _replace_datasource(fragment, donor, datasource_name, caption)
        fragment = _replace_fields(fragment, raw_to_target)
        fragment = _replace_parameters(fragment, validated_parameters)
        fragment = _replace_simple_ids(
            fragment, kind, _fragment_uuid(resource_id, worksheet_name, kind)
        )
        rendered[kind] = fragment

    rendered["worksheet"] = (
        f"<worksheet name='{escape_attribute(worksheet_name)}'>\n"
        f"{rendered['worksheet']}\n"
        "</worksheet>"
    )
    rendered["window"] = _set_window_identity(rendered["window"], worksheet_name)

    _reject_unsafe_output(
        rendered,
        donor=donor,
        target_datasource=datasource_name,
        raw_to_logical=raw_to_logical,
        field_mappings=mappings,
        target_caption=caption,
    )
    for kind, fragment in rendered.items():
        _parse_wrapped(fragment, namespaces, kind)
    return rendered["worksheet"], rendered["window"]


def _read_text(path: Path, label: str) -> str:
    """Read a UTF-8 file without translating its line endings.

    ``read_text`` would turn every CRLF into a bare LF, which a bounded splice
    would then write back as a whole-file rewrite.
    """
    try:
        return Path(path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ResourceError(f"Cannot read {label} {path}: {error}") from error


def _parse_workbook(twb_text: str) -> ET.Element:
    """Parse workbook text and confirm it has a ``<workbook>`` root."""
    try:
        root = ET.fromstring(twb_text)
    except ET.ParseError as error:
        raise ResourceError(f"Workbook is not well-formed XML: {error}") from error
    if root.tag != "workbook":
        raise ResourceError(
            f"Workbook root element must be <workbook>, found <{root.tag}>"
        )
    return root


def _metadata_record_fields(datasource: ET.Element) -> dict[str, FieldMetadata]:
    """Return field metadata from ``<metadata-record class='column'>`` entries.

    A record describes a physical column of the connection. Tableau surfaces a
    numeric one as a measure and everything else as a dimension, and that
    default is the only role a record can imply, so it is the only role
    reported here.

    Parsing is defensive and deterministic: a record of another class, one
    with no ``<local-name>``, one that names a field without Tableau's
    brackets, and a repeat of a name already seen are all skipped, so a
    partial or hand-edited connection block cannot redefine a field.
    """
    discovered: dict[str, FieldMetadata] = {}
    for record in datasource.iter("metadata-record"):
        if record.get("class") != METADATA_RECORD_COLUMN_CLASS:
            continue
        raw = (record.findtext("local-name") or "").strip()
        if len(raw) <= 2 or not (raw.startswith("[") and raw.endswith("]")):
            continue
        name = unescape_bracket(raw[1:-1])
        if name in discovered:
            continue
        datatype = (record.findtext("local-type") or "").strip() or None
        role = None
        if datatype is not None:
            role = (
                "measure"
                if _datatype_family(datatype) == NUMERIC_FAMILY
                else "dimension"
            )
        # A record carries no separate display type, so the physical type is
        # the most this layer can honestly say about both.
        discovered[name] = FieldMetadata(datatype, datatype, role)
    return discovered


def _column_fields(datasource: ET.Element) -> dict[str, FieldMetadata]:
    """Return field metadata from explicit ``<column>`` declarations."""
    discovered: dict[str, FieldMetadata] = {}
    for column in datasource.iter("column"):
        name = _bracketed_name(column, "name")
        if name is None or name in discovered:
            continue
        discovered[name] = FieldMetadata(
            column.get("datatype"),
            column.get("user-datatype"),
            column.get("role"),
        )
    return discovered


def inspect_datasource_metadata(twb_text: str) -> dict[str, DatasourceMetadata]:
    """Return each global datasource's caption and field metadata.

    Only datasources declared in the workbook's own ``<datasources>`` container
    are reported. A worksheet's per-view ``<datasources>`` block names the same
    datasource but carries only the columns that view happens to use, so
    including it would let a mapping validate against an incomplete field list.

    A field is discovered from either layer a real workbook may use: an
    explicit ``<column>`` declaration, or a ``<metadata-record class='column'>``
    entry under the connection. A physical column the author has never
    customized appears only as a metadata record, so reading just ``<column>``
    would report a workbook's own fields as missing. Where both layers
    describe one field the explicit declaration wins, because that is the
    logical definition Tableau itself reads.
    """
    root = _parse_workbook(twb_text)
    container = root.find("datasources")
    if container is None:
        raise ResourceError("Workbook has no <datasources> container")

    discovered: dict[str, DatasourceMetadata] = {}
    for datasource in container.findall("datasource"):
        name = datasource.get("name") or ""
        if not name.strip():
            raise ResourceError("Workbook declares a <datasource> without a name")
        if name in discovered:
            raise ResourceError(
                f"Workbook declares datasource {name} more than once"
            )
        fields = _metadata_record_fields(datasource)
        fields.update(_column_fields(datasource))
        discovered[name] = DatasourceMetadata(
            (datasource.get("caption") or "").strip() or name, fields
        )
    return discovered


def inspect_datasources(twb_text: str) -> dict[str, set[str]]:
    """Return each global datasource's internal name and its field names.

    A thin view over :func:`inspect_datasource_metadata` for callers that only
    need to know which fields exist.
    """
    return {
        name: set(metadata.fields)
        for name, metadata in inspect_datasource_metadata(twb_text).items()
    }


def _validate_target_fields(
    datasources: dict[str, DatasourceMetadata],
    datasource_name: str,
    field_mappings: dict[str, str],
) -> None:
    """Confirm the target datasource and every mapped target field exist."""
    if datasource_name not in datasources:
        available = ", ".join(sorted(datasources)) or "none"
        raise ResourceError(
            f"Workbook has no datasource named {datasource_name} "
            f"(available: {available})"
        )
    fields = datasources[datasource_name].fields
    missing = sorted(
        {target for target in field_mappings.values() if target not in fields}
    )
    if missing:
        available = ", ".join(sorted(fields)) or "none"
        raise ResourceError(
            f"Datasource {datasource_name} has no field named "
            f"{', '.join(missing)} (available: {available})"
        )


def _validate_mapping_types(
    source_types: dict[str, str],
    target_fields: dict[str, FieldMetadata],
    field_mappings: dict[str, str],
) -> None:
    """Reject a mapping whose target field cannot carry the source's data.

    Tableau's datatypes fall into families that behave the same way on a
    shelf. Within one family a template survives being repointed: an integer
    measure works unchanged against a real, and a date dimension works against
    a datetime, because the derivation, the shelf role, and the
    nominal/ordinal/quantitative pair all stay valid. Crossing a family
    boundary does not survive that way — a Sum of a string, or a date
    truncation of a boolean, is not a viz this module can honestly produce —
    so it fails here, before anything is rendered.

    A target field whose datatype cannot be determined is equally fatal:
    rendering it would have to fall back to the donor's datatype, which is the
    defect this check exists to prevent.
    """
    problems: list[str] = []
    for source in sorted(field_mappings):
        source_datatype = source_types.get(source)
        source_family = _datatype_family(source_datatype)
        if source_family is None:
            # No recorded contract for this field, so there is nothing to
            # compare the target against and nothing to assert.
            continue
        target = field_mappings[source]
        metadata = target_fields.get(target)
        target_datatype = metadata.datatype if metadata is not None else None
        target_family = _datatype_family(target_datatype)
        if target_family is None:
            problems.append(
                f"{source} -> {target} (target field declares no datatype; "
                f"{source} is {source_datatype})"
            )
        elif target_family != source_family:
            problems.append(
                f"{source} -> {target} ({source_datatype} is {source_family}, "
                f"{target_datatype} is {target_family})"
            )
    if problems:
        raise ResourceError(f"Incompatible field mappings: {'; '.join(problems)}")


def _fragment_name(fragment: str, tag: str) -> str:
    """Return the ``name`` attribute of a rendered fragment's root element."""
    data = fragment.encode("utf-8")
    opening = f"<{tag}".encode("utf-8")
    if not data.startswith(opening) or data[len(opening) : len(opening) + 1] not in (
        b" ",
        b"\t",
        b"\n",
        b"\r",
        b">",
        b"/",
    ):
        raise ResourceError(f"Rendered fragment is not a <{tag}> element")
    name = _unescape(_tag_attributes(data, 0).get("name") or "")
    if not name:
        raise ResourceError(f"Rendered <{tag}> fragment has no name attribute")
    return name


def _closing_tag_offset(data: bytes, tag: str) -> int:
    """Return the byte offset of the workbook's single ``</tag>``."""
    closing = f"</{tag}>".encode("utf-8")
    count = data.count(closing)
    if count != 1:
        detail = (
            f"an empty <{tag} /> container cannot receive a fragment"
            if count == 0 and re.search(rf"<{tag}(\s[^<>]*)?/>", data.decode("utf-8"))
            else f"found {count}"
        )
        raise ResourceError(
            f"Workbook must contain exactly one closing </{tag}> tag ({detail})"
        )
    return data.index(closing)


def _expand_empty_container(text: str, tag: str) -> str:
    """Rewrite a self-closing ``<tag />`` container into an open/close pair.

    Applied only to the bundled starter, whose containers are empty by design.
    A caller's workbook is never restructured this way: it must already carry
    the container it is being asked to extend.
    """
    if f"</{tag}>" in text:
        return text
    pattern = re.compile(
        rf"^([ \t]*)<{tag}((?:\s[^<>]*?)?)\s*/>[ \t]*$", re.MULTILINE
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ResourceError(
            f"Starter workbook must contain exactly one <{tag}> container, "
            f"found {len(matches)}"
        )
    match = matches[0]
    indent = match.group(1)
    replacement = f"{indent}<{tag}{match.group(2).rstrip()}>\n{indent}</{tag}>"
    return text[: match.start()] + replacement + text[match.end() :]


def _insert_before(data: bytes, offset: int, fragment: str) -> bytes:
    """Splice ``fragment`` into ``data`` immediately before ``offset``.

    Every byte before ``offset`` and every byte from ``offset`` onward is
    carried over untouched; only the closing tag's own indentation is repeated
    after the fragment so the result stays readable.
    """
    line_start = data.rfind(b"\n", 0, offset) + 1
    indent = data[line_start:offset]
    # The closing tag shares its line with other markup, so start a new line
    # for the fragment instead of copying that markup as indentation.
    lead, indent = (b"", indent) if not indent.strip() else (b"\n", b"")
    return (
        data[:offset]
        + lead
        + fragment.encode("utf-8")
        + b"\n"
        + indent
        + data[offset:]
    )


def inject_fragments(twb_text: str, worksheet: str, window: str) -> str:
    """Insert one rendered worksheet/window pair into workbook text.

    Both fragments are placed immediately before the workbook's single
    ``</worksheets>`` and ``</windows>`` closing tags. The workbook is parsed
    to reject a duplicate worksheet or window name and to confirm the result is
    well-formed, but it is never reserialized.
    """
    worksheet_name = _fragment_name(worksheet, "worksheet")
    window_name = _fragment_name(window, "window")

    root = _parse_workbook(twb_text)
    for tag in ("worksheets", "windows"):
        if root.find(tag) is None:
            raise ResourceError(f"Workbook has no <{tag}> container")
    if worksheet_name in {
        item.get("name") for item in root.findall("worksheets/worksheet")
    }:
        raise ResourceError(
            f"Workbook already contains a worksheet named {worksheet_name}; "
            "choose a different --worksheet-name"
        )
    if window_name in {item.get("name") for item in root.findall("windows/window")}:
        raise ResourceError(
            f"Workbook already contains a window named {window_name}; "
            "choose a different --worksheet-name"
        )

    data = twb_text.encode("utf-8")
    insertions = sorted(
        (
            (_closing_tag_offset(data, "worksheets"), worksheet),
            (_closing_tag_offset(data, "windows"), window),
        ),
        key=lambda insertion: insertion[0],
        reverse=True,
    )
    for offset, fragment in insertions:
        data = _insert_before(data, offset, fragment)

    output = data.decode("utf-8")
    written = _parse_workbook(output)
    placed_worksheets = [
        item.get("name") for item in written.findall("worksheets/worksheet")
    ]
    placed_windows = [item.get("name") for item in written.findall("windows/window")]
    if (
        placed_worksheets.count(worksheet_name) != 1
        or placed_windows.count(window_name) != 1
    ):
        raise ResourceError(
            "Injected fragments did not land exactly once in the workbook's "
            "<worksheets> and <windows> containers"
        )
    return output


def _bracketed_name(element: ET.Element, attribute: str) -> str | None:
    """Return a bracketed identifier attribute's decoded name, if it has one."""
    raw = element.get(attribute) or ""
    if len(raw) > 2 and raw.startswith("[") and raw.endswith("]"):
        return unescape_bracket(raw[1:-1])
    return None


def _defined_fields(element: ET.Element) -> set[str]:
    """Return every field name defined beneath ``element``.

    Relation metadata inside a connection names a table's physical columns
    without brackets, so requiring brackets keeps physical column names out of
    the datasource's field vocabulary.
    """
    return {
        name
        for tag in FIELD_DEFINITION_TAGS
        for child in element.iter(tag)
        if (name := _bracketed_name(child, "name")) is not None
    }


def _field_definitions(root: ET.Element) -> dict[str, set[str]]:
    """Map each globally declared datasource to the fields it defines.

    Only the workbook's own ``<datasources>`` container declares a datasource.
    A worksheet's ``<datasource-dependencies>`` block names an already-declared
    datasource and carries just the columns and column instances that view
    uses, so it extends a declared field set and never creates one.
    """
    definitions: dict[str, set[str]] = {}
    for datasource in root.findall("datasources/datasource"):
        name = datasource.get("name") or ""
        definitions.setdefault(name, set()).update(_defined_fields(datasource))
    for dependencies in root.iter("datasource-dependencies"):
        fields = definitions.get(dependencies.get("datasource") or "")
        if fields is not None:
            fields.update(_defined_fields(dependencies))
    return definitions


def _field_references(root: ET.Element) -> list[tuple[str, str]]:
    """Return every ``[datasource].[field]`` pair a view element carries.

    Geographic metadata is skipped: a semantic role and a semantic-value key
    are qualified names in Tableau's geocoding hierarchy, not references into
    a datasource. A field definition's own attributes are skipped for the same
    reason — they describe that field rather than pointing at another one —
    while element text and everything nested inside a definition is still
    scanned. Names arrive already entity-decoded from the parser, so only
    Tableau's bracket escaping is undone.
    """
    references: list[tuple[str, str]] = []

    def collect(text: str) -> None:
        references.extend(
            (unescape_bracket(datasource), unescape_bracket(field))
            for datasource, field in QUALIFIED_REF_RE.findall(text)
        )

    for container in FIELD_REFERENCE_CONTAINERS:
        for parent in root.findall(container):
            for element in parent.iter():
                if element.tag not in NON_REFERENCE_TAGS:
                    for name, value in element.attrib.items():
                        if name not in NON_REFERENCE_ATTRIBUTES:
                            collect(value)
                for text in (element.text, element.tail):
                    if text:
                        collect(text)
    return references


def _unresolved_field(defined: set[str], field: str) -> str | None:
    """Return the name ``field`` fails to resolve to, or ``None``.

    A column instance that the workbook does not declare still resolves when
    its ``derivation:field:role`` base field is defined, so an undeclared
    instance of a real field is reported against that base field.
    """
    if _is_exempt_field(field) or field in defined:
        return None
    derived = DERIVED_SEGMENT_RE.match(field)
    if derived is None:
        return field
    base = derived.group(2)
    return None if base in defined or _is_exempt_field(base) else base


def _repeated(names: list[str]) -> list[str]:
    """Return each name that appears more than once, sorted and deduplicated."""
    return sorted({name for name in names if names.count(name) > 1})


def validate_workbook_text(text: str) -> list[str]:
    """Return workbook text's structural errors, ordered and deduplicated.

    An empty list means the workbook is structurally sound: it has the three
    required containers, carries no unresolved template token or unresolved
    ``federated.`` placeholder, names each worksheet and its window once and
    consistently, and references only datasources and fields the workbook
    itself defines. Errors are reported in a fixed rule order so a caller can
    compare two runs, and a malformed or non-workbook document reports only
    that, because every later rule would be guessing at its structure.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ["malformed-xml"]
    if root.tag != "workbook":
        return ["not-tableau-workbook"]

    errors: list[str] = [
        f"missing-{tag}-container"
        for tag in REQUIRED_CONTAINERS
        if root.find(tag) is None
    ]

    if TEMPLATE_TOKEN_RE.search(text):
        errors.append("unresolved-template-token")

    definitions = _field_definitions(root)
    # A real connection is named "federated.<hash>", so a federated token is
    # legitimate only when it names one of this workbook's own datasources.
    if any(
        _unescape(match.group(0)) not in definitions
        for match in FEDERATED_RE.finditer(text)
    ):
        errors.append("unresolved-federated-placeholder")

    worksheet_names = [
        item.get("name") or "" for item in root.findall("worksheets/worksheet")
    ]
    windows = root.findall("windows/window")
    errors.extend(
        f"duplicate-worksheet-name: {name}" for name in _repeated(worksheet_names)
    )
    errors.extend(
        f"duplicate-window-name: {name}"
        for name in _repeated([item.get("name") or "" for item in windows])
    )
    # Dashboard and story windows have no worksheet of their own, so only
    # worksheet-class windows are paired.
    worksheet_windows = {
        item.get("name") or "" for item in windows if item.get("class") == "worksheet"
    }
    errors.extend(
        f"worksheet-window-name-mismatch: {name}"
        for name in sorted(set(worksheet_names) ^ worksheet_windows)
    )

    unknown_datasources: set[str] = set()
    unknown_fields: set[str] = set()
    for datasource, field in _field_references(root):
        if datasource not in definitions:
            unknown_datasources.add(datasource)
            continue
        unresolved = _unresolved_field(definitions[datasource], field)
        if unresolved is not None:
            unknown_fields.add(f"{datasource}.{unresolved}")
    errors.extend(
        f"unknown-datasource-reference: {name}"
        for name in sorted(unknown_datasources)
    )
    errors.extend(
        f"unknown-field-reference: {name}" for name in sorted(unknown_fields)
    )

    return list(dict.fromkeys(errors))


def validate_workbook(path: Path) -> list[str]:
    """Return the structural errors of the workbook stored at ``path``."""
    return validate_workbook_text(_read_text(Path(path), "workbook"))


def _read_datasource_definition(path: Path) -> tuple[str, str]:
    """Return one ``<datasource>`` element's text and its internal name."""
    path = Path(path)
    text = _read_text(path, "datasource definition")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ResourceError(
            f"Datasource definition {path} is not well-formed XML: {error}"
        ) from error
    if root.tag != "datasource":
        raise ResourceError(
            f"Datasource definition must be exactly one <datasource> element, "
            f"found <{root.tag}>"
        )
    if root.findall(".//datasource"):
        raise ResourceError(
            "Datasource definition must contain exactly one <datasource> element, "
            "found nested datasources"
        )
    name = root.get("name") or ""
    if not name.strip():
        raise ResourceError(
            "Datasource definition must declare a nonempty name attribute"
        )

    data = text.encode("utf-8")
    spans = [
        (start, end)
        for tag, depth, start, end in _scan_elements(data)
        if depth == 0 and tag == "datasource"
    ]
    if len(spans) != 1:
        raise ResourceError(
            "Datasource definition must contain exactly one <datasource> element"
        )
    start, end = spans[0]
    return data[start:end].decode("utf-8"), name


def _reject_introduced_errors(baseline_text: str, output: str) -> None:
    """Block validation errors this run introduced, ignoring inherited ones.

    Validation is a delta against a baseline, not an absolute gate: a workbook
    that already fails a rule — a hidden sheet with no window, a reference
    this module cannot resolve — is the caller's to fix, and refusing to
    extend it would make this CLI unusable against real workbooks it did not
    create. What this run must never do is make the workbook worse, so any
    error the output has and the baseline did not is fatal.

    The baseline is only the document this run inherited unchanged. Anything
    this run puts into the output — the rendered sheet, and for ``instantiate``
    the caller's inserted ``<datasource>`` definition — is generated content
    and is held to the full rules, so a definition carrying an unresolved
    token cannot license that token in the result. Inherited errors are
    reported alongside the fatal ones so a reader can tell which came from
    where.
    """
    baseline = validate_workbook_text(baseline_text)
    inherited = set(baseline)
    introduced = [
        error for error in validate_workbook_text(output) if error not in inherited
    ]
    if not introduced:
        return
    detail = f"Generated workbook failed validation: {', '.join(introduced)}"
    if baseline:
        detail += (
            " (pre-existing errors carried in from the input workbook: "
            f"{', '.join(baseline)})"
        )
    raise ResourceError(detail)


def _apply_resource(
    twb_text: str,
    *,
    plugin_root: Path,
    resource_id: str,
    worksheet_name: str,
    datasource_name: str,
    field_mappings: dict[str, str] | None,
    parameters: dict[str, str] | None,
    baseline_text: str | None = None,
) -> str:
    """Validate mappings against the workbook, render, inject, and verify.

    The transformed workbook is returned only after it introduces no new
    validation error, so a caller never writes a workbook this run made worse.

    ``baseline_text`` is the document whose existing errors are inherited. It
    defaults to ``twb_text``, which is correct when the caller supplied that
    whole workbook. A caller that assembled ``twb_text`` itself must pass the
    part it did not generate, so the part it did generate is still checked.
    """
    mappings = dict(field_mappings or {})
    datasources = inspect_datasource_metadata(twb_text)
    _validate_target_fields(datasources, datasource_name, mappings)
    target = datasources[datasource_name]
    worksheet, window = render_bookmark(
        plugin_root,
        resource_id,
        worksheet_name,
        datasource_name,
        mappings,
        dict(parameters or {}),
        datasource_caption=target.caption,
        target_fields=target.fields,
    )
    output = inject_fragments(twb_text, worksheet, window)
    _reject_introduced_errors(
        twb_text if baseline_text is None else baseline_text, output
    )
    return output


def _default_file_mode() -> int:
    current = os.umask(0)
    os.umask(current)
    return 0o666 & ~current


def atomic_write(path: Path, content: str, overwrite: bool = False) -> None:
    """Write ``content`` to ``path`` through a same-directory temporary file.

    The destination is only ever replaced by a fully written, fsynced file, so
    an interrupted run cannot leave a partial workbook behind.
    """
    path = Path(path)
    if path.exists() and not overwrite:
        raise ResourceError(
            f"Refusing to replace existing file {path}; pass --overwrite to allow it"
        )
    directory = path.parent
    if not directory.is_dir():
        raise ResourceError(f"Output directory does not exist: {directory}")

    # A temporary file is created 0600, so replacing an existing workbook would
    # otherwise silently narrow its permissions.
    mode = path.stat().st_mode & 0o7777 if path.exists() else _default_file_mode()

    try:
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=directory,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        )
    except OSError as error:
        raise ResourceError(f"Cannot write {path}: {error}") from error

    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ResourceError(f"Cannot write {path}: {error}") from error
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _check_output_path(
    source_path: Path, output_path: Path, overwrite: bool, label: str
) -> None:
    if source_path.resolve() == output_path.resolve() and not overwrite:
        raise ResourceError(
            f"Output path {output_path} is the {label}; pass --overwrite to "
            "replace it or choose a different --output"
        )


def inject_resource(
    *,
    input_path: Path,
    output_path: Path,
    resource_id: str,
    worksheet_name: str,
    datasource_name: str,
    field_mappings: dict[str, str] | None = None,
    parameters: dict[str, str] | None = None,
    plugin_root: Path = PLUGIN_ROOT,
    overwrite: bool = False,
) -> str:
    """Add one executable resource to an existing workbook.

    Returns the complete transformed workbook text, which is also written to
    ``output_path``. The input file is only read, never modified, unless the
    caller points ``output_path`` at it with ``overwrite``.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    _check_output_path(input_path, output_path, overwrite, "input workbook")
    twb_text = _read_text(input_path, "workbook")

    output = _apply_resource(
        twb_text,
        plugin_root=plugin_root,
        resource_id=resource_id,
        worksheet_name=worksheet_name,
        datasource_name=datasource_name,
        field_mappings=field_mappings,
        parameters=parameters,
    )
    atomic_write(output_path, output, overwrite=overwrite)
    return output


def instantiate_resource(
    *,
    datasource_definition_path: Path,
    output_path: Path,
    resource_id: str,
    worksheet_name: str,
    field_mappings: dict[str, str] | None = None,
    parameters: dict[str, str] | None = None,
    plugin_root: Path = PLUGIN_ROOT,
    overwrite: bool = False,
) -> str:
    """Create a workbook from the starter, one datasource, and one resource.

    The caller supplies the complete ``<datasource>`` definition; connection
    metadata is never fabricated. Returns the complete workbook text, which is
    also written to ``output_path``.

    Every part of the result other than the bundled starter is produced by
    this call, so the starter alone is the validation baseline and a supplied
    definition carrying an unresolved token or a stray federated placeholder
    fails the run instead of being inherited.
    """
    plugin_root = Path(plugin_root)
    output_path = Path(output_path)
    _check_output_path(
        Path(datasource_definition_path),
        output_path,
        overwrite,
        "datasource definition",
    )
    definition, datasource_name = _read_datasource_definition(
        datasource_definition_path
    )

    starter_path = plugin_root / "resources" / STARTER_RELATIVE_PATH
    starter_text = _read_text(starter_path, "starter workbook")

    twb_text = starter_text
    for tag in ("datasources", "worksheets", "windows"):
        twb_text = _expand_empty_container(twb_text, tag)
    data = twb_text.encode("utf-8")
    twb_text = _insert_before(
        data, _closing_tag_offset(data, "datasources"), definition
    ).decode("utf-8")

    output = _apply_resource(
        twb_text,
        plugin_root=plugin_root,
        resource_id=resource_id,
        worksheet_name=worksheet_name,
        datasource_name=datasource_name,
        field_mappings=field_mappings,
        parameters=parameters,
        baseline_text=starter_text,
    )
    atomic_write(output_path, output, overwrite=overwrite)
    return output


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def _format_list_text(entries: list[dict[str, object]]) -> str:
    if not entries:
        return "No resources found."
    lines = []
    for entry in entries:
        family = entry.get("family") or "-"
        lines.append(
            f"{entry['id']} [{entry['type']}/{entry['tier']}] "
            f"family={family} — {entry.get('intent') or ''}"
        )
    return "\n".join(lines)


def _format_inspect_text(entry: dict[str, object]) -> str:
    lines = [
        f"id: {entry['id']}",
        f"type: {entry['type']}",
        f"tier: {entry['tier']}",
        f"family: {entry.get('family') or '-'}",
        f"intent: {entry.get('intent') or '-'}",
        f"path: {entry['path']}",
    ]
    datasources = entry.get("datasources") or []
    lines.append(f"datasources: {', '.join(datasources) if datasources else '-'}")
    parameters = entry.get("parameters") or []
    if parameters:
        lines.append("parameters:")
        for parameter in parameters:
            required = parameter.get("required", True)
            details = [
                str(parameter.get("type") or "untyped"),
                "required" if required else "optional",
            ]
            allowed = parameter.get("allowed") or []
            if allowed:
                details.append(f"allowed: {', '.join(allowed)}")
            lines.append(f"  - {parameter.get('name')} ({', '.join(details)})")
    else:
        lines.append("parameters: -")
    fields = entry.get("fields") or []
    if fields:
        lines.append("fields:")
        for field in fields:
            lines.append(
                f"  - {field['sourceField']} ({field['shelf']}, "
                f"{field['role']}, {field['derivation']}, {field['datatype']})"
            )
        lines.append(
            "  each field must map to a target field of the same datatype "
            "family (integer/real, date/datetime, string, boolean, spatial)"
        )
    else:
        lines.append("fields: -")
    reasons = entry.get("classificationReasons") or []
    if reasons:
        lines.append(f"classificationReasons: {', '.join(reasons)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover and inspect Tableau plugin resources.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list", help="List catalog resources, optionally filtered."
    )
    list_parser.add_argument("--query", help="Free-text search over id/intent/family/keywords.")
    list_parser.add_argument("--family", help="Exact-match resource family filter.")
    list_parser.add_argument("--type", dest="resource_type", help="Exact-match resource type filter.")
    list_parser.add_argument("--tier", help="Exact-match resource tier filter.")
    list_parser.add_argument(
        "--format", choices=("json", "text"), default="json", help="Output format."
    )

    inspect_parser = subparsers.add_parser(
        "inspect", help="Show the full catalog entry for one resource id."
    )
    inspect_parser.add_argument("resource_id", help="Resource id to inspect.")
    inspect_parser.add_argument(
        "--format", choices=("json", "text"), default="json", help="Output format."
    )

    instantiate_parser = subparsers.add_parser(
        "instantiate",
        help="Create a workbook from the starter, one datasource, and one resource.",
    )
    instantiate_parser.add_argument("resource_id", help="Executable resource id.")
    instantiate_parser.add_argument(
        "--datasource-definition",
        required=True,
        help="Path to a file holding exactly one <datasource> element.",
    )
    _add_transform_arguments(instantiate_parser)

    inject_parser = subparsers.add_parser(
        "inject", help="Add one executable resource to an existing workbook."
    )
    inject_parser.add_argument("resource_id", help="Executable resource id.")
    inject_parser.add_argument(
        "--input", required=True, help="Path to the existing .twb workbook."
    )
    inject_parser.add_argument(
        "--datasource",
        required=True,
        help="Internal name of the target datasource in the input workbook.",
    )
    _add_transform_arguments(inject_parser)

    validate_parser = subparsers.add_parser(
        "validate", help="Report a workbook's structural errors."
    )
    validate_parser.add_argument(
        "--input", required=True, help="Path to the .twb workbook to check."
    )

    return parser


def _add_transform_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", required=True, help="Path to the output .twb.")
    parser.add_argument(
        "--worksheet-name", required=True, help="Name for the generated worksheet."
    )
    parser.add_argument(
        "--map",
        dest="maps",
        action="append",
        default=[],
        metavar="SOURCE=TARGET",
        help="Map one template source field to a target datasource field.",
    )
    parser.add_argument(
        "--param",
        dest="params",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Supply one template parameter value.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing output file.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    plugin_root = PLUGIN_ROOT

    if args.command == "list":
        results = search_resources(
            load_catalog(plugin_root),
            query=args.query,
            family=args.family,
            resource_type=args.resource_type,
            tier=args.tier,
        )
        if args.format == "text":
            print(_format_list_text(results))
        else:
            _print_json(results)
        return 0

    if args.command == "inspect":
        try:
            entry = find_resource(load_catalog(plugin_root), args.resource_id)
        except KeyError:
            print(f"Unknown resource: {args.resource_id}", file=sys.stderr)
            return 2
        if args.format == "text":
            print(_format_inspect_text(entry))
        else:
            _print_json(entry)
        return 0

    if args.command == "validate":
        try:
            errors = validate_workbook(Path(args.input))
        except ResourceError as error:
            print(str(error), file=sys.stderr)
            return 2
        # stdout is always the JSON error list, so a caller can read the same
        # shape whether or not the workbook passed.
        _print_json(errors)
        return 1 if errors else 0

    if args.command in ("instantiate", "inject"):
        try:
            field_mappings = parse_assignments(args.maps)
            parameters = parse_assignments(args.params)
            if args.command == "inject":
                inject_resource(
                    input_path=Path(args.input),
                    output_path=Path(args.output),
                    resource_id=args.resource_id,
                    worksheet_name=args.worksheet_name,
                    datasource_name=args.datasource,
                    field_mappings=field_mappings,
                    parameters=parameters,
                    plugin_root=plugin_root,
                    overwrite=args.overwrite,
                )
            else:
                instantiate_resource(
                    datasource_definition_path=Path(args.datasource_definition),
                    output_path=Path(args.output),
                    resource_id=args.resource_id,
                    worksheet_name=args.worksheet_name,
                    field_mappings=field_mappings,
                    parameters=parameters,
                    plugin_root=plugin_root,
                    overwrite=args.overwrite,
                )
        except ResourceError as error:
            print(str(error), file=sys.stderr)
            return 2
        print(f"Wrote {args.output}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

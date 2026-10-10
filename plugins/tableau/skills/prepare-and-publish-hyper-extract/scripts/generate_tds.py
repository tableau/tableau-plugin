#!/usr/bin/env python3
"""
Generate a published-ready .tdsx (multi-table relationships, captions,
descriptions, roles) from a .hyper plus a model JSON. No Tableau Desktop.

A script, not freehand XML, because the .tds spans coordinated parts that must
agree exactly: the `<cols>` map, metadata records, `<column>` captions, and the
object graph all key off the same local names and object ids. Desktop's rules
are reproduced here: when a column name repeats across tables, the first table
in the model keeps the bare name and later ones become `name (table)`.

Usage:
  python3 generate_tds.py HYPER MODEL.json --out OUT.tdsx [--fields-out FIELDS.json]

model.json (see references/model-json.md):
  {
    "caption": "Orders",                       // data source caption
    "tables": [
      {"schema": "public", "name": "fact_orders", "caption": "Orders",
       "columns": {"order_id": {"caption": "Order ID", "description": "...",
                                "role": "dimension", "semanticRole": "[Country].[ISO3166_2]",
                                "hidden": false}}}
    ],
    "relationships": [
      {"from": {"table": "fact_orders", "column": "customer_id"},
       "to":   {"table": "dim_customer", "column": "customer_id"}}
    ]
  }

Every Hyper column is emitted; ones missing from the model get a cleaned-up
caption ("signup_ts" -> "Signup Ts") and a role from their type (numbers are
measures, except key-named columns like id / customer_id / customerId).

--fields-out writes the field list the data-app wiring descriptor needs
(`name` = published caption, `datatype`, `role`), so the next step doesn't have
to wait for Tableau Catalog to index the new data source.

Hard-fails (✗ on stderr, exit 1) on: model tables/columns not in the hyper,
duplicate field captions, relationship keys of different types, tables not
joined into one tree, or Hyper types Tableau can't read.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

# Hyper TypeTag name -> (remote-type, local-type, default aggregation)
TYPES = {
    "TEXT": (129, "string", "Count"),
    "VARCHAR": (129, "string", "Count"),
    "CHAR": (129, "string", "Count"),
    "BOOL": (11, "boolean", "Count"),
    "DATE": (133, "date", "Year"),
    "TIMESTAMP": (135, "datetime", "Year"),
    "TIMESTAMP_TZ": (135, "datetime", "Year"),
    "SMALL_INT": (2, "integer", "Sum"),
    "INT": (3, "integer", "Sum"),
    "BIG_INT": (20, "integer", "Sum"),
    "DOUBLE": (5, "real", "Sum"),
    "NUMERIC": (131, "real", "Sum"),
}
ROLES = ("dimension", "measure")
APOS = {"'": "&apos;"}

Schema = dict[tuple[str, str], list[tuple[str, str]]]  # (schema, table) -> [(column, type name)]


class ModelError(Exception):
    pass


def default_caption(column: str) -> str:
    """snake_case / camelCase -> Title Case, keeping short all-caps tokens (ID, URL)."""
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", column).replace("_", " ").split()
    return " ".join(w.upper() if w.lower() in ("id", "url", "luid") else w[:1].upper() + w[1:]
                    for w in words) or column


def is_key_name(column: str) -> bool:
    """id, customer_id, customerId: keys are dimensions even when they're integers."""
    return re.search(r"(^|_)id$|[a-z]Id$", column) is not None or column.lower() == "id"


def read_schema(hyper: Path) -> Schema:
    from tableauhyperapi import Connection, HyperProcess, Telemetry

    out: Schema = {}
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters={"log_config": ""}) as hp, \
         Connection(hp.endpoint, str(hyper)) as conn:
        for schema in conn.catalog.get_schema_names():
            for table in conn.catalog.get_table_names(schema):
                cols = conn.catalog.get_table_definition(table).columns
                out[(schema.name.unescaped, table.name.unescaped)] = [
                    (c.name.unescaped, c.type.tag.name) for c in cols]
    return out


def object_id(schema: str, table: str) -> str:
    guid = uuid.uuid5(uuid.NAMESPACE_URL, f"{schema}.{table}").hex.upper()
    return f"{table} ({schema}.{table})_{guid}"


def connection_name(caption: str) -> str:
    return "hyper." + uuid.uuid5(uuid.NAMESPACE_URL, caption).hex[:28]


def resolve(schema: Schema, model: dict) -> dict:
    """Validate the model against the hyper; return everything the XML needs."""
    tables = model.get("tables") or []
    if not tables:
        raise ModelError("model has no tables")
    by_name = {}
    for t in tables:
        key = (t.get("schema", "public"), t["name"])
        if key not in schema:
            have = ", ".join(f"{s}.{n}" for s, n in schema)
            raise ModelError(f"table {key[0]}.{key[1]} is not in the hyper (have: {have})")
        if t["name"] in by_name:
            raise ModelError(f"table name {t['name']!r} is listed twice")
        by_name[t["name"]] = {**t, "schema": key[0], "hyper_columns": schema[key]}

    # Local names: first table listed keeps the bare column name (Desktop's rule).
    local: dict[tuple[str, str], str] = {}
    taken: set[str] = set()
    for t in by_name.values():
        for col, _ in t["hyper_columns"]:
            name = col if col not in taken else f"{col} ({t['name']})"
            taken.add(name)
            local[(t["name"], col)] = name

    fields = []
    for t in by_name.values():
        meta = t.get("columns") or {}
        hyper_cols = dict(t["hyper_columns"])
        unknown = sorted(set(meta) - set(hyper_cols))
        if unknown:
            raise ModelError(f"{t['name']}: model columns not in the hyper: {', '.join(unknown)}")
        for col, type_name in t["hyper_columns"]:
            if type_name not in TYPES:
                raise ModelError(f"{t['name']}.{col}: Hyper type {type_name} isn't supported; "
                                 "cast it to text, a number, or a date/timestamp when building the hyper")
            remote_type, local_type, agg = TYPES[type_name]
            m = meta.get(col) or {}
            ln = local[(t["name"], col)]
            caption = m.get("caption") or (default_caption(col) if ln == col
                                           else f"{default_caption(col)} ({t.get('caption', t['name'])})")
            role = m.get("role") or ("measure" if local_type in ("integer", "real")
                                     and not is_key_name(col) else "dimension")
            if role not in ROLES:
                raise ModelError(f"{t['name']}.{col}: role must be dimension or measure, got {role!r}")
            fields.append({
                "table": t["name"], "column": col, "local": ln, "caption": caption,
                "remote_type": remote_type, "datatype": local_type, "aggregation": agg,
                "role": role, "description": m.get("description"),
                "semantic_role": m.get("semanticRole"), "hidden": bool(m.get("hidden")),
            })

    seen: dict[str, str] = {}
    for f in fields:
        prior = seen.setdefault(f["caption"].lower(), f"{f['table']}.{f['column']}")
        if prior != f"{f['table']}.{f['column']}":
            raise ModelError(f"caption {f['caption']!r} is used by both {prior} and "
                             f"{f['table']}.{f['column']}; give one a distinct caption")

    by_key = {(f["table"], f["column"]): f for f in fields}
    rels = []
    for r in model.get("relationships") or []:
        ends = []
        for side in ("from", "to"):
            end = r.get(side) or {}
            if isinstance(end.get("column"), list):
                raise ModelError("composite relationship keys aren't supported; build a single "
                                 "key column in the hyper (e.g. md5(a || '::' || b)) and relate on that")
            if (end.get("table"), end.get("column")) not in by_key:
                raise ModelError(f"relationship {side} {end.get('table')}.{end.get('column')} "
                                 "is not a column in the model's tables")
            ends.append(by_key[(end["table"], end["column"])])
        if ends[0]["datatype"] != ends[1]["datatype"]:
            raise ModelError(f"relationship {ends[0]['table']}.{ends[0]['column']} ({ends[0]['datatype']}) "
                             f"= {ends[1]['table']}.{ends[1]['column']} ({ends[1]['datatype']}): "
                             "key types differ; cast one when building the hyper")
        rels.append(ends)

    # Tableau's object graph is a tree: n tables need n-1 relationships, all connected.
    names = list(by_name)
    if len(rels) != len(names) - 1:
        raise ModelError(f"{len(names)} tables need exactly {len(names) - 1} relationship(s) "
                         f"to form one connected model; the model has {len(rels)}")
    parent = {n: n for n in names}

    def root(n: str) -> str:
        while parent[n] != n:
            n = parent[n]
        return n

    for a, b in rels:
        ra, rb = root(a["table"]), root(b["table"])
        if ra == rb:
            raise ModelError(f"relationship {a['table']} → {b['table']} creates a loop; "
                             "each pair of tables may be related only once, as a tree")
        parent[ra] = rb

    return {"tables": list(by_name.values()), "fields": fields, "relationships": rels}


def build_tds(schema: Schema, model: dict, hyper_member: str) -> tuple[str, list[dict]]:
    r = resolve(schema, model)
    caption = model.get("caption") or "Extract"
    conn = connection_name(caption)

    def relation(t: dict) -> str:
        return (f"<relation connection='{conn}' name={quoteattr(t['name'])} "
                f"table={quoteattr('[%s].[%s]' % (t['schema'], t['name']))} type='table' />")

    oid = {t["name"]: object_id(t["schema"], t["name"]) for t in r["tables"]}
    cols_map, records, columns, objects = [], [], [], []
    for t in r["tables"]:
        table_caption = t.get("caption") or default_caption(t["name"])
        objects.append(
            f"      <object caption={quoteattr(table_caption)} id={quoteattr(oid[t['name']])}>\n"
            f"        <properties context=''>\n          {relation(t)}\n        </properties>\n"
            "      </object>")
        columns.append(
            f"  <column caption={quoteattr(table_caption)} datatype='table' "
            f"name={quoteattr('[__tableau_internal_object_id__].[%s]' % oid[t['name']])} "
            "role='measure' type='quantitative' />")

    for ordinal, f in enumerate(r["fields"]):
        tname, ln = f["table"], f["local"]
        cols_map.append(f"      <map key={quoteattr(f'[{ln}]')} "
                        f"value={quoteattr('[%s].[%s]' % (tname, f['column']))} />")
        records.append(
            "      <metadata-record class='column'>\n"
            f"        <remote-name>{escape(f['column'])}</remote-name>\n"
            f"        <remote-type>{f['remote_type']}</remote-type>\n"
            f"        <local-name>{escape(f'[{ln}]')}</local-name>\n"
            f"        <parent-name>{escape(f'[{tname}]')}</parent-name>\n"
            f"        <remote-alias>{escape(f['column'])}</remote-alias>\n"
            f"        <ordinal>{ordinal}</ordinal>\n"
            f"        <local-type>{f['datatype']}</local-type>\n"
            f"        <aggregation>{f['aggregation']}</aggregation>\n"
            "        <contains-null>true</contains-null>\n"
            + ("        <collation flag='0' name='binary' />\n" if f["datatype"] == "string" else "")
            + f"        <object-id>{escape(f'[{oid[tname]}]')}</object-id>\n"
            "      </metadata-record>")
        kind = ("quantitative" if f["role"] == "measure"
                else "ordinal" if f["datatype"] in ("date", "datetime") else "nominal")
        attrs = (f"caption={quoteattr(f['caption'])} datatype='{f['datatype']}'"
                 + (" hidden='true'" if f["hidden"] else "")
                 + f" name={quoteattr(f'[{ln}]')} role='{f['role']}'"
                 + (f" semantic-role={quoteattr(f['semantic_role'])}" if f["semantic_role"] else "")
                 + f" type='{kind}'")
        if f["description"]:
            columns.append(
                f"  <column {attrs}>\n    <desc>\n      <formatted-text>\n"
                f"        <run>{escape(f['description'], APOS)}</run>\n"
                "      </formatted-text>\n    </desc>\n  </column>")
        else:
            columns.append(f"  <column {attrs} />")

    rels = []
    for a, b in r["relationships"]:
        rels.append(
            "      <relationship>\n        <expression op='='>\n"
            f"          <expression op={quoteattr('[%s]' % a['local'])} />\n"
            f"          <expression op={quoteattr('[%s]' % b['local'])} />\n"
            "        </expression>\n"
            f"        <first-end-point object-id={quoteattr(oid[a['table']])} />\n"
            f"        <second-end-point object-id={quoteattr(oid[b['table']])} />\n"
            "      </relationship>")

    nl = "\n"
    tds = f"""<?xml version='1.0' encoding='utf-8' ?>
<datasource formatted-name={quoteattr(caption)} inline='true' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <document-format-change-manifest>
    <ObjectModelEncapsulateLegacy />
    <ObjectModelTableType />
    <SchemaViewerObjectModel />
  </document-format-change-manifest>
  <connection class='federated'>
    <named-connections>
      <named-connection caption={quoteattr(caption)} name='{conn}'>
        <connection authentication='auth-none' author-locale='en_US' class='hyper' dbname={quoteattr(hyper_member)} default-settings='yes' schema='Extract' tablename='Extract' />
      </named-connection>
    </named-connections>
    <relation type='collection'>
{nl.join('      ' + relation(t) for t in r['tables'])}
    </relation>
    <cols>
{nl.join(sorted(cols_map))}
    </cols>
    <metadata-records>
{nl.join(records)}
    </metadata-records>
  </connection>
  <aliases enabled='yes' />
{nl.join(columns)}
  <layout dim-ordering='alphabetic' measure-ordering='alphabetic' show-structure='true' />
  <object-graph>
    <objects>
{nl.join(objects)}
    </objects>
    <relationships>
{nl.join(rels)}
    </relationships>
  </object-graph>
</datasource>
"""
    handoff = [{"name": f["caption"], "datatype": f["datatype"], "role": f["role"],
                "table": f["table"], "column": f["column"],
                **({"description": f["description"]} if f["description"] else {})}
               for f in r["fields"] if not f["hidden"]]
    return tds, handoff


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("hyper", type=Path)
    ap.add_argument("model", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="output .tdsx")
    ap.add_argument("--fields-out", type=Path, help="write the data-app field list here")
    ap.add_argument("--tds-out", type=Path, help="also write the bare .tds (for inspection)")
    args = ap.parse_args()

    if args.out.suffix.lower() != ".tdsx":
        sys.exit("✗ --out must end in .tdsx")
    model = json.loads(args.model.read_text(encoding="utf-8"))
    member = f"Data/Extracts/{args.hyper.stem}.hyper"
    try:
        tds, handoff = build_tds(read_schema(args.hyper), model, member)
    except ModelError as err:
        sys.exit(f"✗ {err}")

    if args.tds_out:
        args.tds_out.write_text(tds, encoding="utf-8")
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{args.out.stem}.tds", tds)
        z.write(args.hyper, member)
    if args.fields_out:
        args.fields_out.write_text(json.dumps(handoff, indent=2) + "\n", encoding="utf-8")
    print(args.out.resolve())


if __name__ == "__main__":
    main()

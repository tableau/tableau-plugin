#!/usr/bin/env python3
"""Generate a multi-table .tds (relationships, captions, descriptions) from a .hyper
schema plus a model JSON, and package both as a .tdsx. No Tableau Desktop needed.

Model JSON:
  {
    "caption": "Data source caption",
    "tables": [
      {"schema": "public", "name": "fact_orders", "caption": "Orders",
       "columns": {"order_id": {"caption": "Order ID", "description": "...",
                                "role": "dimension", "semanticRole": "[Country].[ISO3166_2]"}}}
    ],
    "relationships": [
      {"from": {"table": "fact_orders", "column": "customer_id"},
       "to":   {"table": "dim_customer", "column": "customer_id"}}
    ]
  }

Columns missing from the model are still emitted, with default caption/role.
When a column name repeats across tables, the first table listed keeps the bare
name and later ones get "name (table)", matching Desktop.

Usage: python3 generate_tds.py HYPER MODEL.json --out OUT.tdsx [--tds-out OUT.tds]
Requires tableauhyperapi (schema read only).
"""

from __future__ import annotations

import argparse
import json
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from tableauhyperapi import Connection, HyperProcess, Telemetry, TypeTag

# Hyper type -> (remote-type, local-type, default aggregation)
TYPES = {
    TypeTag.TEXT: (129, "string", "Count"),
    TypeTag.VARCHAR: (129, "string", "Count"),
    TypeTag.CHAR: (129, "string", "Count"),
    TypeTag.BOOL: (11, "boolean", "Count"),
    TypeTag.DATE: (133, "date", "Year"),
    TypeTag.TIMESTAMP: (135, "datetime", "Year"),
    TypeTag.TIMESTAMP_TZ: (135, "datetime", "Year"),
    TypeTag.SMALL_INT: (2, "integer", "Sum"),
    TypeTag.INT: (3, "integer", "Sum"),
    TypeTag.BIG_INT: (20, "integer", "Sum"),
    TypeTag.DOUBLE: (5, "real", "Sum"),
    TypeTag.NUMERIC: (131, "real", "Sum"),
}
APOS = {"'": "&apos;"}
CONN = "hyper.generated0000000000000000"


def read_schema(hyper: Path) -> dict[tuple[str, str], list[tuple[str, TypeTag]]]:
    out = {}
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp, \
         Connection(hp.endpoint, str(hyper)) as conn:
        for schema in conn.catalog.get_schema_names():
            for table in conn.catalog.get_table_names(schema):
                cols = conn.catalog.get_table_definition(table).columns
                key = (schema.name.unescaped, table.name.unescaped)
                out[key] = [(c.name.unescaped, c.type.tag) for c in cols]
    return out


def object_id(schema: str, table: str) -> str:
    guid = uuid.uuid5(uuid.NAMESPACE_URL, f"{schema}.{table}").hex.upper()
    return f"{table} ({schema}.{table})_{guid}"


def rel(schema: str, table: str) -> str:
    return (f"<relation connection='{CONN}' name={quoteattr(table)} "
            f"table={quoteattr(f'[{schema}].[{table}]')} type='table' />")


def desc_xml(text: str) -> str:
    return ("\n    <desc>\n      <formatted-text>\n        <run>"
            f"{escape(text, APOS)}</run>\n      </formatted-text>\n    </desc>\n  ")


def build_tds(schema: dict, model: dict, hyper_member: str) -> str:
    tables = model["tables"]
    for t in tables:
        if (t["schema"], t["name"]) not in schema:
            raise SystemExit(f"table {t['schema']}.{t['name']} not in hyper")

    # Assign Tableau local names; first table listed keeps the bare column name.
    local: dict[tuple[str, str], str] = {}
    taken: set[str] = set()
    for t in tables:
        for col, _ in schema[(t["schema"], t["name"])]:
            name = col if col not in taken else f"{col} ({t['name']})"
            taken.add(name)
            local[(t["name"], col)] = name

    cols_map, records, columns, objects = [], [], [], []
    for t in tables:
        oid = object_id(t["schema"], t["name"])
        objects.append(f"      <object caption={quoteattr(t.get('caption', t['name']))} id={quoteattr(oid)}>\n"
                       f"        <properties context=''>\n          {rel(t['schema'], t['name'])}\n"
                       f"        </properties>\n      </object>")
        columns.append(f"  <column caption={quoteattr(t.get('caption', t['name']))} datatype='table' "
                       f"name={quoteattr(f'[__tableau_internal_object_id__].[{oid}]')} "
                       f"role='measure' type='quantitative' />")
        meta = t.get("columns", {})
        tname = t["name"]
        for col, tag in schema[(t["schema"], t["name"])]:
            if tag not in TYPES:
                raise SystemExit(f"unsupported Hyper type {tag} for {t['name']}.{col}")
            remote_type, local_type, agg = TYPES[tag]
            ln = local[(t["name"], col)]
            cols_map.append(f"      <map key={quoteattr(f'[{ln}]')} value={quoteattr(f'[{tname}].[{col}]')} />")
            records.append(
                "      <metadata-record class='column'>\n"
                f"        <remote-name>{escape(col)}</remote-name>\n"
                f"        <remote-type>{remote_type}</remote-type>\n"
                f"        <local-name>{escape(f'[{ln}]')}</local-name>\n"
                f"        <parent-name>{escape(f'[{tname}]')}</parent-name>\n"
                f"        <remote-alias>{escape(col)}</remote-alias>\n"
                f"        <ordinal>{len(records)}</ordinal>\n"
                f"        <local-type>{local_type}</local-type>\n"
                f"        <aggregation>{agg}</aggregation>\n"
                "        <contains-null>true</contains-null>\n"
                + ("        <collation flag='0' name='binary' />\n" if local_type == "string" else "")
                + f"        <object-id>{escape(f'[{oid}]')}</object-id>\n"
                "      </metadata-record>")
            m = meta.get(col, {})
            numeric = local_type in ("integer", "real")
            role = m.get("role", "measure" if numeric else "dimension")
            kind = ("quantitative" if role == "measure"
                    else "ordinal" if local_type in ("date", "datetime") else "nominal")
            attrs = (f"caption={quoteattr(m.get('caption', col))} datatype='{local_type}' "
                     f"name={quoteattr(f'[{ln}]')} role='{role}'")
            if m.get("semanticRole"):
                attrs += f" semantic-role={quoteattr(m['semanticRole'])}"
            attrs += f" type='{kind}'"
            body = desc_xml(m["description"]) if m.get("description") else ""
            columns.append(f"  <column {attrs}>{body}</column>" if body else f"  <column {attrs} />")

    rels = []
    for r in model.get("relationships", []):
        f, to = r["from"], r["to"]
        by_name = {t["name"]: t for t in tables}
        lhs = local[(f["table"], f["column"])]
        rhs = local[(to["table"], to["column"])]
        rels.append(
            "      <relationship>\n        <expression op='='>\n"
            f"          <expression op={quoteattr(f'[{lhs}]')} />\n"
            f"          <expression op={quoteattr(f'[{rhs}]')} />\n"
            "        </expression>\n"
            f"        <first-end-point object-id={quoteattr(object_id(by_name[f['table']]['schema'], f['table']))} />\n"
            f"        <second-end-point object-id={quoteattr(object_id(by_name[to['table']]['schema'], to['table']))} />\n"
            "      </relationship>")

    nl = "\n"
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<datasource formatted-name={quoteattr(model.get('caption', 'Data Source'))} inline='true' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <document-format-change-manifest>
    <ObjectModelEncapsulateLegacy />
    <ObjectModelTableType />
    <SchemaViewerObjectModel />
  </document-format-change-manifest>
  <connection class='federated'>
    <named-connections>
      <named-connection caption={quoteattr(model.get('caption', 'extract'))} name='{CONN}'>
        <connection authentication='auth-none' author-locale='en_US' class='hyper' dbname={quoteattr(hyper_member)} default-settings='yes' schema='Extract' tablename='Extract' />
      </named-connection>
    </named-connections>
    <relation type='collection'>
{nl.join('      ' + rel(t['schema'], t['name']) for t in tables)}
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("hyper", type=Path)
    ap.add_argument("model", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="output .tdsx")
    ap.add_argument("--tds-out", type=Path, help="also write the .tds here")
    args = ap.parse_args()

    model = json.loads(args.model.read_text())
    member = f"Data/Extracts/{args.hyper.name}"
    tds = build_tds(read_schema(args.hyper), model, member)
    if args.tds_out:
        args.tds_out.write_text(tds, encoding="utf-8")
    stem = args.out.stem
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{stem}.tds", tds)
        z.write(args.hyper, member)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Profile a .hyper and draft a model JSON for generate_tds.py.

Per column: type, null count, distinct count, min/max (numbers, dates), and the
top values of low-cardinality text columns. That's enough to write captions and
descriptions without pulling rows into context. Also checks relationship keys:
the "one" side should be unique, and orphan rows on the "many" side show up
under a null dimension value in Tableau.

Usage:
  python3 profile_hyper.py HYPER [--model-out MODEL.json] [--check FACT.COL=DIM.COL ...]

--model-out writes a skeleton model (every table and column, default captions
and roles, candidate relationships when they form a single tree). Edit it, then
pass it to generate_tds.py. Existing files are not overwritten.

Stdout is JSON: {"tables": [...], "relationshipCandidates": [...], "checks": [...]}.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_tds import TYPES, default_caption  # noqa: E402

from tableauhyperapi import (Connection, HyperProcess, Telemetry,  # noqa: E402
                             TableName, escape_name)

TOP_VALUES_MAX_DISTINCT = 25


def scalar(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def profile_table(conn, schema: str, table: str) -> dict:
    tn = TableName(schema, table)
    rows = conn.execute_scalar_query(f"SELECT COUNT(*) FROM {tn}")
    cols = []
    for c in conn.catalog.get_table_definition(tn).columns:
        name, tag = c.name.unescaped, c.type.tag.name
        q = escape_name(name)
        nulls, distinct = conn.execute_list_query(
            f"SELECT COUNT(*) - COUNT({q}), COUNT(DISTINCT {q}) FROM {tn}")[0]
        info = {"name": name, "hyperType": tag,
                "datatype": TYPES.get(tag, (None, None))[1], "nulls": nulls, "distinct": distinct}
        if tag not in TYPES:
            info["unsupported"] = True
        elif TYPES[tag][1] in ("integer", "real", "date", "datetime"):
            lo, hi = conn.execute_list_query(f"SELECT MIN({q}), MAX({q}) FROM {tn}")[0]
            info["min"], info["max"] = scalar(lo), scalar(hi)
        elif TYPES[tag][1] in ("string", "boolean") and distinct <= TOP_VALUES_MAX_DISTINCT:
            info["values"] = [[scalar(v), n] for v, n in conn.execute_list_query(
                f"SELECT {q}, COUNT(*) FROM {tn} GROUP BY 1 ORDER BY 2 DESC LIMIT 10")]
        cols.append(info)
    return {"schema": schema, "name": table, "rows": rows, "columns": cols}


def check_key(conn, tables: dict, many: tuple[str, str], one: tuple[str, str]) -> dict:
    def ref(side):
        t = tables.get(side[0])
        if not t or side[1] not in {c["name"] for c in t["columns"]}:
            raise SystemExit(f"✗ {side[0]}.{side[1]} is not a column in the hyper")
        return TableName(t["schema"], t["name"]), escape_name(side[1])

    (mt, mc), (ot, oc) = ref(many), ref(one)
    one_rows, one_distinct = conn.execute_list_query(
        f"SELECT COUNT({oc}), COUNT(DISTINCT {oc}) FROM {ot}")[0]
    many_rows, orphans, null_keys = conn.execute_list_query(
        f"SELECT COUNT(*), COUNT(*) FILTER (WHERE m.{mc} IS NOT NULL AND o.k IS NULL), "
        f"COUNT(*) FILTER (WHERE m.{mc} IS NULL) "
        f"FROM {mt} m LEFT JOIN (SELECT DISTINCT {oc} AS k FROM {ot}) o ON m.{mc} = o.k")[0]
    result = {"from": f"{many[0]}.{many[1]}", "to": f"{one[0]}.{one[1]}",
              "toUnique": one_rows == one_distinct, "toDuplicateKeys": one_rows - one_distinct,
              "fromRows": many_rows, "fromOrphans": orphans, "fromNullKeys": null_keys}
    notes = []
    if not result["toUnique"]:
        notes.append(f"{one[0]}.{one[1]} has duplicate keys; the relationship will be many-to-many")
    if orphans or null_keys:
        pct = 100 * (orphans + null_keys) / max(many_rows, 1)
        notes.append(f"{orphans + null_keys} {many[0]} rows ({pct:.1f}%) have no match in "
                     f"{one[0]}; they show under a null {one[0]} value")
    result["notes"] = notes
    return result


def candidates(tables: dict) -> list[dict]:
    """Same-named, same-typed columns where one side is unique: many -> one."""
    out = []
    names = list(tables)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ca = {c["name"]: c for c in tables[a]["columns"]}
            cb = {c["name"]: c for c in tables[b]["columns"]}
            for col in ca.keys() & cb.keys():
                x, y = ca[col], cb[col]
                if x["datatype"] != y["datatype"] or x["datatype"] is None:
                    continue
                x_unique = x["distinct"] == tables[a]["rows"] - x["nulls"]
                y_unique = y["distinct"] == tables[b]["rows"] - y["nulls"]
                if y_unique and not x_unique:
                    out.append({"from": {"table": a, "column": col}, "to": {"table": b, "column": col}})
                elif x_unique and not y_unique:
                    out.append({"from": {"table": b, "column": col}, "to": {"table": a, "column": col}})
    return out


def skeleton(tables: dict, rels: list[dict]) -> dict:
    connected = len(rels) == len(tables) - 1 and \
        len({r["from"]["table"] for r in rels} | {r["to"]["table"] for r in rels}) == len(tables)
    # The table on the "many" side of the most relationships goes first (keeps bare names).
    order = sorted(tables, key=lambda n: -sum(r["from"]["table"] == n for r in rels))
    seen: set[str] = set()
    out_tables = []
    for n in order:
        columns = {}
        for c in tables[n]["columns"]:
            # Repeated column names get the table caption, matching generate_tds.py's default.
            caption = default_caption(c["name"])
            if c["name"] in seen:
                caption = f"{caption} ({default_caption(n)})"
            seen.add(c["name"])
            columns[c["name"]] = {"caption": caption, "description": ""}
        out_tables.append({"schema": tables[n]["schema"], "name": n,
                           "caption": default_caption(n), "columns": columns})
    return {
        "caption": "",
        "description": "",
        "tables": out_tables,
        "relationships": rels if connected else [],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("hyper", type=Path)
    ap.add_argument("--model-out", type=Path)
    ap.add_argument("--check", action="append", default=[], metavar="FACT.COL=DIM.COL")
    args = ap.parse_args()

    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters={"log_config": ""}) as hp, \
         Connection(hp.endpoint, str(args.hyper)) as conn:
        tables = {}
        for schema in conn.catalog.get_schema_names():
            for t in conn.catalog.get_table_names(schema):
                p = profile_table(conn, schema.name.unescaped, t.name.unescaped)
                tables[p["name"]] = p
        rels = candidates(tables)
        checks = []
        for spec in args.check:
            many, _, one = spec.partition("=")
            if "." not in many or "." not in one:
                raise SystemExit(f"✗ expected FACT.COL=DIM.COL, got {spec!r}")
            checks.append(check_key(conn, tables, tuple(many.split(".", 1)), tuple(one.split(".", 1))))

    if args.model_out:
        if args.model_out.exists():
            raise SystemExit(f"✗ {args.model_out} exists; not overwriting")
        args.model_out.write_text(json.dumps(skeleton(tables, rels), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tables": list(tables.values()), "relationshipCandidates": rels,
                      "checks": checks}, indent=2))


if __name__ == "__main__":
    main()

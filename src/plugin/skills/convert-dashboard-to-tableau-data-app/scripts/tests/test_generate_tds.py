"""
Model validation and .tds structure for generate_tds.py. Pure: no Hyper API needed
(the schema is passed in the shape read_schema returns).
"""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from generate_tds import ModelError, build_tds, default_caption

SCHEMA = {
    ("public", "fact_orders"): [("order_id", "BIG_INT"), ("customer_id", "BIG_INT"),
                                ("order_date", "DATE"), ("amount", "NUMERIC"), ("note", "TEXT")],
    ("public", "dim_customer"): [("customer_id", "BIG_INT"), ("region", "TEXT"),
                                 ("signup_ts", "TIMESTAMP_TZ")],
}


def model(**overrides):
    m = {
        "caption": "Orders",
        "tables": [
            {"schema": "public", "name": "fact_orders", "caption": "Orders", "columns": {
                "order_id": {"caption": "Order ID", "role": "dimension", "description": "One row per order."},
                "customer_id": {"caption": "Customer ID (Orders)", "hidden": True},
                "note": {"caption": "Note", "description": "It's free text & <unescaped>"},
            }},
            {"schema": "public", "name": "dim_customer", "caption": "Customers", "columns": {
                "customer_id": {"caption": "Customer ID", "role": "dimension"},
                "region": {"caption": "Region", "semanticRole": "[Country].[ISO3166_2]"},
            }},
        ],
        "relationships": [{"from": {"table": "fact_orders", "column": "customer_id"},
                           "to": {"table": "dim_customer", "column": "customer_id"}}],
    }
    m.update(overrides)
    return m


def build(m=None, schema=SCHEMA):
    tds, fields = build_tds(schema, m or model(), "Data/Extracts/orders.hyper")
    return ET.fromstring(tds.encode()), fields


def columns(root):
    return {c.get("name"): c for c in root.findall("column")}


def test_duplicate_column_names_follow_desktop_rule():
    root, _ = build()
    maps = {m.get("key"): m.get("value") for m in root.iter("map")}
    assert maps["[customer_id]"] == "[fact_orders].[customer_id]"
    assert maps["[customer_id (dim_customer)]"] == "[dim_customer].[customer_id]"
    rel = root.find("object-graph/relationships/relationship/expression")
    assert [e.get("op") for e in rel] == ["[customer_id]", "[customer_id (dim_customer)]"]


def test_every_hyper_column_is_mapped_and_recorded():
    root, _ = build()
    assert len(root.findall(".//metadata-record")) == 8
    assert len(list(root.iter("map"))) == 8
    ordinals = [int(r.find("ordinal").text) for r in root.iter("metadata-record")]
    assert ordinals == list(range(8))


def test_captions_roles_types_and_descriptions():
    root, _ = build()
    cols = columns(root)
    assert cols["[order_id]"].get("role") == "dimension"
    assert cols["[order_id]"].find("desc/formatted-text/run").text == "One row per order."
    assert cols["[note]"].find("desc/formatted-text/run").text == "It's free text & <unescaped>"
    assert cols["[amount]"].get("caption") == "Amount"
    assert (cols["[amount]"].get("role"), cols["[amount]"].get("type")) == ("measure", "quantitative")
    assert cols["[order_date]"].get("type") == "ordinal"
    assert cols["[region]"].get("semantic-role") == "[Country].[ISO3166_2]"
    assert cols["[customer_id]"].get("hidden") == "true"
    assert cols["[signup_ts]"].get("datatype") == "datetime"


def test_object_graph_and_table_captions():
    root, _ = build()
    objs = root.findall("object-graph/objects/object")
    assert [o.get("caption") for o in objs] == ["Orders", "Customers"]
    ids = {o.get("id") for o in objs}
    rel = root.find("object-graph/relationships/relationship")
    assert {rel.find("first-end-point").get("object-id"),
            rel.find("second-end-point").get("object-id")} == ids
    table_cols = [c for c in root.findall("column") if c.get("datatype") == "table"]
    assert len(table_cols) == 2
    for r in root.iter("metadata-record"):
        assert r.find("object-id").text.strip("[]") in ids


def test_connection_points_at_packaged_hyper():
    root, _ = build()
    inner = root.find("connection/named-connections/named-connection/connection")
    assert inner.get("dbname") == "Data/Extracts/orders.hyper"
    conn_name = root.find("connection/named-connections/named-connection").get("name")
    assert all(r.get("connection") == conn_name for r in root.iter("relation") if r.get("type") == "table")


def test_handoff_fields_use_captions_and_skip_hidden():
    _, fields = build()
    by_name = {f["name"]: f for f in fields}
    assert "Customer ID (Orders)" not in by_name
    assert by_name["Order ID"] == {"name": "Order ID", "datatype": "integer", "role": "dimension",
                                   "table": "fact_orders", "column": "order_id",
                                   "description": "One row per order."}
    assert by_name["Amount"]["datatype"] == "real" and by_name["Amount"]["role"] == "measure"


def test_default_caption_for_unmodeled_duplicate_includes_table_caption():
    m = model()
    del m["tables"][1]["columns"]["customer_id"]
    m["tables"][0]["columns"]["customer_id"] = {}
    _, fields = build(m)
    names = {f["name"] for f in fields}
    assert {"Customer ID", "Customer ID (Customers)"} <= names


def test_single_table_model_needs_no_relationships():
    schema = {("public", "t"): [("a", "TEXT")]}
    root, _ = build({"tables": [{"schema": "public", "name": "t"}]}, schema)
    assert root.find("object-graph/relationships") is not None
    assert len(root.findall("object-graph/objects/object")) == 1


@pytest.mark.parametrize("mutate, message", [
    (lambda m: m["tables"][0]["columns"].update(typo={}), "model columns not in the hyper: typo"),
    (lambda m: m["tables"][0].update(name="nope"), "public.nope is not in the hyper"),
    (lambda m: m["tables"][1]["columns"]["region"].update(caption="Order ID"), "caption 'Order ID' is used by both"),
    (lambda m: m["relationships"].clear(), "need exactly 1 relationship"),
    (lambda m: m["relationships"][0]["to"].update(column="region"), "key types differ"),
    (lambda m: m["relationships"][0]["to"].update(column=["a", "b"]), "composite relationship keys"),
    (lambda m: m["relationships"][0]["to"].update(table="fact_orders", column="order_id"), "creates a loop"),
    (lambda m: m["tables"][0]["columns"]["order_id"].update(role="metric"), "role must be dimension or measure"),
])
def test_model_errors(mutate, message):
    m = model()
    mutate(m)
    with pytest.raises(ModelError, match=message.replace("(", r"\(")):
        build(m)


def test_unsupported_hyper_type():
    schema = {("public", "t"): [("g", "GEOGRAPHY")]}
    with pytest.raises(ModelError, match="GEOGRAPHY isn't supported"):
        build({"tables": [{"schema": "public", "name": "t"}]}, schema)


@pytest.mark.parametrize("column, role", [
    ("order_id", "dimension"), ("id", "dimension"), ("customerId", "dimension"), ("ID", "dimension"),
    ("amount", "measure"), ("paid", "measure"), ("valid_count", "measure"),
])
def test_default_role_treats_key_names_as_dimensions(column, role):
    schema = {("public", "t"): [(column, "BIG_INT")]}
    _, fields = build({"tables": [{"schema": "public", "name": "t"}]}, schema)
    assert fields[0]["role"] == role


@pytest.mark.parametrize("raw, caption", [
    ("signup_ts", "Signup Ts"), ("customer_id", "Customer ID"), ("orderDate", "Order Date"),
    ("site_luid", "Site LUID"), ("x", "X"),
])
def test_default_caption(raw, caption):
    assert default_caption(raw) == caption


def test_cli_rejects_non_tdsx_output(tmp_path):
    script = Path(__file__).resolve().parents[1] / "generate_tds.py"
    (tmp_path / "m.json").write_text(json.dumps(model()))
    result = subprocess.run([sys.executable, str(script), "x.hyper", str(tmp_path / "m.json"),
                             "--out", str(tmp_path / "o.zip")], capture_output=True, text=True)
    assert result.returncode == 1 and "--out must end in .tdsx" in result.stderr
